# manual/pipeline/pdf_to_book.py
# Stage 2 for books that arrive as clean digital PDFs (real text, not scans — e.g. Heart and Soul Connection): no OCR needed.
# Reads the text with pdf_text.py and writes the same output/<book>/2-assembled/book.json the scanned books produce, so
# typeset_book.py (our A5 design) and book_to_epub.py work unchanged. Sections come from the PDF's outline; pictures keep their
# place; tables are rebuilt row by row from their small print (zebra-shaded rows defeat table detection); drop caps rejoin.
# Usage: poetry run python manual/pipeline/pdf_to_book.py <path/to/book.pdf> --library <path/to/book-library>

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import difflib
import unicodedata
import json
import re
from collections import Counter

import pymupdf

import pdf_text
from book_tidy import tidy_sections
from ocr_text import ascii_key, tidy_dedication
from pdf_text import balaram_fonts, body_metrics, indent_band, page_lines, paragraphs, running_heads

META_FILE = local_env.META_FILE
SKIP_SECTIONS = {"title page", "copyright", "contents", "table of contents"}  # we build our own title page and contents
TABLE_SIZE = 0.7  # lines printed smaller than this × body size are table text (small caps opening a section are bigger)
ROW_GAP = 10  # pt — table lines further apart than this start a new row (lines inside one cell sit ~7.5 pt apart)
COLUMN_GAP = 20  # pt — line starts further apart than this belong to different columns
PICTURE_TRIM = {}  # page -> lowest y (pt) a picture may reach, from "trim_pictures" in book_meta.json (a heading drawn over its bottom edge)
PICTURE_SHARE = 0.05  # pictures smaller than this share of the page are icons (bullet check marks)
BULLET_MIN_SIZE = 0  # pt — icons smaller than this (either side) are not bullets; book_meta.json "bullet_min_size" sets it per book


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
    # Text wrapped beside a picture (a map at the left, lines starting at its right edge): measured from the picture's edge, so a wrapped
    # line reads as a full line of its paragraph — not as an indented block that splits the paragraph in two (Chaurasi-kosa's maps)
    # (any real image counts here, also a small map under the figure size: 135×113 pt beside a paragraph — not an icon or a speck)
    pictures = [r for r in (pymupdf.Rect(b["bbox"]) for b in page.get_text("dict")["blocks"] if b["type"] == 1) if min(r.width, r.height) >= 40 and r.get_area() >= 0.01 * w * h]
    beside_any = set()
    for r in pictures:
        overlaps = lambda l: l["y"] < r.y1 - 2 and l["y"] + l["size"] > r.y0 + 2  # noqa: E731
        left = [l for l in lines if overlaps(l) and l["x0"] >= r.x1 - 2 and r.x0 < margin + 20]
        right = [l for l in lines if overlaps(l) and l["x1"] <= r.x0 + 2 and r.x1 > w - margin - 20]
        if left:
            for l in left:  # a typed indent beside the picture counts from the picture's edge (its box starts there, not at the body's start)
                l["x0"], l["spaced"] = l.get("vis_x0", l["x0"]), l.get("vis_x0", l["x0"]) > l.get("box_x0", l["x0"]) + 1
            base = min(l.get("box_x0", l["x0"]) for l in left)
            # the wrap may start a line above the picture's top edge ("Sarasvatī’s Ṭhākura’s highly" over a photo set a little lower): same indent, within a line
            left += [l for l in lines if not any(l is x for x in left) and abs(l["x0"] - base) < 2 and 0 < r.y0 - l["y"] <= 1.6 * l["size"]]
            for l in left:
                l["x0"] = margin + (l["x0"] - base)  # (a first-line indent beside the picture stays an indent)
            # a paragraph may open right where the wrap starts, with no indent: the line above ends a sentence, the first wrapped line opens with a capital
            first = min(left, key=lambda l: l["y"])
            above = [l for l in lines if l["y"] < first["y"] - 1]
            if above and re.search(r"[.!?”\"’]\s*$", max(above, key=lambda l: l["y"])["text"]) and first["text"][:1].isupper():
                first["para_start"] = True
        if right:
            others = [l["x1"] for l in lines if not any(l is x for x in right)]
            for l in right:
                l["x1"] = max(others) if others else l["x1"]  # (not a short line: no deliberate break after it)
        if left or right:
            beside_any.add((round(r.x0), round(r.y0)))
    # A decorated initial ("W" set large) belongs at the start of the line beside it ("HEN I FIRST JOINED…"); that first line,
    # set in small capitals, is body text
    for drop in [l for l in lines if len(l["text"].strip()) <= 2 and l["text"].strip()[-1:].isalpha() and l["size"] >= 2 * body]:  # "“T" counts: an opening quote can come with the cap
        beside = [l for l in lines if l is not drop and l["x0"] > drop["x0"] and abs(l["y"] - drop["y"]) < max(3, 0.5 * drop["size"]) and l["y"] >= drop["y"] - 3]  # a tall cap starts above its line; a title above the cap is not that line
        if beside:
            beside[0]["spans"][0] = {**beside[0]["spans"][0], "text": drop["text"] + beside[0]["spans"][0]["text"]}
            beside[0]["text"] = drop["text"] + beside[0]["text"]
            beside[0]["size"] = body
            # the lines wrapped around the cap start further in than the paragraph does: put them back at the cap's own margin
            for l in lines:
                if l is not drop and l["x0"] > drop["x0"] and 0 <= l["y"] - drop["y"] < drop["size"]:
                    l["x0"] = drop["x0"]
            lines.remove(drop)
    # A cap only a little bigger than the body, on a line of its own above a small-capitals first line ("E" / "DDIE GAVE AWAY…"): glued on as well
    for cap in [l for l in lines if len(l["text"].strip()) == 1 and l["text"].strip().isupper()]:
        below = [l for l in lines if l is not cap and 0 < l["y"] - cap["y"] < 2.5 * cap["size"] and abs(l["x0"] - cap["x0"]) < 4 and re.match(r"[A-ZÀ-Ý]{2}", l["text"].strip())]
        if below:
            below[0]["spans"][0] = {**below[0]["spans"][0], "text": cap["text"].strip() + below[0]["spans"][0]["text"].lstrip()}
            below[0]["text"] = cap["text"].strip() + below[0]["text"].lstrip()
            lines.remove(cap)
    # Check-mark icons mark list items: the line level with an icon, to its right, starts an item
    icons = [b["bbox"] for b in page.get_text("dict")["blocks"] if b["type"] == 1
             and (b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1]) < PICTURE_SHARE * w * h
             and min(b["bbox"][2] - b["bbox"][0], b["bbox"][3] - b["bbox"][1]) >= BULLET_MIN_SIZE]  # (decoration drawn as thousands of tiny images is not a bullet)
    icons += pdf_text.bullet_boxes(page)
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
    # The text column's own centre, from this page's full body lines (mirrored facing pages put the column off the page's centre)
    full = [l for l in lines if "object" not in l and abs(l["size"] - body) < 0.3 and l["x1"] - l["x0"] > 0.6 * (w - 2 * margin)]
    col_left, col_right = (min(l["x0"] for l in full), max(l["x1"] for l in full)) if len(full) >= 4 else (margin, w - margin)
    centre = (col_left + col_right) / 2
    col_width = col_right - col_left
    # (a full body line is symmetric too — a centred line also starts well in from the left margin)
    # (a first line indented with typed spaces is never a centred line, even when it also ends early: it is measured from its box, as before spaces were read)
    start = lambda l: l.get("box_x0", l["x0"]) if l.get("spaced") else l["x0"]  # noqa: E731
    is_centred = lambda l: abs((start(l) + l["x1"]) / 2 - centre) < 4 and start(l) > col_left + 8 and l["size"] < 1.4 * body  # noqa: E731
    run = []
    for l in items + [None]:
        if l is not None and "object" not in l and is_centred(l) and (not run or l["y"] - run[-1]["y"] < 3 * ROW_GAP):
            run.append(l)
            continue
        # An indented quotation is symmetric too, but all its lines start at the same indent; centred lines start all over
        # A single centred line, clearly shorter than the text column, is a centred heading or number ("(1)", "The Ten Offences"), kept centred
        single = len(run) == 1 and abs(run[0]["size"] - body) < 0.5 and (run[0]["x1"] - run[0]["x0"]) < 0.72 * col_width and len(run[0]["text"]) < 90
        if (len(run) >= 2 and max(x["x0"] for x in run) - min(x["x0"] for x in run) > 15) or single:
            italic = all(s["italic"] for x in run for s in x["spans"] if s["text"].strip())
            obj = ({"type": "quote", "lines": [x["text"] for x in run]} if italic
                   else {"type": "centred", "lines": [runs_text([{**s, "size": body} for s in x["spans"]], body) for x in run]})
            items = [x for x in items if not any(x is r for r in run)]
            items.append({"object": obj, "y": run[0]["y"]})
        run = [l] if l is not None and "object" not in l and is_centred(l) else []
    for b in page.get_text("dict")["blocks"]:
        x0, y0, x1, y1 = b["bbox"]
        if b["type"] == 1 and (x1 - x0) * (y1 - y0) >= PICTURE_SHARE * w * h:
            # A picture drawn twice, a hair apart (a shadow or a mask beside it), is one picture
            y1 = min(y1, PICTURE_TRIM.get(page.number + 1, y1))
            same = [o for o in items if "object" in o and o["object"]["type"] == "figure" and abs(o["object"]["bbox"][0] - x0) < 4 and abs(o["object"]["bbox"][1] - y0) < 4]
            if same:
                continue
            items.append({"object": {"type": "figure", "page": page.number + 1, "bbox": [x0, y0, x1, y1], "image_bbox": [0, 0, w, h], "caption": "",
                                     "beside": (round(x0), round(b["bbox"][1])) in beside_any}, "y": y0})  # (beside: text wraps round it — placed after its paragraph)
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
    if m := re.match(r"^(Part \w+(?:-\w+)?)\s*:\s*(.+)$", title):  # (also "Part Twenty-One: …")
        return {"kind": "part", "title": m.group(1), "subtitle": m.group(2).strip(), "start_page": page}  # "Part One: Pūrva-campū — …": a part title page (book_meta.json sections)
    first = title.split(":")[0].split("&")[0].strip().lower()
    kind = "front" if first in ("foreword", "introduction", "dedication", "preface", "acknowledgements", "acknowledgments", "maṅgalācaraṇa") else "back"
    return {"kind": kind, "title": title, "start_page": page}


LABEL_RE = re.compile(r"^chapter\s+[\w-]+$", re.I)  # "Chapter One": a label that has its own outline entry before the real title
FRONT_LABELS = ("foreword", "introduction", "preface")


def part_of_title(text: str, title: str) -> bool:
    """A title-block line that is no subtitle: a bare chapter number ("2"), or a piece of the title itself, even spelled a little differently
    ("Sarvatra Prachar" / "Preaching" under "Sarvatra Pracāra — The Worldwide Preaching")."""
    t, whole = ascii_key(text), ascii_key(title)
    if not t or t.isdigit():
        return True
    return difflib.SequenceMatcher(None, t, whole).find_longest_match(0, len(t), 0, len(whole)).size >= 0.8 * len(t)


def clean_outline(entries: list[tuple[str, int]]) -> list[tuple[str, int, str, str]]:
    """(title, page) outline entries → (title, page, kind override, first heading). Word's hidden bookmarks ("_GoBack") are dropped;
    a bare "Chapter One" entry and the title on the same page become one chapter (with an optional "Part 1" entry after it);
    a chapter printed again under the same title continues as an unnumbered part; "Introduction" followed by its own title on
    the same page keeps that title as its first heading."""
    items = [(t, p) for t, p in entries if not t.startswith("_")]
    out, seen, i = [], set(), 0
    while i < len(items):
        title, page = items[i]
        nxt = items[i + 1] if i + 1 < len(items) else None
        if LABEL_RE.match(title) and nxt and nxt[1] == page:
            real, i = nxt[0], i + 2
            part = items[i][0] if i < len(items) and items[i][1] == page and re.fullmatch(r"part\s+\w+", items[i][0], re.I) else None
            i += part is not None
            full = f"{real}: {part}" if part else real
            out.append((("1: " + full) if real not in seen else full, page, "" if real not in seen else "back", ""))
            seen.add(real)
        elif title.lower() in FRONT_LABELS and nxt and nxt[1] == page:
            out.append((title, page, "", nxt[0]))
            i += 2
        else:
            out.append((title, page, "", ""))
            i += 1
    return out


def join_cut_paragraphs(blocks: list[dict]) -> list[dict]:
    """A plain paragraph that opens lowercase joins the earlier plain paragraph that stopped mid-sentence (pictures and tables between them do not matter).
    Read on the text without its tags ("<b>accompanying Him…" opens lowercase too); a "]" ends a paragraph only when it closes a "[source]";
    and a paragraph that stops on a word no sentence ends with ("…From Vrindavana first go to" / "Chhatikara & turn…") is continued by the next, whatever its case."""
    plain = lambda t: re.sub(r"<[^>]+>", "", t or "").strip()  # noqa: E731
    joined, last_p = [], None
    for blk in blocks:
        prev, text = plain(last_p["text"]) if last_p else "", plain(blk.get("text"))
        unfinished = bool(prev) and not re.search(r"[.!?:;”’)>]\s*$", prev) and not (prev.endswith("]") and prev.startswith("["))
        bold_only = last_p is not None and re.fullmatch(r"\s*<b>[^<]*</b>\s*", last_p["text"]) and len(prev) <= 60  # (a short bold label of its own is a heading, never continued — a bold translation line is not)
        # (a whole word after a space: in "śrī-caraṇa" with a combining dot below the n, "\b" would see a word "a" — a verse glued to its translation)
        dangling = re.search(r"(?:^|\s)(of|to|the|a|an|and|or|from|at|with|on|for|by|in|into|onto|as|than|via|past|after|before|behind|near|opposite|beside|between|towards?)$", unicodedata.normalize("NFC", prev))
        # An inset block is continued only as English prose (a quotation cut by a page turn): a verse set line by line ("avatirno bhavisyami…",
        # "hari he! dharma-nista…") holds no "the/and/of", and a capital label ("TEXTS 1-3") opens its verse, so neither is run together
        english = lambda t: len(re.findall(r"\b(?:the|and|of|is|are|that|which|was|were|with|to|in|on|for|not|a|an|i|he|she|his|her|it|you|we|they|my|me|be|by|as|have|had|should|would|this|from)\b", t.lower())) >= 2  # noqa: E731
        inset_ok = "blockquote" not in (blk["type"], last_p["type"] if last_p else "") or (english(prev) and english(text) and prev != prev.upper())
        # (nor a verse line set in italics — "mage va na mage keha…" under a byline — nor a short poem line ending on "the": "You, Prabhupada are the" / "Warmth…")
        verse = lambda b: re.fullmatch(r"\s*<i>.*</i>\s*", b.get("text") or "", re.S) and not english(plain(b["text"]))  # noqa: E731
        inset_ok = inset_ok and not (last_p is not None and (verse(last_p) or verse(blk)))
        dangling = dangling if len(prev) >= 60 else None
        # (or an orphan end: a line of one or two words that closes the sentence — "1968)" after "(Letter, 15 February", "Truth." — set apart by a stray indent)
        orphan = len(text.split()) <= 2 and bool(re.search(r"[.!?)”’\"]$", text))
        if (blk["type"] in ("p", "blockquote") and last_p is not None and unfinished and not bold_only and inset_ok and (text[:1].islower() or (dangling and text[:1].isupper()) or orphan)
                and not re.match(r"(?:<i>)?[^\s—–<.!?]{1,30}(?:[ -][^\s—–<.!?]{1,30}){0,3}(?:</i>)?\s?[—–]\s", blk["text"])):  # a glossary entry ("term – meaning") is a new paragraph, not a continuation — a term holds no sentence end ("chemistry. So okay — nitrogen…" continues)
            # The longer part decides the type: a drop cap's inset first lines + their paragraph is a paragraph; a quotation cut by a page
            # turn ("…established Himself as the Supreme Personality" / "of Godhead by His various activities…") stays a quotation
            if blk["type"] != last_p["type"] and len(plain(blk["text"])) > len(prev):
                last_p["type"] = blk["type"]
            last_p["text"] += " " + blk["text"]
            continue
        joined.append(blk)
        if blk["type"] in ("p", "blockquote"):
            last_p = blk
        elif blk["type"] not in ("figure", "table"):
            last_p = None
    return joined


def line_settings(sections: list[dict], meta: dict) -> None:
    """Per-book settings that cut, retype or realign whole paragraphs (also used by epub_to_book.py):
    "split_before" [regex, …] on a block's text with its tags — a paragraph is cut before each match (a list run on in one paragraph:
    "<b>1</b>. To have … <b>2</b>. To think …"; a signature's second line: "Vrindavana Dhama, Kartika");
    "heading_patterns" [regex, …] — a paragraph whose whole text matches is a subheading (as in the OCR route);
    "right_lines" [text, …] — paragraphs set right-aligned like a signature (as in the OCR route; before a dedication is tidied);
    "normal_case_openings": true — a section's opening words printed in capitals ("IN AUGUST 1970, AFTER FIVE YEARS in…") in normal case."""
    plain = lambda t: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t or "")).strip()  # noqa: E731
    for rx in [re.compile(p) for p in meta.get("split_before", [])]:
        hits = 0
        for sec in sections:
            out = []
            for b in sec["blocks"]:
                cuts = [m.start() for m in rx.finditer(b.get("text") or "") if m.start() > 0] if b["type"] in ("p", "blockquote") else []
                if not cuts:
                    out.append(b)
                    continue
                for a, z in zip([0] + cuts, cuts + [None]):
                    out.append({**b, "text": b["text"][a:z].strip()})
                hits += len(cuts)
            sec["blocks"] = out
        print(f"split before {rx.pattern!r}: {hits}" if hits else f"WARNING: split_before {rx.pattern!r} matched nothing")
    for rx in [re.compile(p) for p in meta.get("heading_patterns", [])]:
        hits = 0
        for sec in sections:
            for i, b in enumerate(sec["blocks"]):
                if b["type"] in ("p", "blockquote") and rx.fullmatch(plain(b["text"])):
                    sec["blocks"][i], hits = {"type": "h", "text": plain(b["text"])}, hits + 1
        print(f"heading pattern {rx.pattern!r}: {hits}" if hits else f"WARNING: heading pattern {rx.pattern!r} matched nothing")
    right, matched = set(meta.get("right_lines", [])), set()
    for sec in sections:
        for b in sec["blocks"]:
            if b["type"] in ("p", "blockquote") and plain(b["text"]) in right:
                b["type"] = "cite"  # (every such line: "—A. C. Bhaktivedanta Swami" closes dozens of quotations)
                matched.add(plain(b["text"]))
    for line in right - matched:
        print(f"WARNING: right_lines {line!r} matched nothing")
    # "verse_lines": ["line one / line two / …", …] — a verse run into its paragraph ("kṛṣṇa tvadīya-… kutas te "My Lord Kṛṣṇa…"): set apart as
    # its lines, the rest of the paragraph after it (an older build lost the verse's line breaks)
    for verse in meta.get("verse_lines", []):
        lines = [l.strip() for l in verse.split(" / ")]
        joined, hits = " ".join(lines), 0
        for sec in sections:
            out = []
            for b in sec["blocks"]:
                given = [plain(l) for l in b.get("lines") or []]
                if b["type"] in ("quote", "centred") and " ".join(given).startswith(joined):
                    # a verse block that is one long line, or that holds its source and translation too ("[Bg 3.21]", "Whatever action…")
                    k = next((n for n in range(1, len(given) + 1) if len(" ".join(given[:n])) >= len(joined)), len(given))
                    rest = " ".join(b["lines"][k:]).strip()
                    out += [{"type": "quote", "lines": lines}] + ([{"type": "p", "text": rest}] if rest else [])
                    hits += 1
                elif b["type"] in ("p", "blockquote") and plain(b["text"]).startswith(joined):
                    rest = b["text"][b["text"].index(lines[-1]) + len(lines[-1]):].strip() if lines[-1] in b["text"] else ""
                    rest = re.sub(r"^(?:</[ib]>\s*)+", "", rest)  # (the verse's own italics close here)
                    out += [{"type": "quote", "lines": lines}] + ([{**b, "type": "p", "text": rest}] if rest else [])  # (its translation: a paragraph below it)
                    hits += 1
                else:
                    out.append(b)
            sec["blocks"] = out
        print(f"verse {lines[0]!r}…: {hits}" if hits else f"WARNING: verse_lines {lines[0]!r} matched nothing")
    # "plain_sections" [title, …]: a list section whose lines only look like headings (a source list in capitals: "NJNK 28.05.91 SB 7.4.41")
    plain_titles = set(meta.get("plain_sections", []))
    for sec in sections:
        if sec["title"] in plain_titles:
            sec["blocks"] = [{"type": "p", "text": b["text"]} if b["type"] == "h" else b for b in sec["blocks"]]
    if meta.get("normal_case_openings"):
        normal_case_openings(sections, meta["normal_case_openings"])


def strip_text(sections: list[dict], patterns: list[str]) -> None:
    """"strip_text" [regex, …] (as in the OCR route): matches are taken out of every block's text, caption and lines — a decorative border
    an older build read as text ("HARE KRSNA HARE KRSNA… •" round every page of Without Fear); a block left empty is dropped, so the
    paragraph it cut can be joined again."""
    rxs = [re.compile(p) for p in patterns]
    plain = lambda t: re.sub(r"<[^>]+>", "", t or "").strip()  # noqa: E731
    clean = lambda t: re.sub(r"<(\w+)>\s*</\1>", "", re.sub(r"\s{2,}", " ", t)).strip()  # noqa: E731
    hits = Counter()
    for sec in sections:
        kept = []
        for b in sec["blocks"]:
            for key in ("text", "caption"):
                if isinstance(b.get(key), str):
                    for rx in rxs:
                        b[key], n = rx.subn(" ", b[key])
                        hits[rx.pattern] += n
                    b[key] = clean(b[key])
            if isinstance(b.get("lines"), list):
                lines = b["lines"]
                for rx in rxs:
                    lines = [rx.sub(" ", line) for line in lines]
                b["lines"] = [clean(line) for line in lines if plain(clean(line))]
            if b["type"] != "figure" and not plain(b.get("text")) and not b.get("lines") and b["type"] not in ("break", "notes-h", "table"):
                continue
            kept.append(b)
        sec["blocks"] = kept
    for p in patterns:
        print(f"strip {p!r}: {hits[p]}" if hits[p] else f"WARNING: strip_text {p!r} matched nothing")


def normal_case_openings(sections: list[dict], mode=True) -> None:
    """The book's small capitals at a section's opening, read as capitals ("IN AUGUST 1970, AFTER FIVE YEARS in the United States",
    "<b>Ś</b>RĪLA PRABHUPĀDA MET WITH THE…"): each word gets the casing the book itself uses most for it elsewhere ("August", "Śrīla
    Prabhupāda", "ISKCON", "in"), the first word a capital initial, and a bold drop-cap letter joins its word. Only a run of 2+ capital
    words followed by the paragraph's own text is touched — never a whole capital line, nor a label ending in a colon ("LEFTHAND PAGE:")."""
    seg_re = r"[^\W\d_]+"  # a run of letters: "PRABHUPĀDA'S" and "NĀMA-SAṄKĪRTANA" are recased part by part
    untag = lambda t: re.sub(r"<[^>]+>", "", t or "")  # noqa: E731
    usage: dict[str, Counter] = {}
    capitals = Counter()  # words the book prints in capitals inside lowercase text (ISKCON, BBT) — not in a capital line ("END OF APPENDIX II")
    for sec in sections:
        for b in sec["blocks"]:
            if b["type"] == "h":
                continue  # (headings are title-cased: "Sixteen Rounds" says nothing about "sixteen")
            text = re.sub(r"<[^>]+>", " ", b.get("text") or "")
            segs = list(re.finditer(seg_re, text))
            for k, m in enumerate(segs):
                w = m.group()
                if w.isupper() and len(w) > 1:
                    near = [segs[j].group() for j in (k - 1, k + 1) if 0 <= j < len(segs)]
                    if near and all(not n.isupper() for n in near):
                        capitals[w.lower()] += 1
                elif not w.isupper() and not re.search(r"(^|[.!?:;“\"‘—]\s*)$", text[:m.start()]):  # (a sentence's first word is capitalised anyway)
                    usage.setdefault(w.lower(), Counter())[w] += 1
    def recase_seg(seg: str) -> str:
        if not seg.isupper() or seg == "I":
            return seg
        seen = usage.get(seg.lower(), Counter())
        if capitals[seg.lower()] >= 2 and capitals[seg.lower()] > 3 * sum(seen.values()):
            return seg  # an acronym the book prints in capitals ("When I joined ISKCON in 1971")
        if seen:
            return seen.most_common(1)[0][0]
        return seg[:1] + seg[1:].lower() if any(ord(c) > 127 for c in seg) else seg.lower()  # (unseen: a Sanskrit name keeps its capital)
    def recase(word: str, first: bool) -> str:
        out = re.sub(seg_re, lambda m: recase_seg(m.group()), word)  # (letters inside tags are lowercase, so tags pass unchanged)
        if first:
            out = re.sub(r"(?<![<\w/])([^\W\d_])", lambda m: m.group(1).upper(), out, count=1)
        return out
    capital = lambda w: any(c.isalpha() for c in untag(w)) and untag(w) == untag(w).upper()  # noqa: E731  (an italic word inside the run counts too)
    hits = 0
    # "normal_case_openings": "all" — also every later paragraph or quotation that opens the same way (Without Fear sets each quoted passage so)
    every = mode == "all"
    targets = [x for sec in sections for x in sec["blocks"] if x["type"] in ("p", "blockquote")] if every else \
              [b for b in (next((x for x in sec["blocks"] if x["type"] == "p"), None) for sec in sections) if b]
    for b in targets:
        if every and re.match(r"(?:<[^>]+>)*END OF\b", b["text"]):
            continue  # a printed end marker ("END OF APPENDIX II"), set in capitals on purpose
        lead = re.match(r"(?:<(?!b>\w</b>)[^>]+>)*[“\"‘']?", b["text"])[0]  # (opening tags and quote — not a drop cap's own <b>)
        body = re.sub(r"^<b>(\w)</b>(?=[^\W\d_])", r"\1", b["text"][len(lead):])  # (a bold drop cap: "<b>W</b>HEN" is "WHEN")
        tokens = body.split(" ")
        run = 0
        while run < len(tokens) and (capital(tokens[run]) or not any(c.isalpha() for c in untag(tokens[run]))):
            run += 1
        letters_words = [w for w in tokens[:run] if sum(c.isalpha() for c in untag(w)) >= 2]  # (initials "A. C." are no capital run)
        if len(letters_words) < 2 or run >= len(tokens) or tokens[run - 1].endswith(":"):
            continue
        b["text"] = lead + " ".join([recase(w, k == 0) for k, w in enumerate(tokens[:run])] + tokens[run:])
        hits += 1
    print(f"normal-case openings: {hits}")


def apply_fixes(sections: list[dict], meta: dict) -> None:
    """book_meta.json corrections to the text, each printed with its number of matches (a fix that matches nothing is warned about):
    "text_fixes" [["wrong", "right"], …] — plain text, e.g. a running head caught mid-sentence;
    "word_fixes" {"Te": "The", …} — whole words whose letters the text layer lost (a ligature "Th" or "ft" that was not written out);
    "regex_fixes" [["pattern", "replacement"], …]. They reach paragraphs, captions, verse lines and section titles."""
    fixes = [(w, r, re.compile(re.escape(w))) for w, r in meta.get("text_fixes", [])]
    fixes += [(w, r, re.compile(r"(?<![\w’])" + re.escape(w) + r"(?![\w’])")) for w, r in meta.get("word_fixes", {}).items()]
    fixes += [(pat, r, re.compile(pat)) for pat, r in meta.get("regex_fixes", [])]
    for wrong, right_text, rx in fixes:
        hits = 0
        for sec in sections:
            sec["title"] = rx.sub(right_text, sec["title"])
            sec["subtitle"], n = rx.subn(right_text, sec.get("subtitle") or "")
            hits += n
            for blk in sec["blocks"]:
                for key in ("text", "caption"):
                    if isinstance(blk.get(key), str):
                        blk[key], n = rx.subn(right_text, blk[key])
                        hits += n
                if isinstance(blk.get("lines"), list):
                    for k, line in enumerate(blk["lines"]):
                        blk["lines"][k], n = rx.subn(right_text, line)
                        hits += n
        print(f"fix {wrong!r} → {right_text!r}: {hits}" if hits else f"WARNING: fix {wrong!r} matched nothing")


def convert(book: str) -> None:
    pdf_path = local_env.find_book(book)
    book = pdf_path.stem  # the key in output/ and book_meta.json, whether given as a path or a name
    pdf = pymupdf.open(pdf_path)
    meta = json.loads(META_FILE.read_text(encoding="utf-8")).get(book, {}) if META_FILE.is_file() else {}
    PICTURE_TRIM.update({int(k): v for k, v in meta.get("trim_pictures", {}).items()})
    pdf_text.DROP_FONTS = tuple(meta.get("drop_fonts", []))  # decoration set in its own font (a faded mantra behind the text)
    global BULLET_MIN_SIZE
    BULLET_MIN_SIZE = meta.get("bullet_min_size", 0)
    pdf_text.GNP_FONTS = pdf_text.gnp_fonts(pdf)  # the BBT's old Macintosh fonts ("K®ß∫a"): their own stand-in table
    pdf_text.BALARAM_FONTS = balaram_fonts(pdf)  # fonts holding Balaram-style stand-in letters are decoded, whatever their name
    pdf_text.BALARAM_FONTS |= set(meta.get("balaram_fonts", []))  # a heading font with too few stand-in letters to be found by itself
    if meta.get("bold_paragraph_pages"):  # [first, last] scan pages of a glossary: each bold term opens an entry
        first_pg, last_pg = meta["bold_paragraph_pages"]
        pdf_text.BOLD_PARA_PAGES = set(range(first_pg - 1, last_pg))
    pdf_text.FIRST_INDENT_MAX = meta.get("first_indent_max", pdf_text.FIRST_INDENT_MAX)
    pdf_text.DEEP_FIRST_LINES = bool(meta.get("deep_first_lines", False))
    line_pages = set(range(meta["line_pages"][0], meta["line_pages"][1] + 1)) if meta.get("line_pages") else set()  # a list of names: one line, one item
    pdf_text.LINE_PAGES = {n - 1 for n in line_pages}
    pdf_text.DROP_LINES = meta.get("drop_lines", [])
    pdf_text.HEADING_LINES = {re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()) for t in meta.get("heading_lines", [])}
    pdf_text.BULLET_FONTS = tuple(meta.get("bullet_fonts", []))
    pdf_text.PAGE_NUMBER_BAND = meta.get("page_number_band", pdf_text.PAGE_NUMBER_BAND)
    pdf_text.NUMBERED_ITEMS = bool(meta.get("numbered_items"))
    pdf_text.HEAL_ENGLISH = bool(meta.get("heal_hyphens"))
    pdf_text.HEADING_EXTRA = meta.get("heading_extra", pdf_text.HEADING_EXTRA)
    if meta.get("mirrored_pages"):  # facing pages with mirrored margins: align each page's margin before measuring indents
        pdf_text.PAGE_SHIFT = pdf_text.page_shifts(pdf, meta["mirrored_pages"] if isinstance(meta["mirrored_pages"], (int, float)) and not isinstance(meta["mirrored_pages"], bool) else 10)
    # Topics the PDF's own outline lists below its chapters (levels 2 and 3): a line in the text with the same words is a subheading,
    # so the contents shows them under their chapter as the original does
    topic_pages: dict[str, set[int]] = {}
    for level, title, page in pdf.get_toc():
        if level >= 2:
            topic_pages.setdefault(re.sub(r"\W+", "", title.lower()), set()).add(page)
    is_topic = lambda text, page: any(abs(page - pg) <= 1 for pg in topic_pages.get(re.sub(r"\W+", "", text.lower()), ()))  # noqa: E731
    outline = clean_outline([(t.strip(), p) for level, t, p in pdf.get_toc() if level == 1])
    if meta.get("sections") and (not outline or meta.get("sections_replace")):  # "sections_replace": use the list even though the PDF has an outline (numbered chapters, other titles). "sections": [["1: Title", first PDF page], …] — for a digital PDF without an outline (the chapters are found on its pages)
        outline = [(e[0], e[1], "", "") for e in meta["sections"]]  # an entry may add a third item: the text its section begins with (several sections share a page)
    markers = [e[2] if len(e) > 2 else "" for e in meta["sections"]] if outline and meta.get("sections") and (not pdf.get_toc() or meta.get("sections_replace")) else []
    pdf_text.RUNNING_HEADS = running_heads(pdf)  # the book's own running heads are dropped from its text
    body, pitch, right = body_metrics([page_lines(p) for p in pdf])
    if meta.get("normalise_sizes"):  # chapters with their own body size (17 pt, 14 pt…): every page is scaled to the book's most common size
        pdf_text.PAGE_SCALE = pdf_text.page_scales(pdf, body)
        body, pitch, right = body_metrics([page_lines(p) for p in pdf])
    # The body's left edge, for this book's first-line indents (paragraphs are not separated by a gap)
    body_lines = [l for p in pdf for l in page_lines(p) if l["size"] == body]
    starts = Counter(round(l["x0"]) for l in body_lines)
    typed = {round(l["x0"]) for l in body_lines if l.get("spaced")}  # (indents typed as spaces: first lines however deep — Radha Govinda Meditation's 35 pt)
    margin = starts.most_common(1)[0][0]
    first_lines = [x for x in starts if indent_band(x, margin, x in typed) == 1]
    # The usual first-line indent; a book with none separates paragraphs by a gap, so the gaps alone split it
    indent = max(first_lines, key=lambda x: starts[x]) if first_lines else None
    # A skipped page reads as empty, so no text on the next page is glued onto one of its paragraphs and lost with it (an epigraph after a printed contents)
    skipped = set(meta.get("skip_pages", []))
    paras = paragraphs([page_items(p, body, margin) if i + 1 not in skipped else [] for i, p in enumerate(pdf)], body, pitch, right, margin if indent is not None else None, indent)

    # Per-book settings (book_meta.json): "drop_sections" — outline titles left out (a page-number index means nothing once the
    # book is reflowed); "skip_pages" — scan pages left out (the publisher's back cover)
    front_titles = {t.lower() for t in meta.get("front_sections", [])}
    back_titles = {t.lower() for t in meta.get("back_sections", [])}
    # a paragraph set smaller than the body (most of its letters at least 0.8 pt below it, but no table print)
    def small_print(p):
        sizes = Counter()
        for r in p["runs"]:
            if not r.get("break") and r["text"].strip():
                sizes[round(r["size"], 1)] += len(r["text"].strip())
        return bool(sizes) and TABLE_SIZE * body <= sizes.most_common(1)[0][0] <= body - 0.8
    skip_titles = SKIP_SECTIONS | {t.lower() for t in meta.get("drop_sections", [])}
    skip_pages = set(meta.get("skip_pages", []))
    paras = [p for p in paras if p["page"] + 1 not in skip_pages]
    # "skip_pictures": pages whose pictures are decoration (a page-sized faded overlay) — the text stays. "picture_pages": pages set
    # as one full-width picture, whatever else is on them (a full-page painting that opens a part)
    skip_pictures, picture_pages = set(meta.get("skip_pictures", [])), sorted(meta.get("picture_pages", []))
    paras = [p for p in paras if not (p["kind"] == "object" and p["object"]["type"] == "figure" and p["page"] + 1 in skip_pictures)]
    # A page-sized picture on a page that also holds a paragraph of text is a background (a faded pattern with the page's own text in it): it would print the page twice
    words = Counter()
    for p in paras:
        words[p["page"]] += len((p["text"] or "").split()) if p["kind"] == "p" else 0
    def page_sized(p):
        x0, y0, x1, y1 = p["object"].get("bbox", (0, 0, 0, 0))
        w, h = pdf[p["page"]].rect.width, pdf[p["page"]].rect.height
        return (x1 - x0) * (y1 - y0) >= 0.9 * w * h
    paras = [p for p in paras if not (p["kind"] == "object" and p["object"]["type"] == "figure" and words[p["page"]] >= 40 and page_sized(p) and p["page"] + 1 not in picture_pages)]
    if picture_pages:
        paras = [p for p in paras if p["page"] + 1 not in picture_pages]

        def ink_box(page):
            """The text, drawings and small images of a text page (its page number and its own section title left out — the title is printed by us),
            or None for a page that is mostly a picture (a painting keeps the whole page and its margin trim)."""
            titles = {ascii_key(t[0]) for t in outline}
            pictures = [r for im in page.get_images(full=True) for r in page.get_image_rects(im[0])]
            if any(r.get_area() > 0.5 * page.rect.get_area() for r in pictures):
                return None
            ink = [pymupdf.Rect(b[:4]) for b in page.get_text("blocks") if b[4].strip() and not re.fullmatch(r"\s*\d+\s*", b[4]) and ascii_key(b[4]) not in titles] + [d["rect"] for d in page.get_drawings()] + pictures
            if not ink:
                return None
            r = ink[0]
            for x in ink[1:]:
                r |= x
            return r
        inks = {pg: ink_box(pdf[pg - 1]) for pg in picture_pages}
        # One text column for all of them, so every such page prints at the same scale (a page of five short lines is not blown up to giant type)
        column = [min(r.x0 for r in inks.values() if r), max(r.x1 for r in inks.values() if r)] if any(inks.values()) else None
        for pg in picture_pages:
            page = pdf[pg - 1]
            w, h = page.rect.width, page.rect.height
            box, exact = [0, 0, w, h], False
            if r := inks[pg]:  # a text-only page (a list in a script Gentium lacks): cropped to its text, or a Letter page prints at 6 pt on A5
                box, exact = [max(0, column[0] - 12), max(0, r.y0 - 4), min(w, column[1] + 12), min(h, r.y1 + 12)], True
            paras.append({"kind": "object", "runs": [], "text": "", "page": pg - 1, "object": {
                "type": "figure", "page": pg, "bbox": box, "image_bbox": [0, 0, w, h], "caption": "", "wide": True, "exact": exact}})  # (exact: the crop is kept as is, no margin trim)
        paras.sort(key=lambda p: p["page"])  # a stable sort: the order within a page is kept

    sections = []
    # Sections that begin mid-page: each starts at the paragraph opening with its marker (else at its page's first paragraph) and runs to the next one's start
    cuts = []
    if any(markers):
        for (_, page, _, _), mark in zip(outline, markers):
            cuts.append(next((k for k, p in enumerate(paras) if p["page"] + 1 >= page and (not mark or p["page"] + 1 == page and ascii_key(re.sub(r"<[^>]+>", "", p["text"] or " ".join(p["object"].get("lines", [])) if p["kind"] == "object" else p["text"])).startswith(ascii_key(mark)))), len(paras)))
            if mark and cuts[-1] == len(paras):
                print(f"  ! marker not found on page {page}: {mark!r}")  # the section would come out empty  # (a centred heading is an object: its lines are the text)
    for i, (title, page, kind, lead) in enumerate(outline):
        end = outline[i + 1][1] if i + 1 < len(outline) else len(pdf) + 1
        if title.lower() in skip_titles:
            continue
        sec = {"subtitle": "", "cover": None, "numeral": "", "footnotes": [], "blocks": [], **section_of(title, page)}
        if title.lower() in front_titles:
            sec["kind"] = "front"  # book_meta.json "front_sections": titles that open the book (about the author, dedication, how to use it…)
        if title.lower() in back_titles:
            sec["kind"] = "back"  # book_meta.json "back_sections": a title that would open the book but closes this one ("Acknowledgments" at the end)
        if kind:
            sec["kind"] = kind
        if lead:
            sec["blocks"].append({"type": "h", "text": lead})
        mine = paras[cuts[i]:cuts[i + 1] if i + 1 < len(cuts) else len(paras)] if cuts else [p for p in paras if page <= p["page"] + 1 < end]
        # The printed title block (big lines at the top) is replaced by ours; its italic part is the author
        # ("Praharana devi dasi", "Cintamani devi dasi & Jagannatha Pandit dasa"), set under our title
        # (a label line set a little larger than the body — "Chapter Three", "Part 1" — belongs to that block too)
        # — but only when it is centred, like the title block (a left-aligned enlarged line is a heading inside the chapter)
        centre = pdf[0].rect.width / 2
        # (a title block is a few short lines: a longer centred paragraph — an epigraph, a chapter's introduction — is text, and ends the block)
        enlarged = lambda p: (sec["kind"] != "front" and p["kind"] == "p" and len(p["text"].split()) <= 20 and abs((p["x0"] + p.get("x1", 0)) / 2 - centre) < 8 and p["runs"]  # noqa: E731
                              and all(r.get("break") or not r["text"].strip() or r["size"] >= body + 0.9 for r in p["runs"]))
        opening = lambda p: re.sub(r"<[^>]+>", "", " ".join(p["object"].get("lines", [])) if p["kind"] == "object" else p["text"]).strip()  # noqa: E731
        if cuts and markers[i] and mine and opening(mine[0]) == markers[i]:  # (a centred line counts too: "CHAPTER— II" set centred)
            mine.pop(0)  # the heading line that opens the section repeats its title
        popped = []
        centred_title = lambda p: bool(meta.get("centred_title_block")) and p["kind"] == "object" and p["object"]["type"] == "centred" and sec["kind"] == "chapter"  # noqa: E731  (a chapter whose label and title are centred line objects)
        short = lambda p: len((p.get("text") or "").split()) <= 20 and not re.match(r"\d+\.(?:[\s​]|$)", (p.get("text") or "").strip())  # noqa: E731  (a boxed quotation above the chapter label is text, not part of the title; nor is the first numbered story, "1." + its title)
        while not meta.get("no_title_block") and mine and short(mine[0]) and (mine[0]["kind"] not in ("p", "object") or enlarged(mine[0]) or centred_title(mine[0])):  # "no_title_block": chapters start straight with their first story, no title page
            head = mine.pop(0)
            popped.append(re.sub(r"\s+", " ", " ".join(re.sub(r"<[^>]+>", "", l) for l in head["object"]["lines"]) if head["kind"] == "object" else "".join(" " if r.get("break") else r["text"] for r in head["runs"])).strip())  # (runs as they are: a diacritic set in its own font is a run of its own — "Avat" + "ā" + "ra")
            author = " ".join(r["text"].strip() for r in head["runs"] if not r.get("break") and r.get("italic") and r["text"].strip())
            if author and not part_of_title(author, sec["title"]):  # (an italic title's own lines are not its author)
                sec["subtitle"] = re.sub(r"\s+", " ", author)
        popped = [re.sub(r"(?<=\w) ’ (?=\w)", "’", re.sub(r"“ | ”", lambda m: m.group().strip(), p)).replace(" – ", "–") for p in popped]  # Word's loose spacing around quotes and dashes
        dated = next((j for j, p in enumerate(popped) if j >= 2 and re.search(r"\b(1[89]\d\d|20\d\d)\b|\d0’?s\b", p)), None)
        if not sec["subtitle"] and popped and re.fullmatch(r"chapter\s+\d+", popped[0], re.I) and dated:  # "CHAPTER 8" / title / "VRINDAVAN 1973–1974" / first heading
            sec["subtitle"] = popped[dated]
            sec["blocks"] += [{"type": "h", "text": p} for p in popped[dated + 1:]]  # lines after the place and date open the chapter's text
        elif not sec["subtitle"] and len(popped) >= 3:  # "Chapter One" / "Nāma-Aparādha" / "The Ten Offences…": the last line is the subtitle
            last = popped[-1]
            same_as_title = part_of_title(last, sec["title"])  # (or the title's own last line: "…The Worldwide / Preaching", or a bare chapter number)
            if last and not same_as_title and not LABEL_RE.match(last) and not re.fullmatch(r"part\s+\w+", last, re.I):
                sec["subtitle"] = last
        if not (popped and re.fullmatch(r"chapter\s+\d+", popped[0], re.I) and dated):
            # A title-block line that became neither the title, a label nor the subtitle is the first heading of the text, never dropped
            # ("Appendix" opening with "Śrīla Prabhupāda - The Founder Acharya")
            sub = ascii_key(sec.get("subtitle") or "")
            unlabelled = lambda p: re.sub(r"^(chapter|part)\s+[\w-]+[\s:.]+", "", p, flags=re.I)  # noqa: E731  ("CHAPTER TWO Ontology" is the title again)
            sec["blocks"] += [{"type": "h", "text": p} for p in popped if p and not part_of_title(unlabelled(p), sec["title"]) and not LABEL_RE.match(p)
                              and not re.fullmatch(r"part\s+\w+(?:-\w+)?", p, re.I) and not (sub and (sub in ascii_key(p) or part_of_title(p, sec["subtitle"])))]
        drop = ""
        for p in mine:
            if p["kind"] == "object":
                obj = p["object"]
                if obj["type"] in ("centred", "quote") and is_topic(" ".join(re.sub(r"<[^>]+>", "", l) for l in obj["lines"]), p["page"] + 1):
                    sec["blocks"].append({"type": "h", "text": " ".join(re.sub(r"<[^>]+>", "", l) for l in obj["lines"]).strip()})  # a line the PDF's own outline lists
                    continue
                if meta.get("bold_headings") and obj["type"] == "centred" and len(obj["lines"]) == 1 and re.fullmatch(r"<b>[^<]{3,90}</b>", obj["lines"][0].strip()):  # one bold centred line = a subheading (opt-in)
                    heading = re.sub(r"<[^>]+>", "", obj["lines"][0]).strip()
                    if re.sub(r"\W", "", heading.lower()) != re.sub(r"\W", "", sec["title"].lower()):
                        sec["blocks"].append({"type": "h", "text": heading})
                    continue
                sec["blocks"].append(obj)
                continue
            text = runs_text(p["runs"], body)
            if p["kind"] == "Title" and len(p["text"]) == 1:
                drop = p["text"]  # a decorated initial: it begins the next paragraph ("W" + "HEN I FIRST JOINED")
                continue
            if drop:
                text, drop = drop + text, ""
            flat = re.sub(r"(?<=\S) {2,}", " ", text.replace("\n", " "))  # Word text carries doubled spaces
            if p["kind"] == "p" and is_topic(re.sub(r"<[^>]+>", "", flat), p["page"] + 1):
                sec["blocks"].append({"type": "h", "text": re.sub(r"<[^>]+>", "", flat).strip()})  # listed in the PDF's own outline, so a topic of its chapter
                continue
            words = [r for r in p["runs"] if not r.get("break") and r["text"].strip()]
            italic = bool(words) and all(r["italic"] for r in words)
            caps_heading = len(p["text"]) < 60 and p["text"].isupper() and len(p["text"].split()) <= 6 and sum(c.isalpha() for c in p["text"]) >= 6 and not p["text"].rstrip().endswith(("”", '"'))  # "FINANCIAL", "HEALTH": a typed-up book's subheading (not the capitals ending a quoted sentence: EVEN THE AIRPORT.”)
            if p["kind"] == "p" and p["page"] + 1 in line_pages and p["runs"] and p["runs"][0].get("size", body) < body - 1:  # (only the list's small print, not text that shares the page)
                sec["blocks"].append({"type": "entry", "text": flat})
                continue
            bold_heading = bool(meta.get("bold_headings")) and p["kind"] == "p" and 2 < len(p["text"]) < 90 and bool(words) and all(r["bold"] for r in words) and not p["text"].rstrip().endswith((".", ",", ";"))  # a bold line at body size is a subheading (opt-in: Rosen's Milwaukee to Mayapur)
            if p["kind"] != "p" and len(p["text"].split()) > 20:
                sec["blocks"].append({"type": "blockquote", "text": flat})  # a passage set in large type (a pull quote, a chapter's introduction) is text, never a heading
            elif p["kind"] != "p" or caps_heading or bold_heading or (sec["title"] == "Notes" and re.fullmatch(r"(Foreword|Introduction|Chapter \d+|Concluding Words)", p["text"])):
                if re.sub(r"\W", "", re.sub(r"<[^>]+>", "", flat).lower()) != re.sub(r"\W", "", sec["title"].lower()):  # (not the section's own title again, bold or not)
                    sec["blocks"].append({"type": "h", "text": re.sub(r"<[^>]+>", "", flat).strip() if bold_heading else flat})  # in Notes: the chapter each group of notes belongs to
            elif p["bullet"]:  # "In this chapter you will learn:" items, printed after a check-mark icon
                sec["blocks"].append({"type": "entry", "text": "• " + flat})
            elif re.fullmatch(r"\[.*\]", p["text"].strip()):
                sec["blocks"].append({"type": "cite", "text": flat})  # a quotation's source: "[Letter to Balai, 21 July 1969]"
            elif italic and indent_band(p["x0"], margin, p.get("spaced")) == 2:
                sec["blocks"].append({"type": "quote", "lines": [re.sub(r"<[^>]+>", "", ln).strip() for ln in text.split("\n") if ln.strip()]})
            elif indent_band(p["x0"], margin, p.get("spaced")) == 2:
                sec["blocks"].append({"type": "blockquote", "text": flat})
            elif meta.get("small_quotes") and small_print(p):
                sec["blocks"].append({"type": "blockquote", "text": flat})  # "small_quotes": a quotation set a size smaller than the body, hardly indented (The Qualities of Śrī Kṛṣṇa)
            else:
                sec["blocks"].append({"type": "p", "text": flat})
        if meta.get("no_title_block") and sec["blocks"][:1] and sec["blocks"][0]["type"] == "h":
            first = re.sub(r"\W", "", re.sub(r"<[^>]+>", "", sec["blocks"][0]["text"]).lower())
            if difflib.SequenceMatcher(None, first, re.sub(r"\W", "", sec["title"].lower())).ratio() >= 0.8:
                sec["blocks"].pop(0)  # the printed title, set a little differently from ours
        if meta.get("chapter_subtitles") and sec["kind"] == "chapter" and not sec["subtitle"] and sec["blocks"][:1] and sec["blocks"][0]["type"] == "centred" and len(sec["blocks"][0]["lines"]) == 1:
            sec["blocks"][0] = {"type": "h", "text": re.sub(r"<[^>]+>", "", sec["blocks"][0]["lines"][0])}  # a lone centred line under the title is its subtitle
        if meta.get("chapter_subtitles") and sec["kind"] == "chapter" and not sec["subtitle"] and sec["blocks"][:1] and sec["blocks"][0]["type"] == "h":
            first = re.sub(r"</?b>", "", sec["blocks"][0]["text"]).strip()
            if first.isupper():  # "SACRED MARRIAGE" under the chapter's name: its subtitle
                sec["subtitle"] = first.title()
                sec["blocks"].pop(0)
        # A story number printed on its own line ("1." from Word's list numbering) and its title set as a centred line: one heading "1. Title", as the book's other stories are
        merged = []
        for blk in sec["blocks"]:
            prev = merged[-1] if merged else None
            title_lines = blk.get("lines") if blk["type"] in ("quote", "centred") else [blk.get("text", "")] if blk["type"] in ("p", "h") else None
            if prev and prev["type"] in ("p", "h") and re.fullmatch(r"\d+\.[\s​]*", re.sub(r"<[^>]+>", "", prev.get("text", ""))) and title_lines and len(title_lines) <= 2 and len(" ".join(title_lines)) < 90:
                merged[-1] = {"type": "h", "text": re.sub(r"<[^>]+>", "", prev["text"]).strip() + " " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", " ".join(title_lines))).strip()}
                continue
            merged.append(blk)
        sec["blocks"] = merged
        # A paragraph cut by a picture or a page break ("There was this" / picture / "burden of karma…") is one paragraph again:
        # a plain paragraph that opens lowercase joins the earlier plain paragraph that stopped mid-sentence
        sec["blocks"] = join_cut_paragraphs(sec["blocks"])
        sec["blocks"] = [{k: v for k, v in b.items() if k != "top"} for b in merge_tables(sec["blocks"])]
        sections.append(sec)

    if meta.get("restore_r_dot"):  # the same ṛ repair as the OCR route: a word whose r → ṛ twin the book itself prints elsewhere gets its dot back
        from assemble_prose import restore_r_dot
        slots = [(sec, key) for sec in sections for key in ("title", "subtitle")]
        for sec in sections:
            for b in sec["blocks"]:
                slots += [(b, "text")] if isinstance(b.get("text"), str) else []
                slots += [(b["lines"], i) for i in range(len(b["lines"]))] if isinstance(b.get("lines"), list) else []
        slots = [(c, k) for c, k in slots if isinstance(c[k], str)]
        pseudo = [{"text": c[k]} for c, k in slots]
        print(restore_r_dot(pseudo)[0])
        for (c, k), p in zip(slots, pseudo):
            c[k] = p["text"]
    apply_fixes(sections, meta)
    for sec in sections:
        # A paragraph opening with a drop cap is indented beside the letter, so its first lines read as an inset block ("After about two weeks
        # of serving remotely, we" / "received the news…"): an unfinished inset followed by a lowercase paragraph is one paragraph
        joined = []
        for blk in sec["blocks"]:
            prev = joined[-1] if joined else None
            if (prev and prev["type"] == "blockquote" and blk["type"] == "p" and re.match(r"(?:<[^>]+>)*[a-z]", blk["text"])
                    and not re.sub(r"<[^>]+>", "", prev["text"]).rstrip().endswith((".", "!", "?", "”", '"', ":", ";"))):
                joined[-1] = {**blk, "text": prev["text"].rstrip() + " " + blk["text"].lstrip()}
                continue
            joined.append(blk)
        sec["blocks"] = join_cut_paragraphs(joined)  # a fix may leave a paragraph cut mid-sentence
    for sec in sections:  # a list the PDF stores as one paragraph ("Specifics: • one … • two …"): every bullet is its own paragraph
        listed = []
        for blk in sec["blocks"]:
            if blk["type"] == "p" and len(re.findall(r"(?:^|\s)•\s", blk["text"])) >= 2:
                listed += [{**blk, "text": part.strip()} for part in re.split(r"\s+(?=•\s)", blk["text"]) if part.strip()]
            else:
                listed.append(blk)
        sec["blocks"] = listed
    if meta.get("tidy"):  # "tidy": true — verses, translations, subheadings, signatures, capital openings, breaks (book_tidy.py)
        tidy_sections(sections, meta)
    if meta.get("drop_headings"):  # headings left out by hand, as in the OCR route (an editor's note printed as a heading: "BOX NEEDED")
        for sec in sections:
            sec["blocks"] = [b for b in sec["blocks"] if not (b["type"] == "h" and re.sub(r"<[^>]+>", "", b.get("text", "")).strip() in meta["drop_headings"])]
    line_settings(sections, meta)
    for sec in sections:  # a translation cut off its verse block joins its continuation ("…common men follow in" / "his footsteps…")
        sec["blocks"] = join_cut_paragraphs(sec["blocks"])
        # A heading is set bold by the design: its own <b> tags only make it patchy where a diacritic's font is not flagged bold
        # ("<b>N</b>ā<b>rada Muni</b>" — Gaurāṅga), in the heading and in the contents; italics stay
        for blk in sec["blocks"]:
            if blk["type"] == "h":
                blk["text"] = re.sub(r"\s+", " ", re.sub(r"</?b>", "", blk["text"])).strip()
    for sec in sections:
        if re.match(r"\W*(dedicat|invocation)", sec["title"], re.I):  # (a section that IS the dedication or invocation — not a chapter about one)
            # A dedication or invocation is set centred: its lines printed larger (small capitals) read as headings, but are its text
            sec["blocks"] = [{"type": "centred", "lines": [b["text"]]} if b["type"] == "h" else b for b in sec["blocks"]]
            sec["blocks"] = tidy_dedication(sec["blocks"])

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
