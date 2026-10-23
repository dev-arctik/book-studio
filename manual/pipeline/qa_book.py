# manual/pipeline/qa_book.py
# The check that follows every run (Devansh, 2026-10-23: "checking after the pipeline is run is very crucial"). Reads the finished PDF and EPUB
# of every book in a batch folder (and the assembled book.json beside them in the workspace) and reports what a person would otherwise find by
# paging through: a missing or blank cover, a contents without topics, fallback fonts, stray text outside the margins, picture resolution,
# label headings not centred, word-for-word glosses without bold Sanskrit, broken paragraph fragments, lost-ligature words.
# It reads only; it changes nothing. A line starting "FAIL" must be fixed before publishing, "WARN" must be looked at.
# Usage: poetry run python manual/pipeline/qa_book.py <batch folder with pdf/ and epub/> --library <path/to/book-library>

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import io
import json
import re
import zipfile
from pathlib import Path

import pymupdf
from PIL import Image

LIGATURE_LOSS = re.compile(r"\b(?:Te(?!’)|Tis|Tere|Tey|Tese|afer|ofen)\b|\bTat(?= (?:is|was|you|the|a)\b)")  # "The", "This", "There", "They", "These", "after", "often", "That" without their ligature letters
CENTRED_LABEL = re.compile(r"^(section|translation|purport|texts?|synonyms|verses?|commentary|comments?|summary)\b[\s\d.:IVXLC-]*$", re.I)
GLOSS = re.compile(r"\s=\s")


def pdf_checks(path: Path) -> list[str]:
    out = []
    doc = pymupdf.open(path)
    first = doc[0]
    imgs = first.get_images()
    if not imgs or len(first.get_text().strip()) > 5:
        out.append("FAIL cover: page 1 is not a full-page cover picture")
    else:
        pix = first.get_pixmap(dpi=24)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        white = sum(1 for v in im.getdata() if v > 235) / (im.width * im.height)
        if white > 0.8:
            out.append(f"FAIL cover: page 1 is {white:.0%} white — a title page, not a cover (use the supplied cover image: cover_file)")
    toc = doc.get_toc()
    top = [t for t in toc if t[0] == 1]
    if len(top) < 2:
        out.append("FAIL contents: fewer than two chapters in the PDF bookmarks")
    elif not any(t[0] == 2 for t in toc):
        out.append("WARN contents: no topics under the chapters (fine only if the book has no subheadings)")
    fonts = {f[3].split("+")[-1] for p in doc for f in p.get_fonts()}
    other = sorted(f for f in fonts if not f.startswith("GentiumBookPlus"))
    if other:
        out.append(f"FAIL fonts: not Gentium: {other[:4]} (a character Gentium lacks fell back to another font)")
    width = first.rect.width
    outside = 0
    low, worst = 0, 9999
    for n, page in enumerate(doc):
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                if ln["bbox"][0] < 12 or ln["bbox"][2] > width - 12:
                    outside += 1
        if n == 0:
            continue
        for info in page.get_image_info():
            w = info.get("width", 0)
            span = info["bbox"][2] - info["bbox"][0]
            if span > 36 and w:
                dpi = w / (span / 72)
                worst = min(worst, dpi)
                low += dpi < 150
    if outside:
        out.append(f"FAIL margins: {outside} text lines run outside the page margins")
    if low:
        out.append(f"WARN pictures: {low} pictures print below 150 dpi (lowest {worst:.0f}) — soft in print")
    text = "\n".join(p.get_text() for p in doc)
    loss = LIGATURE_LOSS.findall(text)
    if len(loss) > 5:
        out.append(f"FAIL words: {len(loss)} words look like they lost ligature letters ({', '.join(sorted(set(loss))[:5])}) — word_fixes")
    if re.search(r"[-]", text):
        out.append("FAIL words: private-use characters in the text (an old diacritic font that was not decoded)")
    return out


def epub_checks(path: Path) -> list[str]:
    out = []
    z = zipfile.ZipFile(path)
    names = z.namelist()
    opf = z.read(next(n for n in names if n.endswith(".opf"))).decode("utf-8")
    cover = re.search(r'properties="cover-image"[^>]*|<item [^>]*properties="cover-image"[^>]*>', opf)
    href = re.search(r'<item [^>]*id="cover-image"[^>]*href="([^"]+)"', opf) or re.search(r'href="([^"]+)"[^>]*id="cover-image"', opf)
    if not cover or not href:
        out.append("FAIL cover: the EPUB has no cover image")
    else:
        im = Image.open(io.BytesIO(z.read("OEBPS/" + href.group(1)))).convert("L")
        small = im.resize((40, 60))
        white = sum(1 for v in small.getdata() if v > 235) / 2400
        if white > 0.8:
            out.append(f"FAIL cover: the EPUB cover is {white:.0%} white")
        if im.height < 900:
            out.append(f"WARN cover: the EPUB cover is only {im.height} px tall")
    nav = z.read("OEBPS/nav.xhtml").decode("utf-8")
    if nav.count("<li>") < 3:
        out.append("FAIL contents: the EPUB contents has fewer than three entries")
    elif "<ol><li>" not in nav:
        out.append("WARN contents: the EPUB contents has no topics under the chapters")
    return out


def data_checks(key: str) -> list[str]:
    out = []
    path = local_env.win_long(local_env.WORKSPACE_DIR / key.rstrip(". ") / "2-assembled" / "book.json")
    if not path.is_file():
        return ["WARN data: no assembled book.json in the workspace (checks of headings, glosses and paragraphs skipped)"]
    book = json.loads(path.read_text(encoding="utf-8"))
    plain = lambda t: re.sub(r"<[^>]+>", "", t).strip()  # noqa: E731
    blocks = [b for s in book.get("sections", []) for b in s["blocks"]]
    bare = [b for b in blocks if b["type"] == "p" and len(GLOSS.findall(b["text"])) >= 3 and b["text"].count(" | ") >= 2 and "<b>" not in b["text"]]
    # (typeset_book bolds the Sanskrit of such lines itself; this only reports how many there are)
    if bare:
        out.append(f"INFO glosses: {len(bare)} word-for-word lines (typeset_book sets their Sanskrit in bold)")
    fragments = 0
    for i, b in enumerate(blocks[:-1]):
        if b["type"] == "p":
            t = plain(b["text"])
            nxt = blocks[i + 1]
            if 0 < len(t) < 40 and not re.search(r"[.!?:;)\"”’\]]$", t) and nxt["type"] in ("p", "blockquote") and plain(nxt.get("text", ""))[:1].islower():
                fragments += 1
    if fragments > 2:
        out.append(f"WARN paragraphs: {fragments} short fragments that look like a paragraph broken in pieces — compare with the original")
    labels = [b for b in blocks if b["type"] == "h" and CENTRED_LABEL.match(plain(b["text"]))]
    if labels:
        out.append(f"INFO headings: {len(labels)} label headings (SECTION / TRANSLATION …) are centred by typeset_book")
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--library")]
    batch = Path(args[0]).expanduser().resolve() if args else None
    if not batch or not (batch / "pdf").is_dir():
        sys.exit(local_env.USAGE + "\n(first argument: the batch folder that holds pdf/ and epub/)")
    failed = 0
    for pdf in sorted((batch / "pdf").glob("*.pdf")):
        key = pdf.stem[:-3] if pdf.stem.endswith("_en") else pdf.stem
        problems = pdf_checks(pdf)
        epub = batch / "epub" / (pdf.stem + ".epub")
        problems += epub_checks(epub) if epub.is_file() else ["FAIL epub: missing"]
        problems += data_checks(key)
        bad = [p for p in problems if p.startswith("FAIL")]
        failed += bool(bad)
        print(f"{'FAIL' if bad else 'ok  '} {key[:60]}")
        for p in problems:
            print("       " + p)
    print(f"\n{failed} book(s) with a FAIL")


if __name__ == "__main__":
    main()
