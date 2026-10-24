# manual/pipeline/typeset_book.py
# Stage 3 (final): typesets the assembled book (2-assembled/book.json) into one clean PDF of the whole book using Typst and Gentium Book Plus.
# Works for both layouts in book_meta.json — "verses" (Padyāvalī) and "prose" (Vraja-līlā) — by converting each into one shared template format.
# Usage: poetry run python manual/pipeline/typeset_book.py <path/to/book.pdf> --library <path/to/book-library>   → output/<book>/3-clean-pdf/<book>.pdf

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import json
import re
import shutil
import sys
from pathlib import Path

import pypdfium2 as pdfium
import typst

from figures import book_cover, crop_figure, has_ink
from ocr_text import PICTURE_LABELS, clean_inline, ocr_pages
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


def mark_headings(front: list[dict], chapters: list[dict]) -> None:
    """Subheadings: label-like or all-capitals ones are centred; every other (unique) one is a subtopic that the contents lists under
    its chapter, with its page — so the contents shows the chapter names and the topics inside each chapter."""
    from collections import Counter
    plain = lambda b: plain_text(b["segs"])  # noqa: E731
    counts = Counter(plain(b) for ch in chapters for b in ch["blocks"] if b["type"] == "h")
    for sec in front:
        for b in sec["blocks"]:
            if b["type"] == "h" and (LABEL_HEADING_RE.match(plain(b)) or (plain(b).isupper() and len(plain(b)) < 60)):
                b["centre"] = True
    for ci, ch in enumerate(chapters):
        k = 0
        for b in ch["blocks"]:
            if b["type"] != "h":
                continue
            text = plain(b)
            label = bool(LABEL_HEADING_RE.match(text))
            if label or (text.isupper() and len(text) < 60):
                b["centre"] = True
            if not label and 2 < len(text) <= 120 and not text.endswith((",", ";")) and (counts[text] <= 2 if not text.isupper() else counts[text] == 1 and not re.search(r"\d", text)):
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
        self.pdf = pdfium.PdfDocument(str(local_env.find_book(book)))
        self.build_dir = build_dir
        self.count = 0

    def place(self, b: dict, figure=None) -> dict:
        self.count += 1
        figure = figure or crop_figure(self.pdf, b["page"], b["bbox"], b["image_bbox"])
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
        chapters.append({"number": n if s["kind"] == "chapter" else None, "part": s["kind"] == "part", "title": s["title"], "subtitle": s["subtitle"],
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
            pages = [(n + 1, page_blocks_text(pdf[n])) for n in range(min(first_page - 1, len(pdf)))]  # decoded like the book's text
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
    frontispiece = front_figures(book, first_text_page(book, assembled), figures, set(meta.get("frontispiece_skip", [])))
    front, chapters = (from_prose_book if meta["layout"] == "prose" else from_verses_book)(assembled, figures)
    mark_headings(front, chapters)
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
