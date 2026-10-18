# manual/pipeline/epub_pack.py
# Shared EPUB 3 packaging for pdf_to_epub.py (text PDFs) and book_to_epub.py (our processed books): page template, stylesheet,
# and writing the .epub — clickable contents in both forms e-readers use (EPUB 3 nav + the older toc.ncx Kindle reads),
# the cover, images, and Gentium Book Plus embedded so every diacritic shows on any e-reader.

import html
import io
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import local_env
from figures import book_cover

COVER_HEIGHT = 1600  # px — sharp on Kindle screens without bloating the file
FONTS = {"regular": "GentiumBookPlus-Regular.ttf", "italic": "GentiumBookPlus-Italic.ttf",
         "bold": "GentiumBookPlus-Bold.ttf", "bolditalic": "GentiumBookPlus-BoldItalic.ttf"}

# Same look as the PDFs (book_template.typ): Gentium, brown accent, indented paragraphs, centred italic verses
CSS = """@font-face { font-family: "Gentium"; font-style: normal; font-weight: normal; src: url(fonts/GentiumBookPlus-Regular.ttf); }
@font-face { font-family: "Gentium"; font-style: italic; font-weight: normal; src: url(fonts/GentiumBookPlus-Italic.ttf); }
@font-face { font-family: "Gentium"; font-style: normal; font-weight: bold; src: url(fonts/GentiumBookPlus-Bold.ttf); }
@font-face { font-family: "Gentium"; font-style: italic; font-weight: bold; src: url(fonts/GentiumBookPlus-BoldItalic.ttf); }
body { font-family: "Gentium", serif; line-height: 1.45; }
h1 { color: #7a4a12; font-style: italic; font-weight: normal; text-align: center; margin: 0.4em 0 1.2em; }
h2 { color: #7a4a12; font-size: 1em; font-weight: bold; margin: 1.3em 0 0.5em; page-break-after: avoid; }
p.label { text-align: center; text-indent: 0; color: #6b6158; font-size: 0.8em; letter-spacing: 0.15em; margin-top: 2em; }
p.sub { text-align: center; text-indent: 0; color: #6b6158; margin: -0.8em 0 1.2em; }
p { margin: 0; text-indent: 1.3em; text-align: justify; }
p.first, p.display, p.centre { text-indent: 0; }
p.display { text-align: center; font-style: italic; margin: 1em 0; font-size: 1.15em; }
p.centre { text-align: center; margin: 0.5em 0; }
p.verse { text-indent: 0; text-align: center; font-style: italic; margin: 0.8em 0; }
p.cite { text-indent: 0; text-align: right; font-size: 0.85em; color: #6b6158; margin: 0.2em 0 0.9em; }
p.sign { text-indent: 0; text-align: right; font-style: italic; margin-top: 0.9em; }
p.break { text-indent: 0; text-align: center; color: #7a4a12; letter-spacing: 0.6em; margin: 1em 0; }
blockquote { margin: 0.9em 1.5em; font-size: 0.92em; }
blockquote p { text-indent: 0; margin-bottom: 0.4em; }
p.epigraph { text-indent: 0; font-style: italic; margin: 0.8em 1.5em 0.3em; font-size: 0.92em; }
p.entry { text-indent: -1.5em; margin: 0.3em 0 0.3em 1.5em; font-size: 0.92em; text-align: left; }
p.note { text-indent: 0; font-size: 0.8em; color: #6b6158; margin: 0.25em 0; }
p.wfw { text-indent: 0; font-size: 0.88em; margin: 0.6em 0; text-align: left; }
p.tr-label { text-indent: 0; font-size: 0.8em; color: #7a4a12; letter-spacing: 0.1em; margin-top: 0.8em; }
p.notes-h { text-indent: 0; font-size: 0.8em; color: #7a4a12; letter-spacing: 0.1em; margin-top: 2em; border-top: 1px solid #6b6158; padding-top: 0.3em; width: 30%; }
div.figure { text-align: center; margin: 1.2em 0; page-break-inside: avoid; }
div.figure img { max-width: 100%; max-height: 90vh; }
div.figure p { text-indent: 0; text-align: center; font-style: italic; font-size: 0.85em; color: #6b6158; margin-top: 0.4em; }
span.small { font-size: 0.8em; }
table.book { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.85em; }
table.book td, table.book th { border: 1px solid #6b6158; padding: 0.25em 0.4em; vertical-align: top; text-align: left; }
table.book th { color: #7a4a12; text-align: center; }
nav#toc ol { list-style: none; padding: 0; margin: 1em 0; }
nav#toc li { margin: 0.7em 0; }
nav#toc a { color: inherit; text-decoration: none; }
.title { text-align: center; margin-top: 30%; }
.title .name { font-size: 2.2em; font-style: italic; color: #7a4a12; }
.title .sub { font-size: 1.1em; color: #6b6158; margin-top: 0.5em; }
.title .author { font-size: 1.3em; margin-top: 2.5em; }
.copyright-page { text-align: center; font-size: 0.75em; color: #6b6158; margin-top: 40%; }
.copyright-page p { text-indent: 0; text-align: center; margin: 0 0 0.7em; }
"""


def xhtml(title: str, body: str) -> str:
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">\n<head><meta charset="utf-8"/>'
            f'<title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>\n<body>\n{body}\n</body>\n</html>\n')


def title_page(title: str, subtitle: str, author: str) -> str:
    return xhtml(title, f'<div class="title"><div class="name">{html.escape(title)}</div>'
                        f'<div class="sub">{html.escape(subtitle)}</div><div class="author">{html.escape(author)}</div></div>')


def cover_jpeg(pdf_path: Path, meta: dict | None = None) -> bytes:
    """The book's front cover (the chosen image, else page 1 of the PDF or scan) as a JPEG — the same picture the PDF opens with."""
    buf = io.BytesIO()
    book_cover(pdf_path, meta or {}, COVER_HEIGHT).save(buf, "JPEG", quality=85, optimize=True)
    return buf.getvalue()


def write_epub(out: Path, book: str, title: str, author: str, docs: list[tuple[str, str, str]], cover: bytes,
               images: dict[str, bytes] = None, start: str = "chapter-01") -> None:
    """docs: (id, contents label, XHTML) in reading order — every doc except the title page is listed in the clickable contents.
    images: {"images/figure-001.jpg": bytes} referenced by the docs."""
    images = images or {}
    book_id = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'iskcon-youth-forum/' + book)}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = "\n".join(f'<item id="{d}" href="{d}.xhtml" media-type="application/xhtml+xml"/>' for d, _, _ in docs)
    manifest += "\n" + "\n".join(f'<item id="font-{k}" href="fonts/{f}" media-type="font/ttf"/>' for k, f in FONTS.items())
    manifest += "".join(f'\n<item id="img-{i}" href="{p}" media-type="image/jpeg"/>' for i, p in enumerate(images, 1))
    # Reading order: cover, title page, then the clickable contents page (where a reader expects it), then the book
    spine = "\n".join(f'<itemref idref="{d}"/>' + ('\n<itemref idref="nav"/>' if d == "title" else "") for d, _, _ in docs)
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="en">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bookid">{book_id}</dc:identifier>
<dc:title>{html.escape(title)}</dc:title>
<dc:creator>{html.escape(author)}</dc:creator>
<dc:language>en</dc:language>
<meta property="dcterms:modified">{modified}</meta>
<meta name="cover" content="cover-image"/>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="css" href="style.css" media-type="text/css"/>
<item id="cover-image" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>
<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
{manifest}
</manifest>
<spine toc="ncx">
<itemref idref="cover"/>
{spine}
</spine>
<guide><reference type="toc" title="Contents" href="nav.xhtml"/><reference type="text" title="Start" href="{start}.xhtml"/></guide>
</package>
'''
    # The clickable contents: everything after the title page (the cover and title are reached by paging back)
    listed = [(d, t) for d, t, _ in docs if d != "title"]
    nav = xhtml("Contents", '<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>\n' + "\n".join(
        f'<li><a href="{d}.xhtml">{html.escape(t)}</a></li>' for d, t in listed) + "\n</ol></nav>\n"
        '<nav epub:type="landmarks" hidden=""><ol><li><a epub:type="toc" href="nav.xhtml">Contents</a></li>'
        f'<li><a epub:type="bodymatter" href="{start}.xhtml">Start</a></li></ol></nav>')
    ncx = (f'<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
           f'<head><meta name="dtb:uid" content="{book_id}"/></head>\n<docTitle><text>{html.escape(title)}</text></docTitle>\n<navMap>\n'
           + "\n".join(f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{html.escape(t)}</text></navLabel><content src="{d}.xhtml"/></navPoint>'
                       for i, (d, t) in enumerate(listed, 1)) + "\n</navMap>\n</ncx>\n")
    cover_page = xhtml(title, '<div style="text-align:center"><img src="cover.jpg" alt="Cover" style="max-width:100%;max-height:100%"/></div>')

    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")  # must be first and stored uncompressed

        def add(name, data):
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        add("META-INF/container.xml", '<?xml version="1.0"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                                      '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>\n')
        add("OEBPS/content.opf", opf)
        add("OEBPS/nav.xhtml", nav)
        add("OEBPS/toc.ncx", ncx)
        add("OEBPS/style.css", CSS)
        add("OEBPS/cover.xhtml", cover_page)
        add("OEBPS/cover.jpg", cover)
        for d, _, page in docs:
            add(f"OEBPS/{d}.xhtml", page)
        for path, data in images.items():
            add(f"OEBPS/{path}", data)
        for f in FONTS.values():
            add(f"OEBPS/fonts/{f}", (local_env.FONTS_DIR / f).read_bytes())
