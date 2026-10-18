# manual/pipeline/assemble_prose.py
# Stage 2 for prose books (layout "prose" in book_meta.json, e.g. Vraja-līlā): per-page OCR → sections → typed blocks.
# Sections come from the book's own contents list, matched in order, so none can be missed or invented — including Parts, and index
# sections that are dropped. Block types: paragraph, verse quote, source, signature, subheading, figure, scene break and endnote.
# Verse anthologies use assemble_verses.py instead.
# Usage: poetry run python manual/pipeline/assemble_prose.py <path/to/book.pdf> --library <path/to/book-library>   → output/<book>/2-assembled/{book.json, report.txt}

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import difflib
from collections import Counter
import json
import re
from dataclasses import dataclass, field, asdict

from figures import is_illustration
from ocr_text import PICTURE_LABELS, apply_text_fixes, ascii_key, blank_pages, clean_inline, drop_back_cover, ends_sentence, is_all_italic, join_lines, ocr_pages, plain

META_FILE = local_env.META_FILE
MARGIN_LABELS = {"PageHeader", "PageFooter"}
# Contents lines look like "Kokilavan – 41" or "Foreword – x"
TOC_LINE_RE = re.compile(r"^(.+?)\s*[–—-]\s*([ivxlc]+|\d{1,3})$", re.I)
PAGE_NUMBER_RE = re.compile(r"^\W*([ivxlc]+|\d{1,3})\W*$", re.I)
# Table-style contents rows: "1. Preface", "Part 1: Kusuma-sarovara", "Chapter 1: The Gardener of Govardhana"
TOC_PART_RE = re.compile(r"^Part\s+(\d+)\s*:\s*(.+)$", re.I)
TOC_BOOK_RE = re.compile(r"^((?:BOOK|PART)\s+[A-Z]+)\s*:\s*(.+)$", re.I)  # "BOOK ONE: FROM THE MYSTIC WEST 1967–68"
TOC_NUMBERED_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z].+)$")  # "1 Children of the Fifties"
TOC_CHAPTER_RE = re.compile(r"^Chapter\s+(\d+)\s*:\s*(.+)$", re.I)
SCENE_BREAK_RE = re.compile(r"^\*(\s*\*)+$")
PART_LABEL_RE = re.compile(r"^PART\s+[A-Z]+$", re.I)  # "PART ONE" under a part title
NOTE_START_RE = re.compile(r"^\d{1,3}\.\s")
# Roman-numbered chapters ("IV. Vivāha-saṁskāra: Marriage", "XVII Vidyārambha…") and their numbered sub-sections ("IV.2.", "1.2.4.")
TOC_ROMAN_RE = re.compile(r"^([IVXL]+)\.?\s+(\S.+)$")
TOC_SUBSECTION_RE = re.compile(r"^[IVXL1]+\.\d")
# A contents row holding only a label ("Chapter One", "Appendix 1 B"); the title follows on its own row
TOC_LABEL_RE = re.compile(r"^(Chapter|Appendix)\s+[\w-]+(\s+[A-Z])?$", re.I)  # "Chapter Twenty-Seven" too
# The matching label printed above a chapter's title ("CHAPTER 1", "CHAPTER TWO") — the typesetter prints its own
HEADING_LABEL_RE = re.compile(r"^((CHAPTER|APPENDIX)\s+[A-Z0-9]+(\s+[A-Z])?|\d{1,2})$", re.I)  # also a bare "1" above the title
_NUMBER_WORDS = sorted("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
                       "eighteen nineteen twenty thirty forty fifty".split(), key=len, reverse=True)
NUMBERED_LABEL_RE = re.compile(rf"^(chapter|part|book)\s*({'|'.join(_NUMBER_WORDS)})(-({'|'.join(_NUMBER_WORDS)}))?\s*", re.I)
HEADING_PREFIX_RE = re.compile(r"^(chapter|appendix)\s+\w+(\s+[a-z])?\s*:\s*", re.I)  # "APPENDIX 2: " in front of a title
# Footnote text opening with its number ("15 It is beyond…", "<sup>3</sup> From…")
NOTE_NUMBER_RE = re.compile(r"^\s*(?:<sup>(\d{1,3})</sup>\s*|(\d{1,3})\.?\s+)(?=\S)")
# A date line under a chapter title: "August–October 1970", "November 27, 1971–February 24, 1972"
DATE_RE = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b.*\d", re.I)
NOTE_WINDOW = 3  # a mislabelled block counts as a footnote only if its number is at most this far past the last note seen
LOOKAHEAD = 4  # contents entries to look ahead, so one heading the OCR garbled can't block every chapter after it
FRONT_TITLES = {"preface", "foreword", "introduction", "dedication", "acknowledgments", "acknowledgements"}
TITLE_MATCH_RATIO = 0.85


@dataclass
class Section:
    kind: str  # "front" (Foreword, Preface…), "part" (part title page), "chapter" (numbered), "back" (unnumbered closing section) or "drop" (indexes)
    title: str
    subtitle: str
    start_page: int
    cover: dict | None = None  # Part pages: the original full-page painting the part title is printed on
    numeral: str = ""  # original chapter numeral from the contents ("IV"), used to repair sub-section numbers
    footnotes: list = field(default_factory=list)  # page-bottom footnotes, moved to the section's Notes
    blocks: list = field(default_factory=list)  # {"type": "p"|"epigraph"|"quote"|"cite"|"sign"|"sign-detail"|"h"|"figure"|"break"|"notes-h"|"note"|"entry", ...}


def text_shapes(page_blocks) -> dict:
    """Indentation of each body-text block against the page's own text margins (block reading_order → shape).
    'inset': indented on both sides — a quoted passage. 'hanging': indented on the left only but running to the right
    margin — the rest of a footnote carried over from the previous page (its lines hang under the note number)."""
    text = [b for b in page_blocks if b["label"] in ("Text", "Footnote") and (b["html"] or "").strip()]
    if len(text) < 2:
        return {}
    width = text[0]["image_bbox"][2]
    left, right = min(b["bbox"][0] for b in text), max(b["bbox"][2] for b in text)
    shapes = {}
    for b in text:
        x0, x1 = b["bbox"][0], b["bbox"][2]
        if x0 - left >= 0.03 * width and x1 - x0 >= 0.6 * width:  # wide enough to be several lines, not a short indented line
            shapes[b["reading_order"]] = "inset" if right - x1 >= 0.025 * width else "hanging" if right - x1 < 0.012 * width else ""
    return shapes


def facsimile(page_no: int, page_blocks) -> list[dict]:
    """A page printing a document as a picture (a newspaper clipping, a letter from Śrīla Prabhupāda): everything above its
    caption becomes one picture — never retyped as book text — and the caption (the last text block) stays its caption."""
    content = [b for b in page_blocks if b["label"] not in ("PageHeader", "PageFooter")]
    texts = [b for b in content if b["label"] in ("Text", "Caption") and (b["html"] or "").strip()]
    caption = texts[-1] if texts else None
    body = [b for b in content if b is not caption]
    bbox = [min(b["bbox"][0] for b in body), min(b["bbox"][1] for b in body), max(b["bbox"][2] for b in body), max(b["bbox"][3] for b in body)]
    out = [{"page": page_no, "label": "Picture", "text": "", "bbox": bbox, "image_bbox": content[0]["image_bbox"]}]
    if caption:
        out.append({"page": page_no, "label": "Caption", "text": clean_inline(caption["html"]), "html": "", "shape": "", "rule": False})
    return out


def load_blocks(book: str, academic: bool = False, facsimiles: set = frozenset(), inset_quotes: bool = False, running_heads: list = ()):
    """Text and picture blocks in reading order, plus the set of pages carrying a printed page number (i.e. real book pages, not covers).
    Academic books (page footnotes, indented quotations) also get each block's indentation shape and their footnotes marked."""
    blocks, numbered_pages = [], set()
    for page_no, page_blocks in ocr_pages(book):
        shapes = text_shapes(page_blocks) if academic or inset_quotes else {}
        if page_no in facsimiles:
            numbered_pages.add(page_no)
            blocks += facsimile(page_no, page_blocks)
            continue
        for b in page_blocks:
            if b["label"] in PICTURE_LABELS:
                if is_illustration(b["bbox"], b["image_bbox"]):  # photos and drawings; drop caps, dividers and corner swirls are skipped
                    blocks.append({"page": page_no, "label": "Picture", "text": "", "bbox": b["bbox"], "image_bbox": b["image_bbox"]})
                elif is_full_page(b["bbox"], b["image_bbox"]):
                    # Kept aside: used only if this page turns out to be a Part opener (blank versos are full-page "pictures" too)
                    blocks.append({"page": page_no, "label": "FullPage", "text": "", "bbox": b["bbox"], "image_bbox": b["image_bbox"]})
                continue
            if not (b["html"] or "").strip() or in_side_edge(b["bbox"], b["image_bbox"]):
                continue
            text = clean_inline(b["html"])
            # A running head the OCR tagged as a heading ("Chapter Three : Bhaktivedānta!") — only at a page's very top,
            # so the same words used as a label lower down (captions grouped by chapter) stay
            if (b["label"] == "SectionHeader" and b["bbox"][1] < 0.08 * b["image_bbox"][3]
                    and any(re.search(r, plain(text)) for r in running_heads)):
                continue
            if academic and b["label"] == "SectionHeader":
                text = re.sub(r"\s*\n\s*", " ", re.sub(r"-\n", "-", text))  # headings wrapped mid-phrase ("SANNYASA-⏎ASHRAMA") read as one line
            if not plain(text):
                continue
            if b["label"] in MARGIN_LABELS:
                if PAGE_NUMBER_RE.match(plain(text)):
                    numbered_pages.add(page_no)
                if not SCENE_BREAK_RE.match(plain(text)):  # a "* * * *" scene break at a page top is sometimes labelled a header
                    continue  # running headers and page numbers are regenerated by the typesetter
            blocks.append({"page": page_no, "label": b["label"], "text": text, "html": b["html"] if b["label"] in ("TableOfContents", "Table") else "",
                           "shape": shapes.get(b["reading_order"], ""), "rule": b["html"].lstrip().startswith("<hr")})
    if academic:
        mark_footnotes(blocks)
    return blocks, numbered_pages


def mark_footnotes(blocks) -> None:
    """Footnotes run in one numbered sequence through an academic book, so a Text or list block opening with the next number
    is a footnote the OCR mislabelled, and a 'hanging' block is the rest of a note carried over from the previous page."""
    note_no = 0
    for i, b in enumerate(blocks):
        n = note_number(b["text"])
        mislabelled = b["label"] in ("Text", "ListGroup") and n is not None and note_no < n <= note_no + NOTE_WINDOW
        # A page shifted on the scanner makes a paragraph continued from the previous page 'hang' too — a carried-over
        # note is labelled a footnote, or is followed on its page by footnotes only
        # (and has body text above it — an indented paragraph straight under a heading is the page's own text)
        rest = [r for r in blocks[i + 1:] if r["page"] == b["page"] and r["label"] not in ("Picture", "FullPage")]
        body_above = any(r["page"] == b["page"] and r["label"] in ("Text", "ListGroup") for r in blocks[max(0, i - 30):i])
        carried = b.get("shape") == "hanging" and (b["label"] == "Footnote" or (body_above and rest and all(
            r["label"] == "Footnote" or note_number(r["text"]) is not None for r in rest)))
        below_rule = b["label"] == "Text" and b.get("rule")  # the footnote separator line is drawn above this block
        if b["label"] == "Footnote" or mislabelled or carried or below_rule:
            b["footnote"] = True
            numbers = [note_number(ln) for ln in b["text"].split("\n")]
            note_no = max([note_no] + [x for x in numbers if x is not None and x <= note_no + NOTE_WINDOW])


def in_side_edge(bbox, image_bbox) -> bool:
    """Text lying entirely in the outer 8% at a page's left or right edge is scanner debris (e.g. a strip of another sheet
    caught along the edge of a blank page) — the book's own text never sits there."""
    return bbox[2] < 0.08 * image_bbox[2] or bbox[0] > 0.92 * image_bbox[2]


def is_full_page(bbox, image_bbox) -> bool:
    x0, y0, x1, y1 = bbox
    return (x1 - x0) * (y1 - y0) >= 0.8 * image_bbox[2] * image_bbox[3]


def picture_share(b: dict) -> float:
    """Share of the page a picture block covers."""
    x0, y0, x1, y1 = b["bbox"]
    return (x1 - x0) * (y1 - y0) / (b["image_bbox"][2] * b["image_bbox"][3])


def toc_entry(raw_title: str, page: str) -> dict:
    """One contents entry. 'match' is what the body heading should look like; 'title' (if set) is the nicer display spelling."""
    raw_title = re.sub(r"^\d+\.\s*", "", raw_title.strip())  # "1. Preface" → "Preface"
    if m := TOC_PART_RE.match(raw_title):  # "Part 1: Aspects of Sādhana" — labelled "Part One" unless its page prints its own label
        words = "One Two Three Four Five Six Seven Eight Nine Ten".split()
        label = f"Part {words[int(m.group(1)) - 1]}" if m.group(1).isdigit() and 0 < int(m.group(1)) <= 10 else ""
        return {"match": m.group(2), "title": m.group(2), "subtitle": label, "page": page, "hint": "part"}
    if m := TOC_BOOK_RE.match(raw_title):  # "BOOK TWO: FINDING KRISHNA IN LONDON 1968–70": a Part, titled from its own page
        return {"match": m.group(2), "title": None, "subtitle": m.group(1).title(), "page": page, "hint": "part"}
    if m := TOC_NUMBERED_RE.match(raw_title):  # "1 Children of the Fifties"
        return {"match": m.group(2), "title": m.group(2), "page": page, "hint": "chapter"}
    if m := TOC_CHAPTER_RE.match(raw_title):
        return {"match": f"Chapter {m.group(1)} {m.group(2)}", "title": m.group(2), "page": page, "hint": "chapter"}
    if TOC_SUBSECTION_RE.match(raw_title):
        return None  # sub-sections become subheadings inside their chapter, not sections of their own
    if m := TOC_ROMAN_RE.match(raw_title):
        return {"match": raw_title, "title": m.group(2).strip(), "page": page, "hint": "chapter", "numeral": m.group(1)}
    return {"match": raw_title, "title": None, "page": page, "hint": None}


LEADER_RE = re.compile(r"^(.*?)\s*\.{3,}\s*(\d{1,3}|[ivxlc]+)?\s*$", re.I)  # "Setting the Scene ..... 75"


def reorder_pages(blocks, skip: set, moves: list) -> list:
    """Repair a scan's page order, checked against its printed page numbers: duplicate scans are left out, and each
    [page, after] move puts a scan page right after another (swapped pairs; pages re-scanned and added at the end)."""
    if not skip and not moves:
        return blocks
    order = list(dict.fromkeys(b["page"] for b in blocks if b["page"] not in skip))
    for page, after in moves:
        order.remove(page)
        order.insert(order.index(after) + 1, page)
    rank = {p: i for i, p in enumerate(order)}
    return sorted((b for b in blocks if b["page"] in rank), key=lambda b: rank[b["page"]])  # stable: keeps each page's own order


def restore_r_dot(blocks) -> list[str]:
    """Some scans' fonts set the dot under ṛ so low that the OCR drops it ("Krṣṇa" for the printed Kṛṣṇa, checked against
    the scan). The book's own correctly read words are the vocabulary: a word whose r → ṛ spelling the OCR also read
    elsewhere is corrected. English words have no such twin, so they never change."""
    words = Counter(w for b in blocks for w in re.findall(r"\w+", plain(b["text"])))
    vocab = {w for w, n in words.items() if ("ṛ" in w or "Ṛ" in w) and n >= 2}
    fixes = {}
    for w in words:
        for i, ch in enumerate(w):
            if ch in "rR" and (cand := w[:i] + ("ṛ" if ch == "r" else "Ṛ") + w[i + 1:]) in vocab:
                fixes[w] = cand
                break
    changed = Counter()
    for b in blocks:
        def swap(m):
            if m.group(0) in fixes:
                changed[m.group(0)] += 1
                return fixes[m.group(0)]
            return m.group(0)
        b["text"] = re.sub(r"\w+", swap, b["text"])
        if b.get("html"):
            b["html"] = re.sub(r"\w+", lambda m: fixes.get(m.group(0), m.group(0)), b["html"])
    return [f"      ṛ restored: {sum(changed.values())} words — " + ", ".join(f"{w}→{fixes[w]} ×{n}" for w, n in changed.most_common(12))]


SMALL_WORDS = {"a", "an", "and", "the", "of", "in", "on", "to", "for", "at", "by", "with", "or", "as", "from", "is"}


def smart_title(text: str) -> str:
    """'FIRST SIGHT—CONCERNED WITH LOVE' → 'First Sight—Concerned with Love'; 'APPENDIX II' → 'Appendix II' (numerals kept)."""
    out = []
    for i, word in enumerate(re.split(r"(\s+|—|-)", text)):
        if re.fullmatch(r"[IVXL]+", word) and len(word) > 1 or word in ("I", "II") or ("/" in word and len(word) <= 4):  # "B/W"
            out.append(word)
        elif word.lower() in SMALL_WORDS and i > 0 and out and out[-1] not in ("—",):
            out.append(word.lower())
        else:
            out.append(word[:1].upper() + word[1:].lower())
    return "".join(out)


def contents_rows(blocks, pages: list, plain_lines: bool = False) -> list[tuple[str, list[str]]]:
    """The contents pages as rows of (first cell's HTML, cells), whatever their shape: table rows; paragraph entries
    ("<b>Title</b> ..... 139<br/>Śrīmad-Bhāgavatam 10.9.7–10", one row per line); and "CHAPTER FOUR" printed as a heading.
    Dotted leaders are dropped from titles."""
    rows = []
    for b in blocks:
        if b["page"] not in pages:
            continue
        # A contents page printed as plain lines ("Foreword by Radhanath Swami ix", "Chapter 1: Arriving on the Scene 1")
        if plain_lines and b["label"] in ("Text", "SectionHeader", "TableOfContents") and plain(b["text"]).strip().lower() != "contents":
            for line in (ln.strip(" —–-") for ln in plain(b["text"]).split("\n") if ln.strip(" —–-")):
                # "Title 17" — or the page first, "17 WITHOUT FEAR" (Without Fear)
                m = re.match(r"^(.*?\S)\s+(\d{1,3}|[ivxlc]+)$", line)
                first = re.match(r"^(\d{1,3}|[ivxlc]+)\s+(\S.*)$", line)
                rows.append((line, [m.group(1), m.group(2)] if m else [first.group(2), first.group(1)] if first else [line]))
            continue
        if b["label"] == "SectionHeader" and any(r.match(plain(b["text"])) for r in (TOC_LABEL_RE, TOC_BOOK_RE, TOC_PART_RE)):
            rows.append((b["text"], [plain(b["text"])]))
        if b["label"] != "TableOfContents":
            continue
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", b["html"], re.S | re.I)
        if trs:
            for row in trs:
                raw = [c for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I) if plain(clean_inline(c)).strip()]
                rows.append((raw[0] if raw else "", [re.sub(r"\s+", " ", plain(clean_inline(c))).strip() for c in raw]))
        else:
            for line in (ln for ln in plain(clean_inline(b["html"])).split("\n") if ln.strip()):
                m = LEADER_RE.match(line)
                rows.append((line, [m.group(1), m.group(2)] if m and m.group(2) else [line.strip()]))
    for i, (raw, cells) in enumerate(rows):
        if cells and (m := LEADER_RE.match(cells[0])):
            cells[0] = m.group(1)
    return rows


def read_contents(blocks, keep: set = frozenset(), pages: list = None, subentries: bool = False) -> list[dict]:
    """The book's contents list. Table style (Tava Kathāmṛta): title and page on alternate lines of TableOfContents blocks.
    Line style (Vraja-līlā): the longest run of consecutive 'Title – page' lines.
    'keep': titles that are sections even where they look like a chapter's sub-entries (Epilogue, Glossary…)."""
    table, label_page, pending_label, pending_title, in_chapter = [], "", "", "", False
    # The contents pages are the first run of pages holding contents tables; an index at the back looks the same
    toc_pages = sorted({b["page"] for b in blocks if b["label"] == "TableOfContents"})
    run = [p for i, p in enumerate(toc_pages) if p - toc_pages[0] <= i + 1]
    run = pages or run  # contents pages named in book_meta.json (a contents set as plain lines)
    # One row per entry keeps a title that wraps over two lines together
    for raw0, cells in contents_rows(blocks, run, plain_lines=bool(pages)):
        raw = [raw0] if raw0 else []
        # "Chapter 1: On to India" with "August–October 1970" on the cell's second line: the date is the chapter's subtitle
        date = ""
        if raw and len(lines := [l for l in plain(clean_inline(raw[0])).split("\n") if l.strip()]) > 1 and DATE_RE.search(" ".join(lines[1:])):
            cells[0], date = lines[0].strip(), " ".join(l.strip() for l in lines[1:])
        if len(cells) >= 3 and re.fullmatch(r"\d{1,2}\.?", cells[0]):
            cells = [f"{cells[0].rstrip('.')} {cells[1]}"] + cells[2:]  # "9 | Youthful Temple | 197" → "9 Youthful Temple | 197"
        if not cells or PAGE_NUMBER_RE.match(cells[0]):
            continue
        page = cells[-1] if len(cells) > 1 and PAGE_NUMBER_RE.match(cells[-1]) else ""
        # "Chapter One | 19" with "Introduction and Foundational Elements" on the row below: one entry, matched by its title
        if not page and table and table[-1].get("label"):
            label = table.pop()["label"]
            chapter = label.lower().startswith("chapter")
            table.append({"match": cells[0], "title": cells[0] if chapter else label, "subtitle": "" if chapter else cells[0],
                          "page": label_page, "hint": "chapter" if chapter else "back"})
            continue
        # "Chapter 1" with no page, then the chapter's first place "Stockholm, December 1974 | 11" (its title), then more
        # places "London, Paris | 16" — those are headings inside the chapter, not sections (A Spiritual Journey)
        if not page and TOC_LABEL_RE.match(cells[0]):
            pending_label, pending_title, in_chapter = cells[0], "", False
            continue
        if pending_label and not page:
            pending_title = (pending_title + " " + cells[0]).strip()  # a title wrapped over two rows
            continue
        if pending_label and page:
            name = (pending_title + " " + cells[0]).strip()
            if pending_label.lower().startswith("chapter"):
                table.append({"match": name, "title": name, "page": page.strip(), "hint": "chapter"})
            else:  # "APPENDIX 2" + its title: titled by the label, the title as subtitle (as in Sannyāsīs)
                table.append({"match": name, "title": smart_title(pending_label), "subtitle": name, "page": page.strip(), "hint": "back"})
            pending_label, pending_title, in_chapter = "", "", True
            continue
        # A row without a page right after a chapter is its scripture reference ("Śrīmad-Bhāgavatam 10.9.1-3")
        if in_chapter and not page and table and not table[-1].get("subtitle") and (not pages or re.search(r"\d", cells[0])):
            table[-1]["subtitle"] = cells[0]
            continue
        if pages and not page and not TOC_LABEL_RE.match(cells[0]):
            continue  # plain-text contents: a line without a page is a running head or a stray, not an entry
        if in_chapter and page and cells[0] not in keep and not TOC_CHAPTER_RE.match(cells[0]):
            continue
        if page and TOC_LABEL_RE.match(cells[0]):
            table.append({"match": cells[0], "title": None, "page": page.strip(), "hint": None, "label": cells[0]})
            label_page = page.strip()
            continue
        entry = toc_entry(cells[0], page.strip())
        if entry:
            if date:
                entry["subtitle"] = date
            table.append(entry)
            # "chapter_subentries": the lines listed under a chapter ("Battling Nair 106") are its subheadings, not sections
            if subentries and entry["hint"] == "chapter":
                in_chapter = True
    # A contents printed in capitals ("FIRST SIGHT—CONCERNED WITH LOVE") reads better in title case
    for e in table:
        for key in ("title", "subtitle"):
            if e.get(key) and e[key].isupper():
                e[key] = smart_title(e[key])
    if any(e.get("numeral") for e in table):
        # Roman-numbered book: after the first chapter only numbered entries are chapters — unnumbered rows are
        # sub-section lines that lost their number ("Lāja-homa and Āśmākramaṇa, Sapta-padī…")
        first = next(i for i, e in enumerate(table) if e.get("numeral"))
        table = table[:first] + [e for e in table[first:] if e.get("numeral")]
    if len(table) >= 5:
        return table
    best, run = [], []
    for b in blocks:
        m = TOC_LINE_RE.match(plain(b["text"]))
        if m and "\n" not in b["text"]:
            entry = toc_entry(m.group(1), m.group(2))
            if entry:
                run.append(entry)
        else:
            best, run = max(best, run, key=len), []
    return max(best, run, key=len)


def ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, ascii_key(a), ascii_key(b)).ratio()


def part_of(piece: str, title: str) -> bool:
    """A heading piece that appears, letter for letter in order, within a title — allowing a spelling variant ("ashrama" / "asrama")."""
    key = ascii_key(piece)
    blocks = difflib.SequenceMatcher(None, key, ascii_key(title), autojunk=False).get_matching_blocks()
    return len(key) >= 4 and sum(b.size for b in blocks) >= 0.9 * len(key)


def title_ratio(heading: str, listed: str) -> float:
    """How well a page heading matches a contents title. Contents titles often say more than the heading:
    a bracketed description ('Introduction (including the list…)'), a description after a colon
    ('IX. Jāta-karma: Also Known as Medhā-jana…' vs 'IX. Jāta-Karma:'), or a wrapped second line."""
    variants = [listed, re.sub(r"\s*\(.*\)\s*$", "", listed), listed.split(":")[0], re.sub(r"^chapter\s+", "", listed, flags=re.I),
                re.sub(r"^appendix\s+\w+\s*:\s*", "", listed, flags=re.I)]  # "Appendix 1: Use of the Word Adhikārī" → its page heading
    # the heading may carry its label where the contents row doesn't — even glued on by the OCR ("PART ONEASPECTS OF…")
    headings = {heading, HEADING_PREFIX_RE.sub("", heading), NUMBERED_LABEL_RE.sub("", heading)}
    best = max(ratio(h, v) for h in headings for v in variants)
    # A numbered heading that is the start of the numbered contents title ('XVIII. Upanayana (Dīkṣā)') is the same section
    h, l = ascii_key(heading), ascii_key(listed)
    numeral = re.match(r"^([IVXL]+)\.", heading.strip())
    if numeral and listed.startswith(numeral.group(1) + ".") and len(h) >= 10 and l.startswith(h):
        best = 1.0
    return best


def classify(text: str, label: str, prev: dict | None) -> list[dict]:
    """Turn one OCR block into typed blocks. A verse with its source on the last line ("…\n[CC Ādi-līlā 1.5]") becomes quote + cite."""
    p = plain(text)
    lines = [ln for ln in text.split("\n") if plain(ln)]
    if SCENE_BREAK_RE.match(p):
        return [{"type": "break"}]
    # Source on its own last line, in square brackets
    if len(lines) > 1 and re.fullmatch(r"\[.*\]", plain(lines[-1])):
        return classify("\n".join(lines[:-1]), label, prev) + [{"type": "cite", "text": plain(lines[-1])}]
    if re.fullmatch(r"\[.*\]", p):
        return [{"type": "cite", "text": p}]
    if p.startswith(("—", "–")) and len(p) < 80:
        return [{"type": "sign", "text": p.lstrip("—– ").strip()}]
    if prev and prev["type"] == "sign" and len(p) < 200 and "\n" not in p:
        return [{"type": "sign-detail", "text": p}]  # place/date line under a signature
    # Verses are printed in italics, one line per pāda
    if is_all_italic(text) and len(lines) >= 2:
        return [{"type": "quote", "lines": [plain(ln) for ln in lines]}]
    # A short italic line right after a quote or an epigraph is its source ("Śrī Vṛndāvana-mahimāmṛta, Śataka 1.17, …")
    if is_all_italic(text) and len(lines) == 1 and len(p) < 160 and prev and prev["type"] in ("quote", "p") and prev.get("first"):
        return [{"type": "cite", "text": p}]
    if is_all_italic(text) and len(lines) == 1 and len(p) < 160 and prev and prev["type"] == "quote":
        return [{"type": "cite", "text": p}]
    numbered = re.match(r"^[IVXL1]+(\.\d+)+\.?\s", p)  # "II.2.3.1. Artha-śāstras" — section headings can be long
    if label == "SectionHeader" and is_all_italic(text) and len(lines) >= 2:  # a verse the OCR tagged as a heading
        return [{"type": "quote", "lines": [plain(ln) for ln in lines]}]
    if label == "SectionHeader" and (len(p) < 80 or (numbered and len(p) < 160)) and not p.endswith("."):
        return [{"type": "h", "text": p}]
    return [{"type": "p", "text": join_lines(text)}]


def unfinished(paragraph: dict) -> bool:
    """A paragraph a page break (or a picture) cut off: no closing punctuation, and not an all-capitals byline or label
    ("BY SRILA BHAKTISIDDHANTA SARASVATI PRABHUPADA"), which ends without a full stop."""
    return not ends_sentence(paragraph["text"]) and not plain(paragraph["text"]).isupper()


def glue(paragraph: dict, text: str) -> None:
    paragraph["text"] = paragraph["text"].rstrip("-") + ("" if paragraph["text"].endswith("-") else " ") + text


def add_block(section: Section, new: dict) -> None:
    last = section.blocks[-1] if section.blocks else None
    # A paragraph (or quotation) cut by a page break doesn't end in sentence punctuation — glue the next piece onto it
    # (a quotation only across a page: on one page, two quoted blocks are separate paragraphs as printed)
    if new["type"] in ("p", "blockquote") and last and last["type"] == new["type"] and unfinished(last) and last.get("page") != new.get("page", -1):
        glue(last, new["text"])
        return
    # A photo in the middle of a paragraph: keep the paragraph whole and let the photo follow it
    before = section.blocks[-2] if len(section.blocks) > 1 else None
    if new["type"] == "p" and last and last["type"] == "figure" and before and before["type"] == "p" and unfinished(before):
        glue(before, new["text"])
        return
    # A paragraph starting in lowercase continues an earlier one — even after a closing quote mark ("…tho!" / "blends with…"),
    # or with a picture or verse placed in between by the page break; glue it to the nearest paragraph within 3 blocks
    if new["type"] == "p" and plain(new["text"])[:1].islower():
        for prev in reversed(section.blocks[-3:]):
            if prev["type"] in ("p", "entry"):  # a list item can continue onto the next page too
                # …but never onto a paragraph that truly ended with . ! or ? — a quote mark or comma may close a speech mid-sentence
                if not plain(prev["text"]).rstrip().endswith((".", "!", "?")):
                    glue(prev, new["text"])
                    return
                break
            if prev["type"] not in ("figure", "quote", "cite", "break"):
                break
    # An epigraph is a paragraph immediately followed by its source at the very start of a section
    if new["type"] == "cite" and last and last["type"] == "p" and len(section.blocks) == 1:
        last["type"] = "epigraph"
    section.blocks.append(new)


def section_kind(entry: dict, unnumbered: set, dropped: set, front_prefixes: tuple = ()) -> str:
    title = entry["match"]
    if entry["hint"] in ("part", "back"):
        return entry["hint"]
    if re.match(r"appendi(x|ces)\b", title, re.I):  # "Appendix 1: Use of the Word Adhikārī"
        return "back"
    if title in dropped:
        return "drop"
    first_word = re.sub(r"\W", "", title.split()[0].lower()) if title.split() else ""
    if entry["hint"] != "chapter" and (re.fullmatch(r"[ivxlc]+", entry["page"], re.I) or first_word in FRONT_TITLES or title.startswith(front_prefixes)):
        return "front"
    return "back" if title in unnumbered else "chapter"


def add_note_lines(section: Section, text: str) -> None:
    """Endnotes: a line starting "12. " opens a new note; anything else continues the previous one (notes run across pages)."""
    for line in (ln for ln in text.split("\n") if plain(ln)):
        last = section.blocks[-1] if section.blocks else None
        if NOTE_START_RE.match(plain(line)) or not last or last["type"] != "note":
            section.blocks.append({"type": "note", "text": line})
        else:
            glue(last, line)


def note_number(text: str) -> int | None:
    m = NOTE_NUMBER_RE.match(text)
    return int(m.group(1) or m.group(2)) if m else None


def add_footnotes(section: Section, blk: dict) -> None:
    """Page-bottom footnotes, moved to the section's Notes (which also lets the paragraph they interrupted be glued back
    together). A piece opening with a note number starts a new note ("15 It is…" → "15. It is…"); a 'hanging' block or a
    later list line without one continues the note before it."""
    # A list holds several notes, one or more lines each; any other block is one piece
    pieces = [ln for ln in blk["text"].split("\n") if plain(ln)] if blk["label"] == "ListGroup" else [blk["text"]]
    for i, piece in enumerate(pieces):
        n = note_number(piece)
        continues = n is None and section.footnotes and (blk["shape"] == "hanging" or i > 0 or plain(piece)[:1].islower())
        if continues:
            section.footnotes[-1] = section.footnotes[-1].rstrip("-") + ("" if section.footnotes[-1].endswith("-") else " ") + join_lines(piece)
            continue
        if n is not None:
            piece = NOTE_NUMBER_RE.sub(f"{n}. ", piece, count=1)
        section.footnotes.append(piece)


def assemble(blocks, contents, unnumbered: set, dropped: set, front_prefixes: tuple = (), academic: bool = False, italic_prose: bool = False,
             inserted: list = None, opts: dict = None):
    opts = opts or {}
    sections, skipped_pages, k, skip, in_notes, part_label, full_pages, entry_page, waiting = [], set(), 0, 0, False, "", {}, 0, []
    matched = set()
    extra = sorted(inserted or [], key=lambda x: x["page"])
    for i, blk in enumerate(blocks):
        if extra and blk["page"] >= extra[0]["page"]:
            sections.append(Section(kind=extra[0].get("kind", "back"), title=extra[0]["title"], subtitle=extra[0].get("subtitle", ""), start_page=blk["page"]))
            extra = extra[1:]
        if skip:
            skip -= 1
            continue
        if blk["label"] == "FullPage":
            full_pages[blk["page"]] = {"page": blk["page"], "bbox": blk["bbox"], "image_bbox": blk["image_bbox"], "caption": ""}
            if sections and sections[-1].kind == "part" and sections[-1].start_page == blk["page"]:
                sections[-1].cover = full_pages[blk["page"]]
            continue
        if blk["label"] == "Picture":
            figure = {"type": "figure", "page": blk["page"], "bbox": blk["bbox"], "image_bbox": blk["image_bbox"], "caption": ""}
            if sections:
                sections[-1].blocks.append(figure)
            else:
                waiting.append(figure)  # may sit above the first section's heading (a dedication photo)
            continue
        # A photo section's captions sometimes come back as plain text under the photo
        if (blk["label"] == "Text" and sections and sections[-1].title in opts.get("gallery", ()) and sections[-1].blocks
                and sections[-1].blocks[-1]["type"] == "figure" and not sections[-1].blocks[-1]["caption"] and len(plain(blk["text"])) < 400):
            sections[-1].blocks[-1]["caption"] = join_lines(plain(blk["text"]))
            continue
        # Tables the OCR read as tables (a list of initiated disciples, a timeline) — opt-in, as other books' tables were checked as text
        if blk["label"] == "Table" and opts.get("ocr_tables") and sections:
            rows = [[re.sub(r"\s+", " ", clean_inline(c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
                    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", blk["html"], re.S | re.I)]
            rows = [r for r in rows if any(r)]
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                last = sections[-1].blocks[-1] if sections[-1].blocks else None
                if last and last["type"] == "table" and len(last["rows"][0]) == width:
                    last["rows"] += rows[1:] if rows[0] == last["rows"][0] else rows  # one table printed over several pages
                else:
                    sections[-1].blocks.append({"type": "table", "rows": rows})
            continue
        if blk["label"] == "Caption":
            # Belongs to the most recent figure of this section that has no caption yet
            figure = next((b for b in reversed(sections[-1].blocks) if b["type"] == "figure"), None) if sections else None
            if figure and not figure["caption"]:
                figure["caption"] = join_lines(plain(blk["text"]))
            continue
        p = plain(blk["text"])
        # "PART ONE" can be read before or after its part's title — hold it for the part that is due next
        if PART_LABEL_RE.match(p) and k < len(contents) and contents[k]["hint"] == "part":
            part_label = p.title()
            continue
        # The contents page's own lines ("Foreword – x") would otherwise match the very titles they list
        heading_like = (blk["label"] == "SectionHeader" or (len(p) < 60 and "\n" not in p)) and not TOC_LINE_RE.match(p)

        # Next section from the contents list — its title may be split over two heading blocks ("Yavat" / "Part One",
        # "CHAPTER 1" / "THE GARDENER OF GOVARDHANA"). Look a few entries ahead in case one heading was garbled, and match
        # front sections (Foreword, Preface…) in any order — some books print them before the contents page.
        candidates = [j for j in range(k, min(k + LOOKAHEAD, len(contents))) if j not in matched]
        candidates += [j for j, e in enumerate(contents) if j not in matched and j not in candidates
                       and section_kind(e, unnumbered, dropped, front_prefixes) == "front"]
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        hit = None
        for j in candidates if heading_like else []:
            single = title_ratio(p, contents[j]["match"])
            both = title_ratio(p + " " + plain(nxt["text"]), contents[j]["match"]) if nxt is not None and nxt["label"] == "SectionHeader" else 0
            # Take the next heading too only if it improves the match — else it is the section's first subheading ("1965")
            two = both >= TITLE_MATCH_RATIO and both > single
            if two or single >= TITLE_MATCH_RATIO:
                hit = (j, two)
                break
        if hit:
            j, two = hit
            entry = contents[j]
            matched.add(j)
            kind = section_kind(entry, unnumbered, dropped, front_prefixes)
            # All-capital headings ("ABOUT THE AUTHOR") read better in the contents' own spelling ("About the Author")
            title = entry["title"] or re.sub(r"\s+", " ", entry["match"] if p.isupper() else p)
            subtitle = plain(nxt["text"]) if two and not entry["title"] else entry.get("subtitle", "")
            skip, in_notes = int(two), False
            if j >= k:
                k = j + 1
            after = blocks[i + 1 + skip] if i + 1 + skip < len(blocks) else None
            if kind == "part":
                if after and PART_LABEL_RE.match(plain(after["text"])):
                    part_label, skip = plain(after["text"]).title(), skip + 1  # "PART ONE" read after the part title
                subtitle, part_label = part_label or entry.get("subtitle", ""), ""
            sections.append(Section(kind=kind, title=title, subtitle=subtitle, start_page=blk["page"],
                                    cover=full_pages.get(blk["page"]) if kind == "part" else None, numeral=entry.get("numeral", "")))
            # A picture printed above the first section's heading on the same page opens that section
            sections[-1].blocks += [f for f in waiting if f["page"] == blk["page"]]
            waiting = []
            continue

        # The rest of a title printed over several heading blocks ("RESULTS OF SOCIAL RESEARCH:" / "PRIMARY FACTORS FOR…")
        if blk["label"] == "SectionHeader" and sections and not sections[-1].blocks and part_of(p, sections[-1].title + sections[-1].subtitle):
            continue
        # A "CHAPTER 1" label that didn't match together with the title below it: the title alone matches the contents
        # (a label-only row there) and the typesetter prints its own label
        if blk["label"] == "SectionHeader" and HEADING_LABEL_RE.match(p):
            continue
        if not sections:
            skipped_pages.add(blk["page"])  # endorsements, dedication, acknowledgements and contents before the first section
            continue
        current = sections[-1]
        if blk["label"] == "TableOfContents":
            continue  # the contents page itself — the typesetter builds its own
        if blk["label"] == "Footnote" or blk.get("footnote"):
            add_footnotes(current, blk)
            continue
        # Running headers sometimes come back as headings ("Yavat Part One" on every page) — drop repeats of the section title
        # (and a date line under the title that adds the year to the contents' subtitle: "OCTOBER 20–30, 1970")
        if heading_like and (max(ratio(p, current.title), ratio(p, f"{current.title} {current.subtitle}"),
                                 ratio(p, current.subtitle) if current.subtitle else 0) >= TITLE_MATCH_RATIO
                             or (current.subtitle and not current.blocks and ascii_key(p).startswith(ascii_key(current.subtitle)))):
            continue
        # "PART 2" printed under a chapter title that already ends in "2" ("Their Sweetness 2")
        if heading_like and not current.blocks and re.fullmatch(r"PART\s+\d+", p.strip(), re.I) and current.title.rstrip().endswith(p.split()[-1]):
            continue
        # Endnotes: everything after a chapter's "NOTES" heading
        if heading_like and p.strip().upper() == "NOTES":
            in_notes = True
            current.blocks.append({"type": "notes-h", "text": "Notes"})
            continue
        if in_notes:
            add_note_lines(current, blk["text"])
            continue
        # A list (e.g. the Bibliography) arrives as one block — each line is its own entry
        if blk["label"] == "ListGroup":
            for line in (ln for ln in blk["text"].split("\n") if plain(ln)):
                last = current.blocks[-1] if current.blocks else None
                # Academic bibliography: every entry has its year; a line without one is the wrapped end of the entry
                # before it ("Berkeley: University of California Press."), even when the OCR gave it a list dash
                if academic and last and last["type"] == "entry" and not re.search(r"\b(1[5-9]|20)\d\d\b", plain(line)):
                    glue(last, re.sub(r"^[-–•]\s*", "", line))
                    continue
                current.blocks.append({"type": "entry", "text": line})
            entry_page = blk["page"]
            continue
        # Academic books: a bibliography entry cut by a page break is finished by the next page's first text block — only
        # across a page (Saṁskāras' ritual lists mix bullets, mantras and translations too freely for this rule)
        last = current.blocks[-1] if current.blocks else None
        if academic and blk["label"] == "Text" and last and last["type"] == "entry" and blk["page"] > entry_page and not ends_sentence(last["text"]):
            glue(last, join_lines(blk["text"]))
            continue
        # Books without verses ("italic_prose"): an italic block is part of a letter or notice printed in italics, not a verse
        # or a source line — it flows as an italic quotation (its pieces across a page break glue back together)
        if italic_prose and blk["label"] == "Text" and is_all_italic(blk["text"]):
            add_block(current, {"type": "blockquote", "text": join_lines(blk["text"]), "page": blk["page"]})
            continue
        # A prose passage set in from both margins is a quotation (scripture, a scholar, an interview); italic verses stay quotes
        if blk["label"] == "Text" and blk["shape"] == "inset" and not is_all_italic(blk["text"]):
            add_block(current, {"type": "blockquote", "text": join_lines(blk["text"]), "page": blk["page"]})
            continue
        prev = current.blocks[-1] if current.blocks else None
        for new in classify(blk["text"], blk["label"], prev and {**prev, "first": len(current.blocks) == 1}):
            if new["type"] == "h" and current.numeral == "I":
                new["text"] = re.sub(r"^1\.(?=\d)", "I.", new["text"])  # OCR reads the Roman I of "I.2.4." as a digit
            add_block(current, new)
    for s in sections:
        if s.footnotes:
            if not any(b["type"] == "notes-h" for b in s.blocks):
                s.blocks.append({"type": "notes-h", "text": "Notes"})
            s.blocks += [{"type": "note", "text": f} for f in s.footnotes]
    missed = [contents[j]["match"] for j in range(len(contents)) if j not in matched]
    return sections, sorted(skipped_pages), missed


def build_report(sections, contents, skipped, blank, fixes, missed) -> list[str]:
    lines = [f"Skipped front pages: {skipped}", f"Contents check: {len(contents)} listed, {len(contents) - len(missed)} found"]
    lines += [f"Hand-checked text fixes applied ({len(fixes)}):"] + fixes if fixes else []
    lines += [f"      ! contents lists '{m}' but it was not found in the book" for m in missed]
    lines.append(f"Pages with no text (illustrations, or failed OCR — check): {blank}")
    lines.append("")
    for s in sections:
        counts = {t: sum(b["type"] == t for b in s.blocks) for t in ("p", "quote", "blockquote", "cite", "h", "note")}
        first = next((plain(b["text"]) for b in s.blocks if b["type"] == "p"), "")
        lines.append(f"p{s.start_page:>3}  [{s.kind}] {s.title} {s.subtitle}".rstrip() + f"  — {counts['p']} paragraphs, {counts['quote']} verse quotes, {counts['cite']} sources" + (f", {counts['blockquote']} quotations" if counts["blockquote"] else "") + f", {counts['note']} notes")
        # First words show at a glance if a decorated drop cap was lost ("efore" instead of "Before")
        lines.append(f"      starts: {first[:70]}")
        if first and not first[0].isupper() and not first[0] in "“\"'‘[(":
            lines.append("      ! first paragraph starts in lowercase — drop cap may be missing")
        lines += [f"      subheading: {b['text']}" for b in s.blocks if b["type"] == "h"]
        lines += [f"      figure p{b['page']}: {b['caption'] or '(no caption)'}" for b in s.blocks if b["type"] == "figure"]
    return lines


def main():
    book = (local_env.book_path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit(local_env.USAGE)).stem
    meta = json.loads(META_FILE.read_text(encoding="utf-8"))[book]
    blocks, numbered_pages = load_blocks(book, meta.get("academic", False), set(meta.get("facsimile_pages", [])), meta.get("inset_quotes", False),
                                         meta.get("running_heads", []))  # academic flag also goes to assemble()
    # Everything after the book's last content page is left out: an index not in the contents (its page numbers would be
    # wrong in our layout), endpapers and the back cover (Dāmodara-jananī: General Index from scan page 462)
    if last := meta.get("last_page"):
        blocks = [b for b in blocks if b["page"] <= last]
    blocks = reorder_pages(blocks, set(meta.get("skip_pages", [])), meta.get("page_moves", []))
    # ṛ first, so hand-checked fixes can be written in the book's correct spelling ("Kṛṣṇa")
    fixes = restore_r_dot(blocks) if meta.get("restore_r_dot") else []
    fixes += apply_text_fixes(blocks, meta.get("text_fixes", []))
    unnumbered, dropped = set(meta.get("unnumbered_sections", [])), set(meta.get("drop_sections", []))
    contents = read_contents(blocks, unnumbered | dropped, meta.get("contents_pages"), meta.get("chapter_subentries", False))
    # A contents page printed as plain lines would match its own titles: it is read for the contents only
    blocks = [b for b in blocks if b["page"] not in meta.get("contents_pages", [])]
    # Sections whose page heading differs from their contents title ("Srila Prabhupada" is headed "His Divine Grace A.C.
    # Bhaktivedanta Swami Prabhupada"): match the printed heading, keep the contents title for display
    for e in contents:
        if alias := meta.get("heading_aliases", {}).get(e["match"]):
            for group in (unnumbered, dropped):  # an unnumbered or dropped section stays so under its printed heading
                if e["match"] in group:
                    group.add(alias)
            e["title"], e["match"] = e["title"] or (smart_title(e["match"]) if e["match"].isupper() else e["match"]), alias
    front_prefixes = tuple(meta.get("front_sections", []))
    academic = meta.get("academic", False)
    italic_prose = meta.get("italic_prose", False)
    inserted = meta.get("insert_sections", [])
    opts = {"ocr_tables": meta.get("ocr_tables", False), "gallery": {x["title"] for x in inserted if x.get("gallery")}}
    sections, skipped, missed = assemble(blocks, contents, unnumbered, dropped, front_prefixes, academic, italic_prose, inserted, opts)

    # Back cover = ISBN page plus the unnumbered cover pages before it; without an ISBN on it, the scan's unnumbered last page
    # built around a big picture (Saṁskāras: a blurb panel that otherwise became the last chapter's "figure" and paragraph).
    # A closing page of plain text without a printed number (Vraja-līlā's "A Few Words…") stays.
    if sections:
        kept = drop_back_cover(blocks, sections[-1].start_page, numbered_pages)
        last_page = max(b["page"] for b in kept)
        if last_page not in numbered_pages and last_page > sections[-1].start_page and max(
                (picture_share(b) for b in kept if b["page"] == last_page and b["label"] in ("Picture", "FullPage")), default=0) >= 0.3:
            kept = [b for b in kept if b["page"] != last_page]
        if len(kept) < len(blocks):
            sections, skipped, missed = assemble(kept, contents, unnumbered, dropped, front_prefixes, academic, italic_prose, inserted, opts)
            blocks = kept

    # Contents-page typos and titles cut off by a wrapped contents row, corrected from the chapter's own heading
    for s in sections:
        if s.title in meta.get("title_fixes", {}):
            fixes.append(f"      title: '{s.title}' → '{meta['title_fixes'][s.title]}'")
            s.title = meta["title_fixes"][s.title]

    # Captions the OCR swallowed into the picture box (checked against the scan) come from book_meta.json
    for s in sections:
        for b in s.blocks:
            if b["type"] == "figure" and not b["caption"]:
                b["caption"] = meta.get("figure_captions", {}).get(str(b["page"]), "")

    # Indexes are matched (so the sections before them end in the right place) but left out: their page numbers would be wrong
    report_sections = sections
    sections = [s for s in sections if s.kind != "drop"]

    out_dir = local_env.stage_dir(book, "assembled")
    data = {"book": book, "layout": "prose", "sections": [asdict(s) for s in sections]}
    (out_dir / "book.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    report = build_report(report_sections, contents, skipped, blank_pages(blocks, sections[0].start_page if sections else 1), fixes, missed)
    (out_dir / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[:2]))
    print(f"Wrote {out_dir}")


if __name__ == "__main__":
    main()
