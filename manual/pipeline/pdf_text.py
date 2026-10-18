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


def span_text(span: dict) -> str:
    text = span["text"].replace("​", "")
    return text.translate(BALARAM) if span["font"].startswith("Balaram") else text


def page_lines(page) -> list[dict]:
    """Every text line on a page with its spans; page numbers and blank lines left out."""
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for ln in block.get("lines", []):
            spans = [{"text": span_text(s), "size": round(s["size"], 1),
                      "bold": bool(s["flags"] & 16) or "Bold" in s["font"], "italic": bool(s["flags"] & 2) or "Italic" in s["font"]}
                     for s in ln["spans"] if not s["font"].startswith("Type3")]  # Type3 = the Hindi PDF's page-number font
            text = "".join(s["text"] for s in spans).strip()
            if not text or (re.fullmatch(r"\d{1,3}", text) and ln["bbox"][1] > 0.9 * page.rect.height):
                continue
            size = Counter({s["size"]: len(s["text"].strip()) for s in spans}).most_common(1)[0][0]
            lines.append({"spans": spans, "text": text, "size": size, "y": ln["bbox"][1], "x0": ln["bbox"][0], "x1": ln["bbox"][2]})
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
            if new:
                paras.append({"kind": kind, "runs": [], "text": "", "page": page_no, "x0": l.get("x0", 0), "bullet": l.get("bullet", False)})
                last = paras[-1]
            elif last["runs"]:
                # Joining the next line: keep a deliberate short-line break (verse, address); otherwise a space,
                # or nothing after a word broken at a hyphen
                prev_line = lines[i - 1] if i > 0 else None
                if prev_line and prev_line["x1"] < SHORT_LINE * right:
                    last["runs"].append({"break": True})
                elif not last["text"].endswith("-"):
                    last["runs"].append({"text": " ", "bold": False, "italic": False, "size": l["size"]})
            for s in l["spans"]:
                last["runs"].append({"text": s["text"], "bold": s["bold"], "italic": s["italic"], "size": s["size"]})
            last["text"] = (last["text"] + " " + l["text"]).strip()
    return paras


def read_pdf(pdf) -> tuple[list[dict], float]:
    """All paragraphs of an open PyMuPDF document, plus its body font size."""
    pages = [page_lines(p) for p in pdf]
    body, pitch, right = body_metrics(pages)
    return paragraphs(pages, body, pitch, right), body
