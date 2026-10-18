# pipeline/pdf_to_epub.py
# Turns a finished, text-based book PDF (not a scan) into an EPUB e-book next to it: books/final/<book>.pdf → <book>.epub.
# Chapters come from the PDF's own outline and the cover from page 1. Text comes from pdf_text.py; the packaging (clickable
# contents, embedded Gentium) from epub_pack.py. Our processed books use book_to_epub.py instead (it keeps their photos).
# Usage: poetry run python pipeline/pdf_to_epub.py bhakti-bhava_en

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import html
import json
import re

import pymupdf

from epub_pack import cover_jpeg, title_page, write_epub, xhtml
from pdf_text import read_pdf

META_FILE = local_env.PIPELINE_DIR / "book_meta.json"
FRONT_SKIP_RE = re.compile(r"©|\bCopyright\b|\bISBN\b|All rights reserved", re.I)  # copyright pages stay out, as in our PDFs


def runs_html(para: dict, body: float) -> str:
    """A paragraph's runs as inline XHTML: italic/bold kept, deliberate line breaks kept, small print (audience remarks) smaller."""
    out = []
    for r in para["runs"]:
        if r.get("break"):
            out.append("<br/>")
            continue
        t = html.escape(r["text"])
        if r["italic"]:
            t = f"<i>{t}</i>"
        if r["bold"]:
            t = f"<b>{t}</b>"
        if r["size"] < 0.8 * body:
            t = f'<span class="small">{t}</span>'
        out.append(t)
    return re.sub(r"</i><i>|</b><b>", "", "".join(out)).strip()


def chapter_html(paras: list[dict], body: float) -> str:
    """Body of one chapter. Its printed title is left out (the <h1> replaces it); other large lines (a closing
    'Hare Kṛṣṇa. Thank you very much.', a bullet scene break) are set apart, centred; italic-only multi-line paragraphs are verses."""
    while paras and paras[0]["kind"] != "p":
        paras = paras[1:]
    out, after_break = [], True
    for p in paras:
        inner = runs_html(p, body)
        if not re.sub(r"<[^>]+>", "", inner).strip():
            continue
        text_runs = [r for r in p["runs"] if not r.get("break") and r["text"].strip()]
        if p["kind"] != "p":
            out.append(f'<p class="display">{inner}</p>')
            after_break = True
        elif text_runs and all(r["italic"] for r in text_runs) and any(r.get("break") for r in p["runs"]):
            out.append(f'<p class="verse">{inner}</p>')
            after_break = True
        else:
            out.append(f'<p class="first">{inner}</p>' if after_break else f"<p>{inner}</p>")
            after_break = False
    return "\n".join(out)


def convert(book: str) -> None:
    pdf_path = local_env.find_book(book)
    meta = json.loads(META_FILE.read_text(encoding="utf-8")).get(book, {})
    title, subtitle, author = meta.get("title", book), meta.get("subtitle", ""), meta.get("author", "")
    pdf = pymupdf.open(pdf_path)
    outline = [(t.strip(), page - 1) for level, t, page in pdf.get_toc() if level == 1]
    if not outline:
        sys.exit(f"{pdf_path.name} has no chapter outline — the clickable contents needs one")
    paras, body = read_pdf(pdf)

    # Front pages (before chapter 1): keep a dedication; skip the copyright page and the printed contents (the e-book has its own)
    toc_titles = {re.sub(r"\W", "", t.lower()) for t, _ in outline}
    front_pages = {}
    for p in paras:
        if p["page"] < outline[0][1]:
            front_pages.setdefault(p["page"], []).append(p)
    front = []
    for page, ps in sorted(front_pages.items()):
        text = " ".join(p["text"] for p in ps)
        listed = sum(re.sub(r"\W", "", p["text"].lower()) in toc_titles for p in ps)
        if FRONT_SKIP_RE.search(text) or listed >= 2:
            continue
        front += ps

    # Chapter i = paragraphs from its outline page up to the next chapter's page
    chapters = []
    for i, (name, start) in enumerate(outline):
        end = outline[i + 1][1] if i + 1 < len(outline) else len(pdf)
        chapters.append((name, [p for p in paras if start <= p["page"] < end]))

    docs = [("title", title, title_page(title, subtitle, author))]
    if front:
        docs.append(("dedication", "Dedication", xhtml("Dedication", '<div class="title">' + "\n".join(
            f'<p class="centre"><i>{runs_html(p, body)}</i></p>' for p in front) + "</div>")))
    for i, (name, ps) in enumerate(chapters, 1):
        docs.append((f"chapter-{i:02d}", name, xhtml(name, f"<h1>{html.escape(name)}</h1>\n{chapter_html(ps, body)}")))

    out = pdf_path.with_suffix(".epub")
    write_epub(out, book, title, author, docs, cover_jpeg(pdf_path))
    words = sum(len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", page))) for _, _, page in docs)
    print(f"{out.name}: {len(chapters)} chapters in the contents, {words} words, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    for name in sys.argv[1:]:
        convert(name)
