# manual/pipeline/epub_to_book.py
# Stage 2 for books whose only source is an EPUB we made ourselves with book_to_epub.py (the Mac-era books, 2026-11-10: their scans are gone).
# Reads the EPUB's own markup back into workspace/<book>/2-assembled/book.json — sections, block types, <i>/<b>/<sup> — and puts its pictures
# and cover in workspace/<book>/source/, so typeset_book.py and book_to_epub.py can build a fresh PDF and EPUB from it.
# Usage: poetry run python manual/pipeline/epub_to_book.py <path/to/book.epub> --library <path/to/book-library>

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import html
import json
import re
import zipfile

from pdf_to_book import apply_fixes, join_cut_paragraphs, line_settings, strip_text

# Our EPUB's spelled-out labels ("BOOK ONE", "PART TWO") → the number words used in a part's subtitle
WORDS = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE"]
BLOCK_RE = re.compile(r"<(p|h1|h2|div|table|blockquote|nav|ol)\b([^>]*)>(.*?)</\1>", re.S)


def inline(fragment: str) -> str:
    """Inner XHTML → book.json text: <i>, <b> and <sup> kept, <br/> as a line break, other tags dropped, entities decoded."""
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = re.sub(r"<(?!/?(?:i|b|sup)>)[^>]+>", "", text)
    return html.unescape(re.sub(r"[ \t\r]*\n[ \t\r]*", "\n", re.sub(r"[ \t\r]+", " ", text))).strip()


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def blocks_of(body: str, zf: zipfile.ZipFile, folder: str, pictures: dict) -> tuple[list, dict]:
    """The body's elements in order → book.json blocks; also the section's label (<p class="label">), h1 and subtitle (<p class="sub">)."""
    head, blocks = {}, []
    for tag, attrs, inner in BLOCK_RE.findall(body):
        cls = (re.search(r'class="([^"]+)"', attrs) or [None, ""])[1]
        if tag == "h1":
            head["title"] = plain(inline(inner))
        elif tag == "p" and cls in ("label", "sub"):
            head[cls] = plain(inline(inner))
        elif tag == "h2":
            blocks.append({"type": "h", "text": plain(inline(inner))})
        elif tag == "div" and "figure" in cls:
            src = re.search(r'<img[^>]*src="([^"]+)"', inner)[1]
            name = src.split("/")[-1]
            pictures[name] = zf.read(f"{folder}{src}")
            caption = re.search(r"<p[^>]*>(.*?)</p>", inner, re.S)
            blocks.append({"type": "figure", "file": name, "caption": inline(caption[1]) if caption else ""})
        elif tag == "table":
            rows = []
            for row in re.findall(r"<tr>(.*?)</tr>", inner, re.S):
                cells = re.findall(r"<t([dh])([^>]*)>(.*?)</t[dh]>", row, re.S)
                if len(cells) == 1 and cells[0][0] == "h":  # the table's own title row: written back the way book_to_epub reads it
                    span = int((re.search(r'colspan="(\d+)"', cells[0][1]) or [0, 2])[1])
                    rows.append(["", inline(cells[0][2])] + [""] * (span - 2))
                else:
                    rows.append([inline(c[2]) for c in cells])
            blocks.append({"type": "table", "rows": rows})
        elif tag == "blockquote":
            blocks.append({"type": "blockquote", "text": inline(re.sub(r"</?p[^>]*>", "", inner))})
        elif tag == "p" and cls in ("", "first") and re.search(r"\S {3,}\S", inner):
            # Items an older build ran into one paragraph, still apart by a run of spaces (a timeline: "…program.    October Giriraj…"): one paragraph each
            blocks += [{"type": "entry", "text": inline(part)} for part in re.split(r"(?<=\S) {3,}(?=\S)", inner) if inline(part)]
        elif tag == "p":
            text = inline(inner)
            if cls == "verse":
                blocks.append({"type": "quote", "lines": [plain(l) for l in text.split("\n") if plain(l)]})
            elif cls == "centre":
                blocks.append({"type": "centred", "lines": [l.strip() for l in text.split("\n") if l.strip()]})
            elif cls == "break":
                blocks.append({"type": "break"})
            elif cls == "notes-h":
                blocks.append({"type": "notes-h", "text": "Notes"})  # (as assemble_prose writes it)
            elif cls == "sign" and re.match(r"—\s*[a-z]", text) and blocks and blocks[-1]["type"] == "p" and len(plain(blocks[-1]["text"]).split()) <= 4:
                # A term's gloss taken for a signature ("abhaya-caraṇāravinda" / "— the lotus feet which make one fearless"): one line again
                blocks[-1]["text"] += " " + text
            elif cls == "sign":
                blocks.append({"type": "sign", "text": re.sub(r"^—\s*", "", text)})
            elif cls in ("cite", "epigraph", "entry", "note"):
                blocks.append({"type": cls, "text": text.replace("\n", " ")})
            else:  # "first" and plain paragraphs: the typesetter decides the indent
                blocks.append({"type": "p", "text": text.replace("\n", " ")})
    return blocks, head


def convert(epub_path) -> None:
    book = epub_path.stem
    meta = json.loads(local_env.META_FILE.read_text(encoding="utf-8")).get(book, {})
    zf = zipfile.ZipFile(epub_path)
    opf_name = re.search(r'full-path="([^"]+)"', zf.read("META-INF/container.xml").decode())[1]
    folder = opf_name.rsplit("/", 1)[0] + "/" if "/" in opf_name else ""
    opf = zf.read(opf_name).decode()
    hrefs = dict(re.findall(r'<item id="([^"]+)" href="([^"]+)"', opf))
    source = local_env.WORKSPACE_DIR / book / "source"
    pictures: dict[str, bytes] = {}
    sections, dropped = [], []
    for n, idref in enumerate(re.findall(r'<itemref idref="([^"]+)"', opf)):
        if not re.match(r"(front|chapter)-\d+$", idref):  # cover, title page and nav are made afresh by the typesetter
            continue
        page = zf.read(folder + hrefs[idref]).decode()
        blocks, head = blocks_of(page[page.find("<body"):], zf, folder, pictures)
        title, label = head.get("title", ""), head.get("label", "")
        sec = {"title": title, "subtitle": head.get("sub", ""), "numeral": "", "cover": None, "footnotes": [], "blocks": blocks, "start_page": n + 1}
        if idref.startswith("front"):
            sec["kind"] = "front"
        elif m := re.fullmatch(r"(?:BOOK|PART)\s+(\w+)", label):
            # A Part page ("BOOK ONE" over its name): "Part One" above the title, as Devansh asked for every Part (2026-11-10)
            word = m[1].title() if m[1] in WORDS else m[1]
            sec.update(kind="part", subtitle=f"Part {word}")
        elif label.startswith("CHAPTER"):
            sec["kind"] = "chapter"
        else:
            sec["kind"] = "back"  # Epilogue, appendices, notes: no chapter number
        # The section's own title repeated as its first paragraph (Book One printed "From the Mystic West 1967–68" twice): the big title stays
        if blocks and blocks[0]["type"] == "p" and plain(blocks[0]["text"]).lower() == title.lower():
            dropped.append(title)
            blocks.pop(0)
        sections.append(sec)
    source.mkdir(parents=True, exist_ok=True)
    for name, data in pictures.items():
        (source / "images").mkdir(exist_ok=True)
        (source / "images" / name).write_bytes(data)
    for sec in sections:  # figures point at their extracted file (absolute, so every stage finds it)
        for b in sec["blocks"]:
            if b["type"] == "figure":
                b["file"] = str((source / "images" / b["file"]).resolve())
    cover = re.search(r'<item id="([^"]+)" href="([^"]+)"[^>]*properties="cover-image"', opf)
    if cover:
        (source / ("cover." + cover[2].rsplit(".", 1)[-1])).write_bytes(zf.read(folder + cover[2]))
    strip_text(sections, meta.get("strip_text", []))  # before joining: a paragraph cut by a stripped border line is joined again
    joined = 0
    for sec in sections:  # a paragraph or quotation an older build cut at a page turn ("…the Supreme Personality" / "of Godhead by…") is whole again
        before = len(sec["blocks"])
        sec["blocks"] = join_cut_paragraphs(sec["blocks"])
        joined += before - len(sec["blocks"])
    print(f"cut paragraphs joined: {joined}")
    apply_fixes(sections, meta)  # book_meta.json text_fixes / regex_fixes, as in the digital route
    line_settings(sections, meta)  # split_before, heading_patterns, right_lines, normal_case_openings
    out_dir = local_env.stage_dir(book, "assembled")
    (out_dir / "book.json").write_text(json.dumps({"book": book, "layout": "prose", "sections": sections}, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds = {k: sum(s["kind"] == k for s in sections) for k in ("front", "part", "chapter", "back")}
    report = [f"Source: our own EPUB ({epub_path.name}) — no OCR", f"Sections: {kinds}", f"Pictures: {len(pictures)}"]
    report += [f"Repeated title dropped: {t}" for t in dropped]
    report += [f"{s['kind']:8} {s['subtitle'] + ': ' if s['kind'] == 'part' else ''}{s['title']} — {len(s['blocks'])} blocks" for s in sections]
    (out_dir / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[:3 + len(dropped)]))
    print(f"Wrote {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(local_env.USAGE)
    for path in map(local_env.book_path, sys.argv[1:]):
        convert(path)
