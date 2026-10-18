# manual/pipeline/book_to_epub.py
# Turns one of our processed books (output/<book>/2-assembled/book.json) into an EPUB for Kindle and other e-readers:
# books/final/<book>_en.epub, with the same chapters, quotations, notes and photos (with captions) as its PDF.
# Reuses typeset_book.py's conversion and picture cropping, so the e-book and the PDF can't drift apart; packaging is epub_pack.py.
# Usage: poetry run python pipeline/book_to_epub.py a-spiritual-journey

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import html
import re
import shutil

from epub_pack import cover_jpeg, title_page, write_epub, xhtml
from typeset_book import build_typst_data


def rich(segs: list[dict]) -> str:
    """Template text segments [{t, i, b, sup}] → inline XHTML, emphasis and footnote markers kept."""
    out = []
    for s in segs:
        t = html.escape(s["t"]).replace("\n", " ")
        if s.get("i"):
            t = f"<i>{t}</i>"
        if s.get("b"):
            t = f"<b>{t}</b>"
        if s.get("sup"):
            t = f"<sup>{t}</sup>"
        out.append(t)
    return re.sub(r"</i><i>|</b><b>", "", "".join(out)).strip()


class Pictures:
    """Collects the cropped figures for the EPUB's images/ folder."""

    def __init__(self):
        self.files = {}

    def add(self, fig: dict) -> str:
        name = f"images/figure-{len(self.files) + 1:03d}.jpg"
        self.files[name] = (local_env.PROJECT_ROOT / fig["path"].lstrip("/")).read_bytes()
        return name


def figure_html(fig: dict, pictures: Pictures) -> str:
    caption = f"<p>{rich(fig['caption'])}</p>" if fig.get("caption") else ""
    return f'<div class="figure"><img src="{pictures.add(fig)}" alt=""/>{caption}</div>'


def blocks_html(blocks: list[dict], pictures: Pictures) -> str:
    """Each template block type as the e-book equivalent of its look in book_template.typ."""
    out = []
    for b in blocks:
        kind = b["type"]
        if kind == "p":
            out.append(f"<p>{rich(b['segs'])}</p>" if b["indent"] else f'<p class="first">{rich(b["segs"])}</p>')
        elif kind == "quote":
            out.append('<p class="verse">' + "<br/>".join(html.escape(l) for l in b["lines"]) + "</p>")
        elif kind == "blockquote":
            out.append(f"<blockquote><p>{rich(b['segs'])}</p></blockquote>")
        elif kind == "epigraph":
            out.append(f'<p class="epigraph">{rich(b["segs"])}</p>')
        elif kind in ("cite", "sign-detail"):
            out.append(f'<p class="cite">{rich(b["segs"])}</p>')
        elif kind == "sign":
            out.append(f'<p class="sign">— {rich(b["segs"])}</p>')
        elif kind == "figure":
            out.append(figure_html(b, pictures))
        elif kind == "h":
            out.append(f"<h2>{rich(b['segs'])}</h2>")
        elif kind == "break":
            out.append('<p class="break">* * *</p>')
        elif kind == "centred":
            out.append('<p class="centre">' + "<br/>".join(rich(l) for l in b["lines"]) + "</p>")
        elif kind == "table":
            rows, n = [], len(b["rows"][0])
            for row in b["rows"]:
                filled = [c for c in row if c]
                if len(filled) == 1 and n > 1 and not row[0]:  # the table's own title row
                    rows.append(f'<tr><th colspan="{n}">{rich(filled[0])}</th></tr>')
                else:
                    rows.append("<tr>" + "".join(f"<td>{rich(c)}</td>" for c in row) + "</tr>")
            out.append('<table class="book">' + "".join(rows) + "</table>")
        elif kind == "notes-h":
            out.append('<p class="notes-h">NOTES</p>')
        elif kind == "entry":
            out.append(f'<p class="entry">{rich(b["segs"])}</p>')
        elif kind == "note":
            out.append(f'<p class="note">{rich(b["segs"])}</p>')
        else:
            raise ValueError(f"no e-book layout for block type {kind!r}")
    return "\n".join(out)


def verses_html(verses: list[dict]) -> str:
    """Verse anthologies (Padyāvalī), as in the PDF: verse number, centred italic Sanskrit, word-for-word with the Sanskrit
    words in bold, translation(s), then the poet."""
    out = []
    for vs in verses:
        out.append(f'<p class="label">VERSE {vs["number"]}</p>')
        out.append('<p class="verse">' + "<br/>".join(html.escape(l) for l in vs["sanskrit"]) + "</p>")
        if vs["word_for_word"]:
            out.append(f'<p class="wfw">{rich(vs["word_for_word"])}</p>')
        for tr in vs["translations"]:
            if tr["label"]:
                out.append(f'<p class="tr-label">{html.escape(tr["label"])}</p>')
            out += [f'<p class="first">{rich(p)}</p>' for p in tr["paragraphs"]]
        if vs["poet"]:
            out.append(f'<p class="sign">— {html.escape(vs["poet"])}</p>')
        out += [f'<p class="note">{rich(n)}</p>' for n in vs["notes"]]
    return "\n".join(out)


def convert(book: str) -> None:
    book = local_env.find_book(book).stem
    build_dir = local_env.stage_dir(book, "clean-pdf") / ".build"
    build_dir.mkdir(exist_ok=True)
    try:
        data = build_typst_data(book, build_dir)  # crops every figure into build_dir, exactly as for the PDF
        meta, pictures = data["meta"], Pictures()
        docs = [("title", meta["title"], title_page(meta["title"], meta["subtitle"], meta["author"], meta.get("copyright", "")))]
        if data["frontispiece"]:
            docs.append(("frontispiece", "Frontispiece", xhtml(meta["title"], "\n".join(figure_html(f, pictures) for f in data["frontispiece"]))))
        for i, sec in enumerate(data["front"], 1):
            docs.append((f"front-{i:02d}", sec["title"], xhtml(sec["title"], f"<h1>{html.escape(sec['title'])}</h1>\n{blocks_html(sec['blocks'], pictures)}")))
        for i, ch in enumerate(data["chapters"], 1):
            label = f'<p class="label">CHAPTER {ch["number"]}</p>' if ch["number"] else ""
            if ch.get("part"):
                label = f'<p class="label">{html.escape(ch["subtitle"].upper())}</p>'
            sub = f'<p class="sub">{html.escape(ch["subtitle"])}</p>' if ch["subtitle"] and not ch.get("part") else ""
            cover = figure_html(ch["cover"], pictures) if ch.get("cover") else ""
            body = f"{label}<h1>{html.escape(ch['title'])}</h1>{sub}\n{cover}{blocks_html(ch['blocks'], pictures)}\n{verses_html(ch['verses'])}"
            name = f"{ch['number']}. {ch['title']}" if ch["number"] else ch["title"]
            docs.append((f"chapter-{i:02d}", name, xhtml(ch["title"], body)))
        out = local_env.FINAL_DIR / f"{book}_en.epub"
        write_epub(out, book, meta["title"], meta["author"], docs, cover_jpeg(local_env.find_book(book), meta),
                   {name: data for name, data in pictures.files.items()}, start="chapter-01")
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)  # cropped figures live on only inside the e-book
        if not any(build_dir.parent.iterdir()):
            build_dir.parent.rmdir()
    print(f"{out.name}: {len(docs) - 1} entries in the contents, {len(pictures.files)} pictures, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    for name in sys.argv[1:]:
        convert(name)
