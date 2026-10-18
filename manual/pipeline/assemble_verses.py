# pipeline/assemble_verses.py
# Stage 2 for verse-anthology books (layout "verses" in book_meta.json, e.g. Padyāvalī): per-page OCR → chapters → verses → (Sanskrit, word-for-word, translation, poet).
# Drops running headers, page numbers and decorations, and re-joins text that a page break split in two. Prose books use assemble_prose.py.
# Usage: poetry run python pipeline/assemble_verses.py padyavali   → output/<book>/2-assembled/{book.json, report.txt}

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import difflib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict

from ocr_text import (PICTURE_LABELS, WORD_RE, add_paragraph, ascii_key, best_match, blank_pages, clean_inline, drop_back_cover,
                      is_all_italic, join_lines, ocr_pages, plain)

DROP_LABELS = {"PageHeader", "PageFooter", "Picture", "Figure"}
# The "Verse" headings use a script font and specks on the scan get read as punctuation (seen: "Terse 45", "Verse .90", "Verse 28.3")
VERSE_RE = re.compile(r"^\W*[A-Za-z]erse\W*(\d[\d.,\s]*)\W*$", re.I)
TRANSLATION_RE = re.compile(r"^Translation\s+(\d+)$", re.I)
EN_TITLE_RE = re.compile(r"^\(.*\)$", re.S)
# Some chapter headings arrive as one block: "Draupadī-trāṇe tad-vākyam\n(Draupadī's Appeal for Protection)"
COMBINED_TITLE_RE = re.compile(r"^([^\n()]+)\n\((.+)\)$", re.S)
# Printed contents entries pair an English title in brackets with a page number — OCR puts the number either before or after it
TOC_NUMBER_FIRST_RE = re.compile(r"(\d{1,3})\s*\(([^)]{6,})\)")
TOC_TITLE_FIRST_RE = re.compile(r"\(([^)]{6,})\)\s*(\d{1,3})")
# A word-for-word gloss starts like "padyā—of Verses;" or "kam prati—unto whom;" — up to 3 words, an em dash, then its meaning
WFW_START_RE = re.compile(r"^[^\s—;.,]{1,40}(?: [^\s—;.,]{1,40}){0,2}—")


@dataclass
class Verse:
    number: int
    pages: list = field(default_factory=list)
    sanskrit: list = field(default_factory=list)  # one string per printed line
    word_for_word: str = ""
    translations: list = field(default_factory=list)  # [{"label": "Translation 1" | None, "paragraphs": [...]}]
    poet: str = ""
    notes: list = field(default_factory=list)  # prose that appears after the poet line, if any


@dataclass
class Chapter:
    title: str  # Sanskrit title, e.g. "Nāma-māhātmya"
    title_en: str  # English title without brackets, e.g. "The Glory of the Holy Name"
    start_page: int
    intro: list = field(default_factory=list)
    verses: list = field(default_factory=list)
    pictures: list = field(default_factory=list)  # [{"page": n, "bbox": [...]}] — chapter illustrations, for later reuse


def verse_number(match) -> int:
    return int(re.sub(r"\D", "", match.group(1)))


def looks_like_gloss(p: str) -> bool:
    """Word-for-word text is a run of "word—meaning;" items; a translation is prose with at most a stray dash."""
    items = re.findall(r"[^\s;]—[^;—]+[;.]", p)
    return len(items) >= 2 or (len(items) == 1 and len(p) < 100)


def is_poet_line(text: str) -> bool:
    p = plain(text)
    # Usually an em dash, but some pages print a plain hyphen ("-Śrī Dakṣiṇātya")
    return (p.startswith(("—", "–")) or re.match(r"^-\s?[A-ZŚṢĀĪŪṚ]", p) is not None) and len(p) < 80


def looks_like_chapter_title(title: str, english: str) -> bool:
    """Title + bracketed English name. A poet line or a sentence followed by a bracketed footnote — "—Śrī Rūpa Gosvāmī" + "(Note: …)",
    "Rādhā: … together." + "(Here She interprets …)" — has the same shape, so rule those out."""
    return (title.count("\n") <= 2 and len(title) < 120 and not VERSE_RE.match(title) and not EN_TITLE_RE.match(title)
            and not is_poet_line(title) and not title.rstrip().endswith(".")
            and not english[1:].lstrip().lower().startswith(("note", "here")))


def load_blocks(book: str):
    """All text blocks of the book in reading order, with page numbers; pictures kept separately."""
    blocks, pictures = [], []
    for page_no, page_blocks in ocr_pages(book):
        for b in page_blocks:
            if b["label"] in PICTURE_LABELS:
                pictures.append({"page": page_no, "bbox": b.get("bbox")})
            elif b["html"].strip():
                text = clean_inline(b["html"])
                # A "Verse N" at the top of a page sometimes gets labelled PageHeader — keep it, drop real headers/footers
                if not plain(text) or (b["label"] in DROP_LABELS and not VERSE_RE.match(plain(text))):
                    continue
                # OCR sometimes glues the Sanskrit lines and the start of the word-for-word into one block; split at the first gloss line
                lines = text.split("\n")
                first_gloss = next((k for k, ln in enumerate(lines) if k > 0 and WFW_START_RE.match(plain(ln))), None)
                if first_gloss and not any("—" in plain(ln) for ln in lines[:first_gloss]):
                    blocks.append({"page": page_no, "label": b["label"], "text": "\n".join(lines[:first_gloss])})
                    text = plain("\n".join(lines[first_gloss:]))
                # OCR sometimes glues the poet line ("—Śrī Dākṣiṇātya") onto the translation; split it back out
                body, _, last = text.rpartition("\n")
                if body and is_poet_line(last):
                    blocks.append({"page": page_no, "label": b["label"], "text": body})
                    text = last
                blocks.append({"page": page_no, "label": b["label"], "text": text})
    # Back cover = ISBN page plus cover pages before it, never a page holding a verse heading or poet line
    verse_pages = {b["page"] for b in blocks if is_poet_line(b["text"]) or VERSE_RE.match(plain(b["text"]))}
    return drop_back_cover(blocks, max(verse_pages, default=0), verse_pages), pictures


def assemble(blocks, pictures):
    intro, chapters, skipped_pages, front_text = [], [], set(), []
    chapter, verse, state = None, None, "front"  # states: front → intro → (sanskrit → wfw → translation → done) per verse

    for i, blk in enumerate(blocks):
        text, page = blk["text"], blk["page"]
        p = plain(text)
        nxt = plain(blocks[i + 1]["text"]) if i + 1 < len(blocks) else ""
        nxt2 = plain(blocks[i + 2]["text"]) if i + 2 < len(blocks) else ""

        # Everything before the Introduction is title pages, publisher catalogue and contents — regenerated later, so skipped
        if state == "front":
            if p.lower() == "introduction":
                state = "intro"
            else:
                skipped_pages.add(page)
                front_text.append(p)  # kept so the printed contents can be cross-checked later
            continue

        # Chapter title: a short heading (1–3 lines) followed by its English name in brackets — as the next block or on its last line.
        # Never right after "Verse N": that slot holds the Sanskrit, which is also multi-line italics.
        combined = COMBINED_TITLE_RE.match(p)
        if combined and not looks_like_chapter_title(combined.group(1), "(" + combined.group(2) + ")"):
            combined = None
        is_title = EN_TITLE_RE.match(nxt) and looks_like_chapter_title(p, nxt)
        # Sometimes the OCR drops the brackets around the English name; the shape heading → heading → "Verse N" still marks a chapter
        bare_pair = (blk["label"] == "SectionHeader" and i + 1 < len(blocks) and blocks[i + 1]["label"] == "SectionHeader"
                     and VERSE_RE.match(nxt2) and not VERSE_RE.match(nxt) and looks_like_chapter_title(p, "(" + nxt + ")"))
        if state != "sanskrit" and (combined or is_title or bare_pair):
            title = combined.group(1) if combined else p
            chapter = Chapter(title=re.sub(r"\s+", " ", title).strip(), title_en="", start_page=page)
            chapter.pictures = [pic for pic in pictures if pic["page"] in (page - 1, page)]
            chapters.append(chapter)
            verse, state = None, "chapter-title"
            if combined:
                chapter.title_en = re.sub(r"\s+", " ", combined.group(2)).strip()
                state = "chapter-intro"
            elif bare_pair and not is_title:
                chapter.title_en = re.sub(r"\s+", " ", nxt).strip()
                state = "chapter-title-done"  # the next block is the bracket-less English name, already used
            continue
        if state == "chapter-title-done":
            state = "chapter-intro"
            continue
        if state == "chapter-title" and EN_TITLE_RE.match(p):
            chapter.title_en = re.sub(r"\s+", " ", p[1:-1]).strip()
            state = "chapter-intro"
            continue

        m = VERSE_RE.match(p)
        if m and chapter:
            verse = Verse(number=verse_number(m), pages=[page])
            chapter.verses.append(verse)
            state = "sanskrit"
            continue

        if state == "intro":
            add_paragraph(intro, text)
            continue
        if state == "chapter-intro":
            add_paragraph(chapter.intro, text)
            continue

        if page not in verse.pages:
            verse.pages.append(page)

        t = TRANSLATION_RE.match(p)
        if t:
            verse.translations.append({"label": p, "paragraphs": []})
            state = "translation"
        elif is_poet_line(text):
            verse.poet = p.lstrip("—– ").strip()
            state = "done"
        elif state == "sanskrit" and (is_all_italic(text) or not WFW_START_RE.match(p)) and "—" not in p:
            verse.sanskrit += [plain(line) for line in text.split("\n") if plain(line)]
        elif state == "wfw" and not verse.word_for_word.rstrip().endswith(".") and looks_like_gloss(p):
            verse.word_for_word += " " + join_lines(p)  # gloss list continued after a page break
        # Checking the gloss shape keeps a translation that happens to open with "word—" from being swallowed
        elif state in ("sanskrit", "wfw") and WFW_START_RE.match(p) and looks_like_gloss(p):
            verse.word_for_word = (verse.word_for_word + " " + join_lines(p)).strip()
            state = "wfw"
        elif state == "done":
            add_paragraph(verse.notes, text)
        else:
            if not verse.translations:
                verse.translations.append({"label": None, "paragraphs": []})
            add_paragraph(verse.translations[-1]["paragraphs"], text)
            state = "translation"

    return intro, chapters, sorted(skipped_pages), "\n".join(front_text)


TITLE_MATCH_RATIO = 0.85  # same title read twice by OCR (contents page vs chapter page) differs by a few letters at most


def contents_entries(front_text: str) -> list[tuple[int, str]]:
    """(printed page, English title) pairs read from the book's contents pages."""
    pairs = TOC_NUMBER_FIRST_RE.findall(front_text) + [(n, en) for en, n in TOC_TITLE_FIRST_RE.findall(front_text)]
    return sorted({ascii_key(en): (int(n), re.sub(r"\s+", " ", en).strip()) for n, en in pairs}.values())


def reconcile_titles(chapters, entries, vocab: Counter) -> list[str]:
    """The contents page and the chapter page are two independent OCR readings of each English title.
    Where they differ slightly (e.g. 'Goṭī' vs 'Gopī'), keep the reading whose words the rest of the book uses more often."""
    notes = []
    for ch in chapters:
        listed, ratio = best_match(ch.title_en, [en for _, en in entries])
        if ratio < TITLE_MATCH_RATIO or listed == ch.title_en:
            continue
        ours, theirs = set(WORD_RE.findall(ch.title_en)), set(WORD_RE.findall(listed))
        only_ours, only_theirs = ours - theirs, theirs - ours
        # Only fix letter-level typos ('Goṭī'/'Gopī'), never swap a whole word — 'Nature'/'Glory' are two different chapters
        typo_pairs = all(max((difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() for b in only_theirs), default=0) >= 0.6 for a in only_ours)
        if typo_pairs and len(only_ours) == len(only_theirs) and sum(vocab[w] for w in only_theirs) > sum(vocab[w] for w in only_ours):
            notes.append(f"      ~ p{ch.start_page}: title corrected '{ch.title_en}' → '{listed}' (contents page reading, more common in the book)")
            ch.title_en = listed
    return notes


def check_against_contents(chapters, entries, last_page: int) -> list[str]:
    """Compare detected chapters with the book's printed contents page — catches chapters the heading rules missed."""
    found = [c.title_en for c in chapters]
    # Printed page numbers run 2 behind PDF pages (two cover pages); only check chapters the OCR has reached
    reached = [(n, en) for n, en in entries if n + 2 <= last_page]
    missing = [f"      ! contents lists '{en}' (printed p{n}) but no chapter was detected" for n, en in reached if best_match(en, found)[1] < TITLE_MATCH_RATIO]
    return [f"Contents check: {len(reached)} listed chapters within OCR'd pages, {len(reached) - len(missing)} found"] + missing


def build_report(chapters) -> list[str]:
    """Sanity checks a human should look at: verse-number gaps and verses missing a part."""
    lines, expected = [], None
    for ch in chapters:
        lines.append(f"p{ch.start_page:>3}  {ch.title} — {ch.title_en}  ({len(ch.verses)} verses)")
        for v in ch.verses:
            if expected is not None and v.number != expected:
                lines.append(f"      ! verse numbering jumps from {expected - 1} to {v.number}")
            expected = v.number + 1
            missing = [name for name, val in (("sanskrit", v.sanskrit), ("word-for-word", v.word_for_word), ("translation", v.translations), ("poet", v.poet)) if not val]
            if missing:
                lines.append(f"      ! verse {v.number} (p{v.pages[0]}) has no {', '.join(missing)}")
    return lines


def main():
    book = local_env.find_book(sys.argv[1]).stem
    blocks, pictures = load_blocks(book)
    intro, chapters, skipped, front_text = assemble(blocks, pictures)
    entries = contents_entries(front_text)
    vocab = Counter(w for b in blocks for w in WORD_RE.findall(plain(b["text"])))
    corrections = reconcile_titles(chapters, entries, vocab)

    out_dir = local_env.stage_dir(book, "assembled")
    data = {"book": book, "intro": intro, "chapters": [asdict(c) for c in chapters]}
    (out_dir / "book.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    last_page = max(b["page"] for b in blocks)
    # A page whose OCR came back empty (e.g. misread as one big picture) silently loses its verses — list them for a re-check
    blank = blank_pages(blocks, chapters[0].start_page if chapters else 1)
    report = [f"Skipped front-matter pages: {skipped}", f"{len(chapters)} chapters, {sum(len(c.verses) for c in chapters)} verses"]
    report.append(f"Pages with no text after the first chapter (illustrations, or failed OCR — check): {blank}")
    report += check_against_contents(chapters, entries, last_page) + corrections + [""] + build_report(chapters)
    (out_dir / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[:2]))
    print(f"Wrote {out_dir}")


if __name__ == "__main__":
    main()
