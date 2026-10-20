# manual/pipeline/pdf_text.py
# Shared reader for finished, text-based book PDFs (not scans) — used by pdf_to_docx.py and pdf_to_epub.py.
# Rebuilds flowing text from PyMuPDF's lines: paragraphs from line spacing, headings from font size, bold/italic runs,
# verse line breaks, paragraphs re-joined across page breaks, and old Balaram-font diacritics decoded to real Unicode.

import re
import statistics
from collections import Counter

TERMINAL = tuple('.!?।॥:"”’\')')  # a paragraph ending in one of these doesn't continue on the next page
PARA_GAP = 1.25  # a line further below the previous one than this × normal line pitch starts a new paragraph
SHORT_LINE = 0.8  # a line ending before this fraction of the text width is a deliberate break (verse line, last line)
DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")

# Older ISKCON books are typeset in "Balaram" fonts, which draw diacritics over stand-in Latin-1 letters ("Kåñëa" prints as
# Kṛṣṇa). Text taken from such a PDF must be mapped back, or readers and e-readers show the stand-ins.
BALARAM = str.maketrans({
    "ä": "ā", "Ä": "Ā", "é": "ī", "É": "Ī", "ü": "ū", "Ü": "Ū", "å": "ṛ", "Å": "Ṛ", "è": "ṝ",
    "ì": "ṅ", "Ì": "Ṅ", "ï": "ñ", "Ï": "Ñ", "ö": "ṭ", "Ö": "Ṭ", "ò": "ḍ", "Ò": "Ḍ", "ë": "ṇ", "Ë": "Ṇ",
    "ç": "ś", "Ç": "Ś", "ñ": "ṣ", "Ñ": "Ṣ", "à": "ṁ", "À": "Ṁ", "ù": "ḥ", "Ù": "Ḥ",
})


BALARAM_FONTS: set[str] = set()  # fonts of this book that carry Balaram's stand-in letters, set by pdf_to_book via balaram_fonts()


def balaram_fonts(pdf) -> set[str]:
    """Fonts whose text is full of å ë ñ ç (letters English never uses): they hold Balaram-style stand-ins ("Kåñëa"), whatever
    the font is called, so their text is decoded."""
    seen = Counter()
    for page in pdf:
        for block in page.get_text("dict")["blocks"]:
            for ln in block.get("lines", []):
                for s in ln["spans"]:
                    seen[s["font"]] += len(re.findall(r"[åëñçÅËÑÇ]", s["text"]))
    return {font for font, n in seen.items() if n >= 20}


def span_text(span: dict) -> str:
    raw = span["text"].replace("​", "")
    if "\x03" in raw:  # a font without a text map: codes are 29 below the real letters, and "space" is code 3 ("WR\x03" = "to ")
        raw = "".join(chr(ord(c) + 29) if 3 <= ord(c) <= 100 else "é" if c == "Þ" else c for c in raw)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", raw)  # control characters some PDFs hide in the text (a stray \x08)
    # "Gaudiya" (Gaudiya Press / Tattva Vicara books) uses the very same stand-in letters as "Balaram"; so does any font found by
    # balaram_fonts() (ScaGoudy, TimesLTMM…), which pdf_to_book sets per book
    return text.translate(BALARAM) if span["font"].startswith(("Balaram", "Gaudiya")) or span["font"] in BALARAM_FONTS else text


def page_blocks_text(page) -> list[str]:
    """A page's text blocks as plain text (lines joined by newlines), old diacritic fonts decoded — for the copyright page."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        lines = ["".join(span_text(s) for s in ln["spans"]).strip() for ln in block.get("lines", [])]
        text = "\n".join(l for l in lines if l)
        if text:
            out.append(text)
    return out


DROP_FONTS: tuple = ()  # font-name prefixes whose text is decoration (a faded mantra used as page background), set per book
BOLD_PARA_PAGES: set[int] = set()  # pages (0-based) where a line opening with a bold term starts a new paragraph (a glossary)
PAGE_SHIFT: dict[int, float] = {}  # per page (0-based): points added to every x, so mirrored facing pages share one left margin


def page_shifts(pdf) -> dict[int, float]:
    """Facing pages are often mirrored: body text starts at x=47 on left pages and x=54 on right ones, which breaks the first-line
    indent test. Each page's own margin (its most common body-line start) is moved to the book's most common one; pages with too
    few lines to tell, or a shift over 10 pt (an indented verse page), are left alone."""
    sizes = Counter()
    for page in pdf:
        for l in page_lines(page):
            sizes[l["size"]] += len(l["text"])
    body = sizes.most_common(1)[0][0]
    per_page, overall = {}, Counter()
    for page in pdf:
        starts = Counter(round(l["x0"]) for l in page_lines(page) if l["size"] == body)
        if sum(starts.values()) >= 8:
            per_page[page.number] = starts.most_common(1)[0][0]
            overall[per_page[page.number]] += 1
    target = overall.most_common(1)[0][0]
    return {n: target - x for n, x in per_page.items() if 0 < abs(target - x) <= 10}

RUNNING_HEADS: set[str] = set()  # texts printed at the very top of many pages, set per book by pdf_to_book via running_heads()
TOP_BAND = 0.07  # a running head sits within this share of the page height from the top


def running_heads(pdf) -> set[str]:
    """Texts that open the top band of at least 4 pages — the book's running heads, which are not part of its text."""
    seen = Counter()
    for page in pdf:
        for block in page.get_text("dict")["blocks"]:
            for ln in block.get("lines", []):
                text = "".join(span_text(s) for s in ln["spans"]).strip()
                if text and ln["bbox"][1] < TOP_BAND * page.rect.height:
                    seen[text] += 1
    return {text for text, n in seen.items() if n >= 4}


def page_lines(page) -> list[dict]:
    """Every text line on a page with its spans; page numbers, running heads and blank lines left out."""
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for ln in block.get("lines", []):
            spans = [{"text": span_text(s), "size": round(s["size"], 1),
                      "bold": bool(s["flags"] & 16) or "Bold" in s["font"], "italic": bool(s["flags"] & 2) or "Italic" in s["font"]}
                     for s in ln["spans"] if not s["font"].startswith("Type3") and not s["font"].startswith(DROP_FONTS)]  # Type3 = the Hindi PDF's page-number font
            text = "".join(s["text"] for s in spans).strip()
            if not text or (re.fullmatch(r"\d{1,3}|[IVXLCivxlc]{1,6}", text) and ln["bbox"][1] > 0.9 * page.rect.height):
                continue
            if text in RUNNING_HEADS and ln["bbox"][1] < TOP_BAND * page.rect.height:
                continue
            sizes = Counter()  # characters per size (a dict comprehension let a trailing space overwrite the real count)
            for s in spans:
                sizes[s["size"]] += len(s["text"].strip())
            size = sizes.most_common(1)[0][0]
            shift = PAGE_SHIFT.get(page.number, 0)
            lines.append({"spans": spans, "text": text, "size": size, "y": ln["bbox"][1], "x0": ln["bbox"][0] + shift, "x1": ln["bbox"][2] + shift})
    return sorted(lines, key=lambda l: l["y"])


def body_metrics(pages: list[list[dict]]) -> tuple[float, float, float]:
    """Body font size (the most common), normal line pitch for it, and the right edge of full text lines."""
    pages = [[l for l in lines if "object" not in l] for lines in pages]  # pictures and tables placed between lines
    sizes = Counter()
    for lines in pages:
        for l in lines:
            sizes[l["size"]] += len(l["text"])
    body = sizes.most_common(1)[0][0]
    pitches = [b["y"] - a["y"] for lines in pages for a, b in zip(lines, lines[1:]) if a["size"] == b["size"] == body and 0 < b["y"] - a["y"] < 3 * body]
    right = statistics.quantiles([l["x1"] for lines in pages for l in lines if l["size"] == body], n=10)[-1]  # 90th percentile
    return body, statistics.median(pitches), right


def kind_of(size: float, body: float) -> str:
    """Title page lettering, part headings and entry headings, from their size relative to the body text."""
    if size >= 2.2 * body:
        return "Title"
    if size >= 1.4 * body:
        return "Heading 1"
    if size >= body + 2.5:
        return "Heading 2"
    return "p"


def indent_band(x0: float, margin: float) -> int:
    """0 = at the left margin, 1 = a paragraph's indented first line, 2 = an indented block (verse, list item, citation)."""
    return 0 if x0 < margin + 5 else 1 if x0 < margin + 25 else 2


def paragraphs(pages: list[list[dict]], body: float, pitch: float, right: float, margin: float | None = None,
               indent: float | None = None) -> list[dict]:
    """Group lines into paragraphs: a bigger gap, a change between heading and text, or a new page after a finished sentence.
    Each paragraph: {kind, runs: [{text, bold, italic, size} | {break}], text, page (0-based), x0}.
    A line may instead be {"object": …, "y": …} (a picture or table placed among the lines): it passes through as its own
    {"kind": "object"} entry and ends the paragraph before it.
    'margin' (the body's left edge) turns on indent rules for books that mark paragraphs by a first-line indent, not a gap:
    a line at the book's first-line 'indent' after a full one starts a paragraph (a note's hanging lines, a little less
    indented, don't), and moving into or out of an indented block starts a new block."""
    paras = []
    for page_no, lines in enumerate(pages):
        for i, l in enumerate(lines):
            if "object" in l:
                paras.append({"kind": "object", "object": l["object"], "runs": [], "text": "", "page": page_no})
                continue
            kind = kind_of(l["size"], body)
            last = paras[-1] if paras else None
            if i == 0:
                # Continue a paragraph cut by the page break only if it stopped mid-sentence
                new = not (last and last["kind"] == kind == "p" and not last["text"].rstrip().endswith(TERMINAL))
                if margin is not None and last and last["text"].rstrip().endswith("]"):
                    new = True  # a source line ("[Srimad-Bhagavatam 1.8.42]") at a page's foot ends its block
            elif "object" in lines[i - 1]:
                new = True
            else:
                new = (last["kind"] != kind or l["y"] - lines[i - 1]["y"] > PARA_GAP * pitch * (l["size"] / body)
                       or (kind != "p" and last["kind"] != "p" and l["size"] != lines[i - 1]["size"]))
                if margin is not None and kind == "p" and not new:
                    before, now = indent_band(lines[i - 1]["x0"], margin), indent_band(l["x0"], margin)
                    new = before != now and (before, now) != (1, 0)  # a first line's indent followed by full lines is one paragraph
                    if (before, now) == (0, 1) and indent is not None and abs(l["x0"] - indent) > 2.5:
                        new = False  # a hanging line (a note's second line), not a new paragraph's indent
                    # In an indented block, plain → italic (a translation, then its Sanskrit verse) starts a new block
                    italic = lambda ln: all(s["italic"] for s in ln["spans"] if s["text"].strip())
                    if before == now == 2 and italic(l) != italic(lines[i - 1]):
                        new = True
                    # A bracketed source runs until its "]" whatever the indents ("[Srimad-Bhagavatam" / "1.8.41]"),
                    # and closes its paragraph there
                    if last["text"].lstrip().startswith("[") and "]" not in last["text"]:
                        new = False
                    elif lines[i - 1]["text"].rstrip().endswith("]"):
                        new = True
            # A glossary (pages named in book_meta.json): every entry starts with its bold term, on a new line right after the
            # previous entry's last — nothing else (no indent, no gap) tells the entries apart
            first = next((s for s in l["spans"] if s["text"].strip()), None)
            if (not new and i > 0 and page_no in BOLD_PARA_PAGES and first and first["bold"] and "object" not in lines[i - 1]
                    and lines[i - 1]["text"].rstrip().endswith((".", "!", "?", ")", "”", "’"))):
                new = True
            if new:
                paras.append({"kind": kind, "runs": [], "text": "", "page": page_no, "x0": l.get("x0", 0), "x1": l.get("x1", 0), "bullet": l.get("bullet", False)})
                last = paras[-1]
            elif last["runs"]:
                # Joining the next line: keep a deliberate short-line break (verse, address); otherwise a space,
                # or nothing after a word broken at a hyphen
                prev_line = lines[i - 1] if i > 0 else None
                if prev_line and prev_line["x1"] < SHORT_LINE * right:
                    last["runs"].append({"break": True})
                elif not last["text"].endswith("-"):
                    last["runs"].append({"text": " ", "bold": False, "italic": False, "size": l["size"]})
                else:  # a line ended in "-": remember the join, so heal_hyphens() can tell a broken word from a real hyphen
                    last["runs"].append({"text": "", "bold": False, "italic": False, "size": l["size"], "joined": True})
            for s in l["spans"]:
                last["runs"].append({"text": s["text"], "bold": s["bold"], "italic": s["italic"], "size": s["size"]})
            last["text"] = (last["text"] + " " + l["text"]).strip()
            last["x1"] = max(last.get("x1", 0), l.get("x1", 0))
    heal_hyphens(paras)
    return paras


def heal_hyphens(paras: list[dict]) -> None:
    """A word the printer broke at a line end ("aus-" / "picious") is joined again when the whole word is used elsewhere in the
    book; otherwise the hyphen stays (it may be a real one: "karma-" / "kāṇḍa"). Marked joins are in the runs ("joined")."""
    vocabulary = Counter(w.lower() for p in paras for w in re.findall(r"\w{4,}", p["text"]))
    for p in paras:
        runs = p["runs"]
        for i, run in enumerate(runs):
            if not run.get("joined"):
                continue
            before = next((r for r in reversed(runs[:i]) if not r.get("break") and r["text"]), None)
            after = next((r for r in runs[i + 1:] if not r.get("break") and r["text"]), None)
            if not before or not after or not before["text"].endswith("-"):
                continue
            left = re.search(r"(\w+)-$", before["text"])
            right = re.match(r"(\w+)", after["text"])
            if left and right and vocabulary[(left.group(1) + right.group(1)).lower()] > 0:
                before["text"] = before["text"][:-1]
    for p in paras:
        p["runs"] = [r for r in p["runs"] if not r.get("joined")]


def read_pdf(pdf) -> tuple[list[dict], float]:
    """All paragraphs of an open PyMuPDF document, plus its body font size."""
    pages = [page_lines(p) for p in pdf]
    body, pitch, right = body_metrics(pages)
    return paragraphs(pages, body, pitch, right), body
