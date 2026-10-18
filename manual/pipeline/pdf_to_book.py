# manual/pipeline/pdf_to_book.py
# Stage 2 for books that arrive as clean digital PDFs (real text, not scans — e.g. Heart and Soul Connection): no OCR needed.
# Reads the text with pdf_text.py and writes the same output/<book>/2-assembled/book.json the scanned books produce, so
# typeset_book.py (our A5 design) and book_to_epub.py work unchanged. Sections come from the PDF's outline; pictures keep their
# place; tables are rebuilt row by row from their small print (zebra-shaded rows defeat table detection); drop caps rejoin.
# Usage: poetry run python manual/pipeline/pdf_to_book.py <path/to/book.pdf> --library <path/to/book-library>

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import json
import re
from collections import Counter

import pymupdf

from pdf_text import body_metrics, indent_band, page_lines, paragraphs

META_FILE = local_env.META_FILE
SKIP_SECTIONS = {"title page", "copyright", "contents", "table of contents"}  # we build our own title page and contents
TABLE_SIZE = 0.7  # lines printed smaller than this × body size are table text (small caps opening a section are bigger)
ROW_GAP = 10  # pt — table lines further apart than this start a new row (lines inside one cell sit ~7.5 pt apart)
COLUMN_GAP = 20  # pt — line starts further apart than this belong to different columns
PICTURE_SHARE = 0.05  # pictures smaller than this share of the page are icons (bullet check marks)


def runs_text(runs: list[dict], body: float) -> str:
    """A paragraph's runs in the assemblers' inline markup: <i>, <b>, and <sup> for small footnote numbers."""
    out = []
    for r in runs:
        if r.get("break"):
            out.append("\n")
            continue
        t = r["text"]  # plain text, as the OCR assemblers store it ("Heart & Soul"); only <i>/<b>/<sup> are markup
        if r["size"] < 0.9 * body and re.fullmatch(r"\s*\d{1,3}\s*", r["text"]):
            out.append(f"<sup>{t.strip()}</sup>")
            continue
        if r["italic"]:
            t = f"<i>{t}</i>"
        if r["bold"]:
            t = f"<b>{t}</b>"
        out.append(t)
    return re.sub(r"</i><i>|</b><b>", "", "".join(out)).strip()


def table_rows(lines: list[dict], body: float, edges: list[float] = None) -> list[list[str]]:
    """Rows of cells from a table's lines: a row gap starts a new row; columns come from the table's drawn cell edges when
    it has them, else from where lines start. A row with an empty first cell is the rest of the row before it."""
    if edges:
        columns = edges  # left edge of each column
    else:
        starts = sorted({round(l["x0"]) for l in lines})
        columns = [starts[0]]
        for x in starts[1:]:
            if x - columns[-1] > COLUMN_GAP:
                columns.append(x)
    rows, lowest = [], None
    for l in sorted(lines, key=lambda l: (round(l["y"]), l["x0"])):
        # A line well below every line so far opens a new row; one just below continues a cell (wrapped text)
        if lowest is None or l["y"] - lowest > ROW_GAP:
            rows.append([""] * len(columns))
        col = max([i for i, c in enumerate(columns) if l["x0"] >= c - (2 if edges else COLUMN_GAP / 2)] or [0])
        text = runs_text([{**s, "size": body} for s in l["spans"]], body)
        rows[-1][col] = (rows[-1][col] + " " + text).strip()
        lowest = l["y"] if lowest is None else max(lowest, l["y"])
    merged = []
    for row in rows:
        if merged and not row[0] and len(row) == len(merged[-1]):
            merged[-1] = [(a + " " + b).strip() for a, b in zip(merged[-1], row)]
        else:
            merged.append(row)
    return merged


def page_items(page, body: float, margin: float) -> list[dict]:
    """A page's text lines in reading order, with its pictures and tables placed among them as objects."""
    lines = page_lines(page)
    w, h = page.rect.width, page.rect.height
    # A decorated initial ("W" set large) belongs at the start of the line beside it ("HEN I FIRST JOINED…"); that first line,
    # set in small capitals, is body text
    for drop in [l for l in lines if len(l["text"]) == 1 and l["size"] >= 2 * body]:
        beside = [l for l in lines if l is not drop and l["x0"] > drop["x0"] and abs(l["y"] - drop["y"]) < 3]
        if beside:
            beside[0]["spans"][0] = {**beside[0]["spans"][0], "text": drop["text"] + beside[0]["spans"][0]["text"]}
            beside[0]["text"] = drop["text"] + beside[0]["text"]
            beside[0]["size"] = body
            lines.remove(drop)
    # Check-mark icons mark list items: the line level with an icon, to its right, starts an item
    icons = [b["bbox"] for b in page.get_text("dict")["blocks"] if b["type"] == 1
             and (b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1]) < PICTURE_SHARE * w * h]
    for l in lines:
        l["bullet"] = any(abs(l["y"] - (y0 + y1) / 2) < 8 and l["x0"] >= x1 for x0, y0, x1, y1 in icons)
    items = [l for l in lines if l["size"] >= TABLE_SIZE * body]
    # Tables: runs of consecutive small-print lines
    small = [l for l in lines if l["size"] < TABLE_SIZE * body]
    groups = []
    for l in small:
        if groups and l["y"] - groups[-1][-1]["y"] < 3 * ROW_GAP:
            groups[-1].append(l)
        else:
            groups.append([l])
    # Column edges from the table's drawn cells (only its shaded rows are detected as a table, but they span every column)
    drawn = []
    try:
        drawn = [t for t in page.find_tables(strategy="lines").tables]
    except Exception:
        pass
    for g in groups:
        top, bottom = g[0]["y"], g[-1]["y"]
        cells = [c for t in drawn if t.bbox[1] <= bottom + 5 and t.bbox[3] >= top - 5 for c in t.cells if c]
        edges = sorted({round(c[0]) for c in cells}) if cells else None
        items.append({"object": {"type": "table", "rows": table_rows(g, body, edges), "page": page.number + 1, "top": top}, "y": top})
    # Centred lines (a boxed list of the twelve principles, a verse): two or more in a row become one centred block
    centre = w / 2
    # (a full body line is symmetric too — a centred line also starts well in from the left margin)
    is_centred = lambda l: abs((l["x0"] + l["x1"]) / 2 - centre) < 4 and l["x0"] > margin + 8 and l["size"] < 1.4 * body
    run = []
    for l in items + [None]:
        if l is not None and "object" not in l and is_centred(l) and (not run or l["y"] - run[-1]["y"] < 3 * ROW_GAP):
            run.append(l)
            continue
        # An indented quotation is symmetric too, but all its lines start at the same indent; centred lines start all over
        if len(run) >= 2 and max(x["x0"] for x in run) - min(x["x0"] for x in run) > 15:
            italic = all(s["italic"] for x in run for s in x["spans"] if s["text"].strip())
            obj = ({"type": "quote", "lines": [x["text"] for x in run]} if italic
                   else {"type": "centred", "lines": [runs_text([{**s, "size": body} for s in x["spans"]], body) for x in run]})
            items = [x for x in items if not any(x is r for r in run)]
            items.append({"object": obj, "y": run[0]["y"]})
        run = [l] if l is not None and "object" not in l and is_centred(l) else []
    for b in page.get_text("dict")["blocks"]:
        x0, y0, x1, y1 = b["bbox"]
        if b["type"] == 1 and (x1 - x0) * (y1 - y0) >= PICTURE_SHARE * w * h:
            items.append({"object": {"type": "figure", "page": page.number + 1, "bbox": [x0, y0, x1, y1], "image_bbox": [0, 0, w, h], "caption": ""}, "y": y0})
    return sorted(items, key=lambda l: l["y"])


def merge_tables(blocks: list[dict]) -> list[dict]:
    """A table continued at the top of the next page is one table (and a row cut by the page break is one row)."""
    out = []
    for b in blocks:
        prev = out[-1] if out else None
        if (b["type"] == "table" and prev and prev["type"] == "table" and b["page"] == prev["page"] + 1 and b["top"] < 80
                and len(b["rows"][0]) == len(prev["rows"][0])):
            rows = b["rows"]
            if not rows[0][0]:  # the cut row's first cell stayed on the previous page
                prev["rows"][-1] = [(a + " " + c).strip() for a, c in zip(prev["rows"][-1], rows[0])]
                rows = rows[1:]
            prev["rows"] += rows
            prev["page"] = b["page"]
            continue
        out.append(b)
    return out


def section_of(title: str, page: int) -> dict:
    """Kind and display title from an outline entry: "1: Foundations: …" is chapter 1; Foreword/Introduction/Dedication are front matter."""
    if m := re.match(r"^(\d+)\s*:\s*(.+)$", title):
        return {"kind": "chapter", "title": m.group(2).strip(), "start_page": page}
    first = title.split(":")[0].split("&")[0].strip().lower()
    kind = "front" if first in ("foreword", "introduction", "dedication", "preface", "acknowledgements", "acknowledgments") else "back"
    return {"kind": kind, "title": title, "start_page": page}


def convert(book: str) -> None:
    pdf_path = local_env.find_book(book)
    book = pdf_path.stem  # the key in output/ and book_meta.json, whether given as a path or a name
    pdf = pymupdf.open(pdf_path)
    outline = [(t.strip(), p) for level, t, p in pdf.get_toc() if level == 1]
    body, pitch, right = body_metrics([page_lines(p) for p in pdf])
    # The body's left edge, for this book's first-line indents (paragraphs are not separated by a gap)
    starts = Counter(round(l["x0"]) for p in pdf for l in page_lines(p) if l["size"] == body)
    margin = starts.most_common(1)[0][0]
    indent = max((x for x in starts if indent_band(x, margin) == 1), key=lambda x: starts[x])  # the usual first-line indent
    paras = paragraphs([page_items(p, body, margin) for p in pdf], body, pitch, right, margin, indent)

    sections = []
    for i, (title, page) in enumerate(outline):
        end = outline[i + 1][1] if i + 1 < len(outline) else len(pdf) + 1
        if title.lower() in SKIP_SECTIONS:
            continue
        sec = {**section_of(title, page), "subtitle": "", "cover": None, "numeral": "", "footnotes": [], "blocks": []}
        mine = [p for p in paras if page <= p["page"] + 1 < end]
        # The printed title block (big lines at the top) is replaced by ours; its italic part is the author
        # ("Praharana devi dasi", "Cintamani devi dasi & Jagannatha Pandit dasa"), set under our title
        while mine and mine[0]["kind"] not in ("p", "object"):
            head = mine.pop(0)
            author = " ".join(r["text"].strip() for r in head["runs"] if not r.get("break") and r.get("italic") and r["text"].strip())
            if author:
                sec["subtitle"] = re.sub(r"\s+", " ", author)
        drop = ""
        for p in mine:
            if p["kind"] == "object":
                sec["blocks"].append(p["object"])
                continue
            text = runs_text(p["runs"], body)
            if p["kind"] == "Title" and len(p["text"]) == 1:
                drop = p["text"]  # a decorated initial: it begins the next paragraph ("W" + "HEN I FIRST JOINED")
                continue
            if drop:
                text, drop = drop + text, ""
            flat = text.replace("\n", " ")
            words = [r for r in p["runs"] if not r.get("break") and r["text"].strip()]
            italic = bool(words) and all(r["italic"] for r in words)
            if p["kind"] != "p" or (sec["title"] == "Notes" and re.fullmatch(r"(Foreword|Introduction|Chapter \d+|Concluding Words)", p["text"])):
                sec["blocks"].append({"type": "h", "text": flat})  # in Notes: the chapter each group of notes belongs to
            elif p["bullet"]:  # "In this chapter you will learn:" items, printed after a check-mark icon
                sec["blocks"].append({"type": "entry", "text": "• " + flat})
            elif re.fullmatch(r"\[.*\]", p["text"].strip()):
                sec["blocks"].append({"type": "cite", "text": flat})  # a quotation's source: "[Letter to Balai, 21 July 1969]"
            elif italic and indent_band(p["x0"], margin) == 2:
                sec["blocks"].append({"type": "quote", "lines": [re.sub(r"<[^>]+>", "", ln).strip() for ln in text.split("\n") if ln.strip()]})
            elif indent_band(p["x0"], margin) == 2:
                sec["blocks"].append({"type": "blockquote", "text": flat})
            else:
                sec["blocks"].append({"type": "p", "text": flat})
        sec["blocks"] = [{k: v for k, v in b.items() if k != "top"} for b in merge_tables(sec["blocks"])]
        sections.append(sec)

    out_dir = local_env.stage_dir(book, "assembled")
    data = {"book": book, "layout": "prose", "sections": sections}
    (out_dir / "book.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    report = [f"Source: digital PDF ({len(pdf)} pages, body {body}pt) — no OCR", f"Sections from the outline: {len(sections)}", ""]
    for s in sections:
        kinds = {t: sum(b["type"] == t for b in s["blocks"]) for t in ("p", "h", "figure", "table", "entry")}
        report.append(f"p{s['start_page']:>3}  [{s['kind']}] {s['title']} {s['subtitle']}".rstrip()
                      + f"  — {kinds['p']} paragraphs, {kinds['h']} subheadings, {kinds['figure']} pictures, {kinds['table']} tables, {kinds['entry']} list items")
        first = next((b["text"] for b in s["blocks"] if b["type"] == "p"), "")
        report.append(f"      starts: {re.sub(r'<[^>]+>', '', first)[:70]}")
    (out_dir / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[:2]))
    print(f"Wrote {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(local_env.USAGE)
    for name in map(str, map(local_env.book_path, sys.argv[1:])):
        convert(name)
