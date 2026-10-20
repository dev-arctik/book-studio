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

import pdf_text
from pdf_text import balaram_fonts, body_metrics, indent_band, page_lines, paragraphs, running_heads

META_FILE = local_env.META_FILE
SKIP_SECTIONS = {"title page", "copyright", "contents", "table of contents"}  # we build our own title page and contents
TABLE_SIZE = 0.7  # lines printed smaller than this × body size are table text (small caps opening a section are bigger)
ROW_GAP = 10  # pt — table lines further apart than this start a new row (lines inside one cell sit ~7.5 pt apart)
COLUMN_GAP = 20  # pt — line starts further apart than this belong to different columns
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
    # A decorated initial ("W" set large) belongs at the start of the line beside it ("HEN I FIRST JOINED…"); that first line,
    # set in small capitals, is body text
    for drop in [l for l in lines if len(l["text"]) == 1 and l["size"] >= 2 * body]:
        beside = [l for l in lines if l is not drop and l["x0"] > drop["x0"] and abs(l["y"] - drop["y"]) < max(3, 0.5 * drop["size"])]  # a tall cap starts above its line
        if beside:
            beside[0]["spans"][0] = {**beside[0]["spans"][0], "text": drop["text"] + beside[0]["spans"][0]["text"]}
            beside[0]["text"] = drop["text"] + beside[0]["text"]
            beside[0]["size"] = body
            # the lines wrapped around the cap start further in than the paragraph does: put them back at the cap's own margin
            for l in lines:
                if l is not drop and l["x0"] > drop["x0"] and 0 <= l["y"] - drop["y"] < drop["size"]:
                    l["x0"] = drop["x0"]
            lines.remove(drop)
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
            # A picture drawn twice, a hair apart (a shadow or a mask beside it), is one picture
            same = [o for o in items if "object" in o and o["object"]["type"] == "figure" and abs(o["object"]["bbox"][0] - x0) < 4 and abs(o["object"]["bbox"][1] - y0) < 4]
            if same:
                continue
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
    kind = "front" if first in ("foreword", "introduction", "dedication", "preface", "acknowledgements", "acknowledgments", "maṅgalācaraṇa") else "back"
    return {"kind": kind, "title": title, "start_page": page}


LABEL_RE = re.compile(r"^chapter\s+[\w-]+$", re.I)  # "Chapter One": a label that has its own outline entry before the real title
FRONT_LABELS = ("foreword", "introduction", "preface")


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
    """A plain paragraph that opens lowercase joins the earlier plain paragraph that stopped mid-sentence (pictures and tables between them do not matter)."""
    joined, last_p = [], None
    for blk in blocks:
        if blk["type"] == "p" and last_p is not None and blk["text"][:1].islower() and not re.search(r"[.!?:;”’)\]>]\s*$", last_p["text"]):
            last_p["text"] += " " + blk["text"]
            continue
        joined.append(blk)
        if blk["type"] == "p":
            last_p = blk
        elif blk["type"] not in ("figure", "table"):
            last_p = None
    return joined


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
    pdf_text.DROP_FONTS = tuple(meta.get("drop_fonts", []))  # decoration set in its own font (a faded mantra behind the text)
    global BULLET_MIN_SIZE
    BULLET_MIN_SIZE = meta.get("bullet_min_size", 0)
    pdf_text.BALARAM_FONTS = balaram_fonts(pdf)  # fonts holding Balaram-style stand-in letters are decoded, whatever their name
    if meta.get("bold_paragraph_pages"):  # [first, last] scan pages of a glossary: each bold term opens an entry
        first_pg, last_pg = meta["bold_paragraph_pages"]
        pdf_text.BOLD_PARA_PAGES = set(range(first_pg - 1, last_pg))
    pdf_text.FIRST_INDENT_MAX = meta.get("first_indent_max", pdf_text.FIRST_INDENT_MAX)
    pdf_text.DROP_LINES = meta.get("drop_lines", [])
    pdf_text.BULLET_FONTS = tuple(meta.get("bullet_fonts", []))
    pdf_text.PAGE_NUMBER_BAND = meta.get("page_number_band", pdf_text.PAGE_NUMBER_BAND)
    pdf_text.NUMBERED_ITEMS = bool(meta.get("numbered_items"))
    if meta.get("mirrored_pages"):  # facing pages with mirrored margins: align each page's margin before measuring indents
        pdf_text.PAGE_SHIFT = pdf_text.page_shifts(pdf)
    outline = clean_outline([(t.strip(), p) for level, t, p in pdf.get_toc() if level == 1])
    if not outline and meta.get("sections"):  # "sections": [["1: Title", first PDF page], …] — for a digital PDF without an outline (the chapters are found on its pages)
        outline = [(e[0], e[1], "", "") for e in meta["sections"]]  # an entry may add a third item: the text its section begins with (several sections share a page)
    markers = [e[2] if len(e) > 2 else "" for e in meta["sections"]] if outline and meta.get("sections") and not pdf.get_toc() else []
    pdf_text.RUNNING_HEADS = running_heads(pdf)  # the book's own running heads are dropped from its text
    body, pitch, right = body_metrics([page_lines(p) for p in pdf])
    if meta.get("normalise_sizes"):  # chapters with their own body size (17 pt, 14 pt…): every page is scaled to the book's most common size
        pdf_text.PAGE_SCALE = pdf_text.page_scales(pdf, body)
        body, pitch, right = body_metrics([page_lines(p) for p in pdf])
    # The body's left edge, for this book's first-line indents (paragraphs are not separated by a gap)
    starts = Counter(round(l["x0"]) for p in pdf for l in page_lines(p) if l["size"] == body)
    margin = starts.most_common(1)[0][0]
    first_lines = [x for x in starts if indent_band(x, margin) == 1]
    # The usual first-line indent; a book with none separates paragraphs by a gap, so the gaps alone split it
    indent = max(first_lines, key=lambda x: starts[x]) if first_lines else None
    paras = paragraphs([page_items(p, body, margin) for p in pdf], body, pitch, right, margin if indent is not None else None, indent)

    # Per-book settings (book_meta.json): "drop_sections" — outline titles left out (a page-number index means nothing once the
    # book is reflowed); "skip_pages" — scan pages left out (the publisher's back cover)
    front_titles = {t.lower() for t in meta.get("front_sections", [])}
    skip_titles = SKIP_SECTIONS | {t.lower() for t in meta.get("drop_sections", [])}
    skip_pages = set(meta.get("skip_pages", []))
    paras = [p for p in paras if p["page"] + 1 not in skip_pages]
    # "skip_pictures": pages whose pictures are decoration (a page-sized faded overlay) — the text stays. "picture_pages": pages set
    # as one full-width picture, whatever else is on them (a full-page painting that opens a part)
    skip_pictures, picture_pages = set(meta.get("skip_pictures", [])), sorted(meta.get("picture_pages", []))
    paras = [p for p in paras if not (p["kind"] == "object" and p["object"]["type"] == "figure" and p["page"] + 1 in skip_pictures)]
    if picture_pages:
        paras = [p for p in paras if p["page"] + 1 not in picture_pages]
        for pg in picture_pages:
            w, h = pdf[pg - 1].rect.width, pdf[pg - 1].rect.height
            paras.append({"kind": "object", "runs": [], "text": "", "page": pg - 1, "object": {
                "type": "figure", "page": pg, "bbox": [0, 0, w, h], "image_bbox": [0, 0, w, h], "caption": "", "wide": True}})
        paras.sort(key=lambda p: p["page"])  # a stable sort: the order within a page is kept

    sections = []
    # Sections that begin mid-page: each starts at the paragraph opening with its marker (else at its page's first paragraph) and runs to the next one's start
    cuts = []
    if any(markers):
        for (_, page, _, _), mark in zip(outline, markers):
            cuts.append(next((k for k, p in enumerate(paras) if p["page"] + 1 >= page and (not mark or p["page"] + 1 == page and re.sub(r"\s+", " ", p["text"]).lstrip().startswith(mark))), len(paras)))
    for i, (title, page, kind, lead) in enumerate(outline):
        end = outline[i + 1][1] if i + 1 < len(outline) else len(pdf) + 1
        if title.lower() in skip_titles:
            continue
        sec = {**section_of(title, page), "subtitle": "", "cover": None, "numeral": "", "footnotes": [], "blocks": []}
        if title.lower() in front_titles:
            sec["kind"] = "front"  # book_meta.json "front_sections": titles that open the book (about the author, dedication, how to use it…)
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
        enlarged = lambda p: (sec["kind"] != "front" and p["kind"] == "p" and abs((p["x0"] + p.get("x1", 0)) / 2 - centre) < 8 and p["runs"]  # noqa: E731
                              and all(r.get("break") or not r["text"].strip() or r["size"] >= body + 0.9 for r in p["runs"]))
        if cuts and markers[i] and mine and mine[0]["text"].strip() == markers[i]:
            mine.pop(0)  # the heading line that opens the section repeats its title
        popped = []
        while not meta.get("no_title_block") and mine and (mine[0]["kind"] not in ("p", "object") or enlarged(mine[0])):  # "no_title_block": chapters start straight with their first story, no title page
            head = mine.pop(0)
            popped.append(re.sub(r"\s+", " ", " ".join(r["text"].strip() for r in head["runs"] if not r.get("break"))).strip())
            author = " ".join(r["text"].strip() for r in head["runs"] if not r.get("break") and r.get("italic") and r["text"].strip())
            if author:
                sec["subtitle"] = re.sub(r"\s+", " ", author)
        popped = [re.sub(r"(?<=\w) ’ (?=\w)", "’", re.sub(r"“ | ”", lambda m: m.group().strip(), p)).replace(" – ", "–") for p in popped]  # Word's loose spacing around quotes and dashes
        dated = next((j for j, p in enumerate(popped) if j >= 2 and re.search(r"\b(1[89]\d\d|20\d\d)\b|\d0’?s\b", p)), None)
        if not sec["subtitle"] and popped and re.fullmatch(r"chapter\s+\d+", popped[0], re.I) and dated:  # "CHAPTER 8" / title / "VRINDAVAN 1973–1974" / first heading
            sec["subtitle"] = popped[dated]
            sec["blocks"] += [{"type": "h", "text": p} for p in popped[dated + 1:]]  # lines after the place and date open the chapter's text
        elif not sec["subtitle"] and len(popped) >= 3:  # "Chapter One" / "Nāma-Aparādha" / "The Ten Offences…": the last line is the subtitle
            last = popped[-1]
            same_as_title = re.sub(r"\W", "", last.lower()) == re.sub(r"\W", "", sec["title"].lower())
            if last and not same_as_title and not LABEL_RE.match(last) and not re.fullmatch(r"part\s+\w+", last, re.I):
                sec["subtitle"] = last
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
            flat = re.sub(r"(?<=\S) {2,}", " ", text.replace("\n", " "))  # Word text carries doubled spaces
            words = [r for r in p["runs"] if not r.get("break") and r["text"].strip()]
            italic = bool(words) and all(r["italic"] for r in words)
            caps_heading = len(p["text"]) < 60 and p["text"].isupper() and len(p["text"].split()) <= 6 and sum(c.isalpha() for c in p["text"]) >= 6  # "FINANCIAL", "HEALTH": a typed-up book's subheading
            if p["kind"] != "p" or caps_heading or (sec["title"] == "Notes" and re.fullmatch(r"(Foreword|Introduction|Chapter \d+|Concluding Words)", p["text"])):
                if re.sub(r"\W", "", flat.lower()) != re.sub(r"\W", "", sec["title"].lower()):  # (not the section's own title again)
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
        # A paragraph cut by a picture or a page break ("There was this" / picture / "burden of karma…") is one paragraph again:
        # a plain paragraph that opens lowercase joins the earlier plain paragraph that stopped mid-sentence
        sec["blocks"] = join_cut_paragraphs(sec["blocks"])
        sec["blocks"] = [{k: v for k, v in b.items() if k != "top"} for b in merge_tables(sec["blocks"])]
        sections.append(sec)

    apply_fixes(sections, meta)
    for sec in sections:
        sec["blocks"] = join_cut_paragraphs(sec["blocks"])  # a fix may leave a paragraph cut mid-sentence

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
