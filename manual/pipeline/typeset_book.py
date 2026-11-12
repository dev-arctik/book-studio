# manual/pipeline/typeset_book.py
# Stage 3 (final): typesets the assembled book (2-assembled/book.json) into one clean PDF of the whole book using Typst and Gentium Book Plus.
# Works for both layouts in book_meta.json — "verses" (Padyāvalī) and "prose" (Vraja-līlā) — by converting each into one shared template format.
# Usage: poetry run python manual/pipeline/typeset_book.py <path/to/book.pdf> --library <path/to/book-library>   → output/<book>/3-clean-pdf/<book>.pdf

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import difflib
import json
import re
import shutil
import sys
from pathlib import Path

import pypdfium2 as pdfium
import typst

from figures import book_cover, crop_figure, has_ink
from ocr_text import PICTURE_LABELS, ascii_key, clean_inline, ocr_pages
from pdf_text import page_blocks_text  # (reads no PDF library itself: scan books never load PyMuPDF)

TEMPLATE = local_env.PIPELINE_DIR / "book_template.typ"
META_FILE = local_env.META_FILE


# Characters Gentium lacks (they would print in a fallback font): the Devanagari danda that OCR returns at the end of a Sanskrit line, °F
GENTIUM_SAFE = str.maketrans({"।": "|", "॥": "||", "℉": "°F", "℃": "°C"})


def safe(text: str) -> str:
    return text.translate(GENTIUM_SAFE)


def to_segments(text: str) -> list[dict]:
    """'<i>Padyāvalī</i> was written' → [{t:'Padyāvalī', i:True, b:False}, {t:' was written', ...}] for the Typst template.
    Footnote markers and ordinals ('day.<sup>1</sup>', '10<sup>th</sup>') get sup:True."""
    text = safe(text)
    segs, italic, bold, sup = [], False, False, False
    for part in re.split(r"(</?(?:i|b|sup)>)", text):
        if part in ("<i>", "</i>"):
            italic = part == "<i>"
        elif part in ("<b>", "</b>"):
            bold = part == "<b>"
        elif part in ("<sup>", "</sup>"):
            sup = part == "<sup>"
        elif part:
            segs.append({"t": part, "i": italic, "b": bold, "sup": sup})
    return segs


def gloss_segments(text: str) -> list[dict]:
    """'namaḥ—obeisances; nalina—lotus flowers;' → Sanskrit word bold, meaning plain, so the eye can find each word quickly.
    OCR italics are dropped here: the printed gloss is roman, and bold alone marks the Sanskrit."""
    segs = []
    for item in re.split(r"(;\s*)", re.sub(r"</?[ib]>", "", text)):
        word, dash, meaning = item.partition("—")
        if dash and word.strip():
            # U+2060 word joiner glues the dash to the word, so a line never starts with "—meaning"
            segs += [{"t": word, "i": False, "b": True}, {"t": "⁠—" + meaning, "i": False, "b": False}]
        elif item:
            segs.append({"t": item, "i": False, "b": False})
    return segs


GLOSS_RE = re.compile(r"\s=\s")


def is_gloss(text: str) -> bool:
    """A word-for-word line: 'esthale = in this regard | ārao = another item | …' (three or more 'word = meaning' pairs)."""
    return len(GLOSS_RE.findall(text)) >= 3 and text.count(" | ") >= 2


def gloss_equals_segments(text: str) -> list[dict]:
    """'etad-dvārā = thus | ihāi = It | …' → the Sanskrit word before each ' = ' in bold, the meaning plain (printed word-for-word
    glosses mark the Sanskrit this way). OCR italics are dropped: bold alone marks the Sanskrit."""
    segs = []
    for item in re.split(r"(\s\|\s)", re.sub(r"</?[ib]>", "", text)):
        word, eq, meaning = item.partition(" = ")
        if eq and word.strip():
            segs += [{"t": word, "i": False, "b": True}, {"t": " = " + meaning, "i": False, "b": False}]
        elif item:
            segs.append({"t": item, "i": False, "b": False})
    return segs


# Labels that stand alone as headings ("SECTION 13", "TRANSLATION", "PURPORT"): centred, and not listed in the contents
LABEL_HEADING_RE = re.compile(r"^(section|translation|purport|texts?|synonyms|verses?|commentary|comments?|summary|part|chapter)\b[\s\d.:IVXLC-]*$", re.I)


def plain_text(segs: list[dict]) -> str:
    return re.sub(r"\s+", " ", "".join(s["t"] for s in segs)).strip()


def repeats_title(heading: str, title: str) -> bool:
    """A heading that is the section title again — same letters, a cut-off start of it, or a close misspelling."""
    return difflib.SequenceMatcher(None, heading, title).ratio() >= 0.85 or (len(heading) >= 12 and title.startswith(heading))


def restates(heading: str, title: str) -> bool:
    """A heading that only restates the chapter title ("The Story of Vatsasura" in the chapter Vatsasura) is no topic of its own."""
    h, t = ascii_key(heading), ascii_key(title)
    return (len(t) >= 6 and t in h and len(h) <= len(t) + 16) or (len(h) >= 8 and h in t)


def near_copy(a: str, b: str) -> bool:
    """Two heading keys that are one heading read twice: nearly the same letters and about the same length."""
    return min(len(a), len(b)) >= 0.7 * max(len(a), len(b)) and difflib.SequenceMatcher(None, a, b).ratio() >= 0.78


def mark_headings(front: list[dict], chapters: list[dict], topics: bool = True, merge_similar: bool = False) -> None:
    """Subheadings: label-like or all-capitals ones are centred; every other (unique) one is a subtopic that the contents lists under
    its chapter, with its page — so the contents shows the chapter names and the topics inside each chapter.
    topics=False ("no_topics" in book_meta.json): the headings are screenplay cues or labels, so none is listed in the contents."""
    from collections import Counter
    plain = lambda b: plain_text(b["segs"])  # noqa: E731
    counts = Counter(plain(b) for ch in chapters for b in ch["blocks"] if b["type"] == "h")
    for sec in front:
        for b in sec["blocks"]:
            if b["type"] == "h" and (LABEL_HEADING_RE.match(plain(b)) or (plain(b).isupper() and len(plain(b)) < 60)):
                b["centre"] = True
    for sec in front + chapters:  # a page's printed running title or banner repeats the section title as a heading in its first blocks: it is not a topic
        key = ascii_key(sec["title"])
        sec["blocks"] = [b for i, b in enumerate(sec["blocks"]) if not (i < 4 and b["type"] == "h" and key and repeats_title(ascii_key(plain(b)), key))
                         and not (i < 3 and b["type"] in ("h", "p") and re.fullmatch(r"Chapter [A-Za-z-]+", plain_text(b["segs"]) if b["type"] == "h" else re.sub(r"<[^>]+>", "", b.get("text", "")).strip()))]
    if merge_similar:  # "merge_similar_headings": the reader returned some headings twice, once misread ("SRI AITANYAMATHA" after "ŚRĪ CAITANYA MAṭHA"): the later near-copy goes
        for ch in chapters:
            seen, kept = [], []
            for b in ch["blocks"]:
                if b["type"] == "h":
                    key = ascii_key(plain(b)).replace("practicalguide", "")
                    if any(near_copy(key, old) for old in seen[-2:]):
                        continue
                    seen.append(key)
                kept.append(b)
            ch["blocks"] = kept
    for ci, ch in enumerate(chapters):
        k = 0
        blocks = ch["blocks"]
        caps = lambda j: 0 <= j < len(blocks) and blocks[j]["type"] == "h" and plain(blocks[j]).isupper()  # noqa: E731
        stacked = set()  # runs of 4+ capital headings in a row: a letterhead or address block, not a title with its author line
        j = 0
        while j < len(blocks):
            end = j
            while caps(end):
                end += 1
            if end - j >= 4:
                stacked.update(range(j, end))
            j = max(end, j + 1)
        for i, b in enumerate(blocks):
            if b["type"] != "h":
                continue
            text = plain(b)
            label = bool(LABEL_HEADING_RE.match(text))
            if label or (re.sub(r"\b\d+(st|nd|rd|th)\b", "", text).isupper() and len(text) < 60):  # (an ordinal is no lowercase: the screenplay cue "1st DEVOTEE")
                b["centre"] = True
            # (not a byline "By Deena Bandhu" / "2008 By …", a "-Name" credit, a bare year, or a chapter label repeated with its title "Chapter 5 OUTSIDE IN";
            # nor a line in a long stack of capitals — a letterhead or address block: "STATE OF FLORIDA / DEPARTMENT OF CORRECTIONS / TO: …")
            byline = bool(re.match(r"(\d{4}\s+)?(By|BY)\s+(?![A-Z][a-z]+ing\b)[A-Z]|-\s*[A-Z]|\d{4}$|(Chapter|Section) \d+\s+[A-Z]{2,}", text)) or i in stacked
            if topics and not label and not byline and 2 < len(text) <= 120 and not text.endswith((",", ";")) and not text.startswith(("“", "‘", "\"", "—", "–")) and not text[:1].islower() and not restates(text, ch["title"] + " " + (ch.get("subtitle") or "")) and not re.search(r"\(Popup|^\d+ \(|^(Chapter|Section|Part) [\w-]+$", text) and not (len(text) > 50 and ": " in text) and (counts[text] <= 2 if not text.isupper() else counts[text] == 1 and not re.search(r"\d", text)):
                b["id"] = f"sub-{ci}-{k}"  # the template labels it, so the contents can link to it and show its page
                k += 1


def split_signature(paragraphs: list[str]) -> tuple[list[str], str]:
    """An introduction often ends with the writer's name on its own line ("Pūrṇaprajña dāsa") — set it apart."""
    if paragraphs:
        last = re.sub(r"</?[ib]>", "", paragraphs[-1]).strip()
        if len(last) < 40 and not last.endswith((".", "!", "?", ":")):
            return paragraphs[:-1], last
    return paragraphs, ""


def typst_path(path: Path) -> str:
    """A file's path as Typst wants it: from the project root, with forward slashes even on Windows (Typst refuses backslashes)."""
    return "/" + path.relative_to(local_env.PROJECT_ROOT).as_posix()


class FigureCropper:
    """Crops each figure out of the scan into the temporary build folder and hands the template its path and shape."""

    def __init__(self, book: str, build_dir: Path):
        source = local_env.find_book(book)
        self.pdf = pdfium.PdfDocument(str(source)) if source.suffix.lower() == ".pdf" else None  # (a book read back from our own EPUB has no pages to crop)
        self.build_dir = build_dir
        self.count = 0

    def place(self, b: dict, figure=None) -> dict:
        self.count += 1
        if figure is None and b.get("file"):  # a picture that is already an image file (epub_to_book.py): used as it is
            from PIL import Image
            figure = Image.open(b["file"]).convert("RGB")
        figure = figure or crop_figure(self.pdf, b["page"], b["bbox"], b["image_bbox"], trim=not b.get("exact"))
        path = self.build_dir / f"figure-{self.count:03d}.jpg"
        figure.save(path, quality=90, optimize=True)
        return {"path": typst_path(path), "aspect": figure.height / figure.width, "wide": b.get("wide", False),
                "caption": to_segments(b["caption"]) if b["caption"] else []}


def typed_block(b: dict, indent: bool, figures: FigureCropper) -> dict:
    """Assembled block → template block; rich text becomes segments, verse lines stay as plain lines, figures get cropped."""
    out = {"type": b["type"], "indent": indent}
    if b["type"] == "quote":
        out["lines"] = [safe(l) for l in b["lines"]]
    elif b["type"] == "centred":
        out["lines"] = [to_segments(l) for l in b["lines"]]
    elif b["type"] == "table":
        out["rows"] = [[to_segments(c) for c in row] for row in b["rows"]]
    elif b["type"] == "figure":
        out.update(figures.place(b))
    elif b["type"] == "p" and is_gloss(b["text"]):
        out["segs"] = gloss_equals_segments(b["text"])
        out["indent"] = False
    elif b["type"] != "break":
        text = b["text"]
        if b["type"] == "h":
            text = re.sub(r"\s*[❖◆♦•✦]\s*", " ", text).strip()  # decorative marks round a printed heading (❖ Title ❖) are left out
        out["segs"] = to_segments(text)
    return out


def prose_blocks(blocks: list[dict], figures: FigureCropper) -> list[dict]:
    # Book convention: a paragraph is indented unless it opens the section or follows a quote/heading/figure
    return [typed_block(b, b["type"] == "p" and i > 0 and blocks[i - 1]["type"] == "p", figures) for i, b in enumerate(blocks)]


def from_verses_book(assembled: dict, figures: FigureCropper) -> tuple[list, list]:
    """Verse anthology (Padyāvalī): introduction as one front section, chapters carrying verses."""
    intro, signature = split_signature(assembled["intro"])
    front = []
    if intro:
        blocks = [{"type": "p", "indent": False, "segs": to_segments(p)} for p in intro]
        if signature:
            blocks.append({"type": "sign", "indent": False, "segs": to_segments(signature)})
        front.append({"title": "Introduction", "blocks": blocks})
    chapters = [{
        "number": i + 1,
        "title": ch["title"],
        "subtitle": ch["title_en"],
        "blocks": [{"type": "p", "indent": False, "segs": to_segments(p)} for p in ch["intro"]],
        "verses": [{
            "number": v["number"],
            "sanskrit": [safe(l) for l in v["sanskrit"]],
            "word_for_word": gloss_segments(v["word_for_word"]),
            "translations": [{"label": t["label"], "paragraphs": [to_segments(p) for p in t["paragraphs"]]} for t in v["translations"]],
            "poet": v["poet"],
            "notes": [to_segments(n) for n in v["notes"]],
        } for v in ch["verses"]],
    } for i, ch in enumerate(assembled["chapters"])]
    return front, chapters


def from_prose_book(assembled: dict, figures: FigureCropper) -> tuple[list, list]:
    """Prose book (Vraja-līlā): Foreword/Introduction as front sections, numbered chapters, unnumbered closing section."""
    front, chapters, n = [], [], 0
    for s in assembled["sections"]:
        if s["kind"] == "front":
            front.append({"title": s["title"], "blocks": prose_blocks(s["blocks"], figures)})
            continue
        n += s["kind"] == "chapter"
        # A title that already starts with its own number ("23: The Song of…") keeps it: a running count above it would disagree (Parts restart at 1)
        own_number = re.match(r"^(?:\d+\s*[:.]\s|Chapter [\w-]+\b)", s["title"], re.I)  # "23: …", or "Chapter One: …" (the title is the label)
        chapters.append({"number": n if s["kind"] == "chapter" and not own_number else None, "part": s["kind"] == "part", "title": s["title"], "subtitle": "" if s["subtitle"] and (ascii_key(s["title"]).startswith(ascii_key(s["subtitle"])[:30]) or re.fullmatch(r"Chapter [A-Za-z-]+", s["subtitle"].strip())) else s["subtitle"],
                         "cover": figures.place(s["cover"]) if s.get("cover") else None,
                         "blocks": prose_blocks(s["blocks"], figures), "verses": []})
    return front, chapters


def front_figures(book: str, first_page: int, figures: FigureCropper, skip: set) -> list[dict]:
    """Photos on the front pages before the book's text begins — a dedication portrait of Śrīla Prabhupāda, a Deity photo
    on an invitation page. The assemblers skip these pages' text, so the photos are shown on their own after the title page.
    Page 1 is the cover; faint ornaments and blank versos are left out, and line-art ornaments (which look like a pencil
    portrait to any pixel test) are listed by page in book_meta.json's "frontispiece_skip" after checking the scan."""
    placed = []
    for page_no, blocks in ocr_pages(book):
        if page_no >= first_page:
            break
        for b in blocks:
            x0, y0, x1, y1 = b["bbox"]
            big = (x1 - x0) * (y1 - y0) >= 0.05 * b["image_bbox"][2] * b["image_bbox"][3]  # not a drop cap or divider
            if page_no > 1 and page_no not in skip and b["label"] in PICTURE_LABELS and big:
                figure = crop_figure(figures.pdf, page_no, b["bbox"], b["image_bbox"])
                if has_ink(figure):
                    placed.append(figures.place({"caption": ""}, figure))
                    print(f"Frontispiece: picture from page {page_no} (check it against the scan)")
    return placed


def first_text_page(book: str, assembled: dict) -> int:
    """Where the book proper begins: its contents page or its first section, whichever comes first (Without Fear's
    dedication, with its photos, comes before the contents)."""
    sections = assembled.get("sections") or assembled.get("chapters")
    first = sections[0]["start_page"]
    for page_no, blocks in ocr_pages(book):
        if any(b["label"] == "TableOfContents" for b in blocks):
            return min(page_no, first)
    return first


# Signs of a copyright page: two or more are needed — one "published by" in a preface is not a copyright page
COPYRIGHT_RE = re.compile(r"©|copyright|all rights reserved|\bisbn\b|printed in|published by", re.I)


def copyright_page(book: str, first_page: int, strip: list = (), only_page: int | None = None) -> list[list[list[dict]]] | None:
    """The book's own copyright page (©, ISBN, publisher) from its front pages, as blocks of lines, set faithfully as printed.
    Only used when the book's settings say "keep_copyright" — the approved design leaves it out. Scans read the OCR text;
    digital PDFs (no OCR pages) read the PDF's own text."""
    pages = [(n, [clean_inline(b["html"]) for b in blocks if b["label"] not in PICTURE_LABELS and b.get("html")])
             for n, blocks in ocr_pages(book) if n < first_page or n == only_page]
    if not pages:
        import pymupdf
        with pymupdf.open(local_env.find_book(book)) as pdf:
            # decoded like the book's text; the page named in "copyright_page" counts too, even after the first section (Chaurasi-kosa's, behind its dedication)
            pages = [(n + 1, page_blocks_text(pdf[n])) for n in range(len(pdf)) if n + 1 < first_page or n + 1 == only_page]
    best, best_hits = None, 1
    for n, texts in pages:
        if only_page and n != only_page:  # book_meta.json "copyright_page": the page checked by hand (the cover also says "Copyrighted material")
            continue
        hits = len(COPYRIGHT_RE.findall(" ".join(texts)))
        if hits > best_hits:
            best, best_hits = (n, texts), hits
    if best is None:
        print("Copyright page: none found in the front pages — the PDF goes without one")
        return None
    print(f"Copyright page: page {best[0]} (check it against the scan)")
    def stripped(text: str) -> str:  # the book's "strip_text" patterns (a scanner's watermark) leave the copyright page too
        for rx in strip:
            text = re.sub(rx, "", text)
        return text
    return [[to_segments(line) for line in stripped(text).split("\n") if line.strip()] for text in best[1]]


def build_typst_data(book: str, build_dir: Path) -> dict:
    assembled = json.loads((local_env.stage_dir(book, "assembled") / "book.json").read_text(encoding="utf-8"))
    meta = json.loads(META_FILE.read_text(encoding="utf-8"))[book]
    figures = FigureCropper(book, build_dir)
    # The original front cover opens the PDF, on a page shaped like the cover itself (no cropping, no white bands)
    cover = book_cover(local_env.find_book(book), meta)
    cover_path = build_dir / "cover.jpg"
    cover.save(cover_path, quality=85, optimize=True)
    cover_data = {"path": typst_path(cover_path), "aspect": cover.height / cover.width}
    frontispiece = front_figures(book, meta.get("frontispiece_until") or first_text_page(book, assembled), figures, set(meta.get("frontispiece_skip", [])))  # "frontispiece_until": a page whose picture belongs before the contents although its text is a section (a dedication)
    front, chapters = (from_prose_book if meta["layout"] == "prose" else from_verses_book)(assembled, figures)
    mark_headings(front, chapters, not meta.get("no_topics", False), meta.get("merge_similar_headings", False))
    copyright_lines = copyright_page(book, first_text_page(book, assembled), meta.get("strip_text", []), meta.get("copyright_page")) if meta.get("keep_copyright") else None
    return {"meta": meta, "layout": meta["layout"], "cover": cover_data, "copyright": copyright_lines, "frontispiece": frontispiece,
            "front": front, "chapters": chapters}


def render(book: str, output: Path) -> None:
    # Typst can only read files inside the project root, so the data and cropped figures go into a temporary build folder
    # next to the PDF and are deleted afterwards — the figures live on only inside the PDF, no duplicate copies
    build_dir = local_env.stage_dir(book, "clean-pdf") / ".build"
    build_dir.mkdir(exist_ok=True)
    try:
        data_path = build_dir / "typst-data.json"
        data_path.write_text(json.dumps(build_typst_data(book, build_dir), ensure_ascii=False), encoding="utf-8")
        inputs = {"data": typst_path(data_path)}  # Typst paths are relative to root
        # ignore_system_fonts: the PDF must look identical on any machine, so only the bundled font is allowed
        # A copy beside the data: Typst only reads files under its root, and Book Studio's root is its own data folder
        template = shutil.copy(TEMPLATE, build_dir / TEMPLATE.name)
        typst.compile(str(template), output=str(output), root=str(local_env.PROJECT_ROOT), font_paths=[str(local_env.FONTS_DIR)], ignore_system_fonts=True, sys_inputs=inputs)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def main():
    book = (local_env.book_path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit(local_env.USAGE)).stem
    output = local_env.stage_dir(book, "clean-pdf") / f"{book}.pdf"
    render(book, output)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
