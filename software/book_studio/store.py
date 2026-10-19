# software/book_studio/store.py
# Book Studio's saved state: app settings (folders, cool-down, cores) and the library of books with what the user edited
# (title, cover, keep the copyright page, book fixes). Turns each book into the book_meta.json entry the pipeline reads.

import hashlib
import json
import os
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium

from . import paths


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    """Write via a temporary file, so a crash mid-save never leaves a half-written settings file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _from_dict(cls, data: dict):
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})  # ignore keys from newer/older versions


@dataclass
class Settings:
    output_dir: str = str(Path.home() / "Documents" / "Book Studio")
    pdf_dir: str = ""  # where finished PDFs go; empty = <output_dir>/PDF
    epub_dir: str = ""  # where finished EPUBs go; empty = <output_dir>/EPUB
    cooldown: bool = True
    work_minutes: int = 60
    rest_minutes: int = 15
    between_minutes: int = 60
    cores: int = max(1, (os.cpu_count() or 2) // 2)
    slots: int = 4  # parallel OCR slots: each holds its own memory (≈1.7 GB in all at 4 on the M4)
    engine: str = ""  # installed llama-server build, e.g. "macos-arm64", "win-vulkan-x64"
    expert: bool = False  # shows Book fixes; volunteers don't need it
    details_open: bool = False  # the book details panel on the right (collapsible)
    sec_per_page: float = 0.0  # this computer's measured reading speed, for time-left estimates before the first pages

    @classmethod
    def load(cls) -> "Settings":
        return _from_dict(cls, _read_json(paths.SETTINGS_FILE, {}))

    def pdf_folder(self) -> Path:
        return Path(self.pdf_dir or Path(self.output_dir) / "PDF")

    def epub_folder(self) -> Path:
        return Path(self.epub_dir or Path(self.output_dir) / "EPUB")

    def save(self) -> None:
        write_json(paths.SETTINGS_FILE, asdict(self))


@dataclass
class Book:
    id: str  # file-name-safe key: work/books/<id>.pdf, work/output/<id>/
    source: str  # where the PDF was added from (shown only; the library keeps its own copy)
    title: str = ""
    subtitle: str = ""
    author: str = ""
    cover_file: str = ""  # file name inside covers/ when the user picked their own image
    ticked: bool = True  # included when Make is pressed
    kind: str = ""  # "scanned" or "digital", as the worker found it (decides which steps are shown)
    keep_copyright: bool = True  # keep the book's own copyright page (©, ISBN, publisher) — on by default (user asked 2026-10-18)
    fixes: dict = field(default_factory=dict)  # advanced book_meta options, plus "kind": auto / scanned / digital
    pages: int = 0
    added: str = ""
    built: str = ""  # time of the last successful build
    built_hash: str = ""  # settings fingerprint at that build — tells "Ready" from "Changed"
    error: str = ""
    pdf: str = ""  # finished files from the last build
    epub: str = ""


def builtin_meta() -> dict:
    """Book settings imported in Settings (the finished books' fixes). Running from the repo with BOOK_LIBRARY set, that library's book_meta.json is used."""
    data = _read_json(paths.BUILTIN_META_FILE, None)
    if data is None and not paths.IS_INSTALLED and os.environ.get("BOOK_LIBRARY"):
        data = _read_json(Path(os.environ["BOOK_LIBRARY"]) / "book_meta.json", {})  # the manual pipeline's library, given explicitly
    return data or {}


def meta_for(book: Book, builtin: dict) -> dict:
    """The book_meta.json entry for one book: built-in settings, then the user's fixes, title, cover and copyright choice on top."""
    meta = dict(builtin.get(book.id) or {"layout": "prose", "credits": []})
    meta.update({k: v for k, v in book.fixes.items() if k != "kind"})
    # The cover is only ever the picture the volunteer chose here: a cover_file in imported settings or fixes could point at
    # any file on this computer and slip it into a PDF that gets shared
    meta.pop("cover_file", None)
    meta.update(title=book.title or meta.get("title") or book.id, subtitle=book.subtitle, author=book.author)
    meta.setdefault("credits", [])
    meta.setdefault("layout", "prose")
    if book.cover_file:
        meta["cover_file"] = str(paths.COVERS_DIR / book.cover_file)
    if book.keep_copyright:
        meta["keep_copyright"] = True
    return meta


def fingerprint(book: Book, builtin: dict) -> str:
    data = meta_for(book, builtin) | {"kind": book.fixes.get("kind", "auto")}
    if book.cover_file:  # a new picture under the same name is still a change
        cover = paths.COVERS_DIR / book.cover_file
        data["cover_mtime"] = cover.stat().st_mtime if cover.exists() else 0
    return hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def slugify(name: str) -> str:
    """'Śrī Padyāvalī (scan)' → 'sri-padyavali-scan' — matches the keys of the finished books' settings."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "book"


def _pdf_metadata(path: Path) -> tuple[str, str]:
    """Title and author stored in the PDF, when they look like real ones (not 'Microsoft Word - scan.docx')."""
    try:  # pypdfium2, not PyMuPDF: Windows Smart App Control can block PyMuPDF, and adding a book must not trigger it
        doc = pdfium.PdfDocument(str(path))
        meta = doc.get_metadata_dict()
        doc.close()
    except Exception:  # noqa: BLE001 — no metadata is fine: the title then comes from the file name
        return "", ""
    title, author = (meta.get("Title") or "").strip(), (meta.get("Author") or "").strip()
    if re.search(r"\.(docx?|pdf|indd)$|^microsoft|^untitled", title, re.I):
        title = ""
    return title, author


class Library:
    def __init__(self, books: list[Book]):
        self.books = books

    @classmethod
    def load(cls) -> "Library":
        return cls([_from_dict(Book, b) for b in _read_json(paths.LIBRARY_FILE, [])])

    def save(self) -> None:
        write_json(paths.LIBRARY_FILE, [asdict(b) for b in self.books])
        self.write_meta()

    def get(self, book_id: str) -> Book | None:
        return next((b for b in self.books if b.id == book_id), None)

    def write_meta(self) -> None:
        builtin = builtin_meta()
        write_json(paths.MERGED_META_FILE, {b.id: meta_for(b, builtin) for b in self.books})

    def add_pdf(self, source: Path) -> Book | None:
        """Copies the PDF into the library (a hard link when possible, so it costs no extra disk space). None if already added."""
        for b in self.books:
            if Path(b.source) == source:
                return None
        base = slugify(source.stem)
        book_id, n = base, 2
        while self.get(book_id) or (paths.WORK_DIR / "books" / f"{book_id}.pdf").exists():
            book_id, n = f"{base}-{n}", n + 1
        target = paths.WORK_DIR / "books" / f"{book_id}.pdf"
        try:
            os.link(source, target)
        except OSError:  # another drive, or a file system without hard links
            shutil.copy2(source, target)
        builtin = builtin_meta().get(book_id, {})
        title, author = _pdf_metadata(target)
        book = Book(
            id=book_id,
            source=str(source),
            title=builtin.get("title") or title or re.sub(r"[-_]+", " ", source.stem).strip().title(),
            subtitle=builtin.get("subtitle", ""),
            author=builtin.get("author") or author,
            pages=len(pdfium.PdfDocument(str(target))),
            added=datetime.now().isoformat(timespec="seconds"),
        )
        self.books.append(book)
        self.save()
        return book

    def remove(self, book: Book, keep_work: bool = False) -> None:
        self.books.remove(book)
        (paths.WORK_DIR / "books" / f"{book.id}.pdf").unlink(missing_ok=True)
        (paths.THUMBS_DIR / f"{book.id}.png").unlink(missing_ok=True)
        if book.cover_file:
            (paths.COVERS_DIR / book.cover_file).unlink(missing_ok=True)
        if not keep_work:
            clear_work(book)
        self.save()


def ocr_pages_done(book: Book) -> int:
    folder = paths.WORK_DIR / "output" / book.id / "1-ocr"
    return sum(1 for _ in folder.glob("page-*.json")) if folder.exists() else 0


def clear_work(book: Book) -> None:
    """Frees the disk space of a book's working files (OCR pages etc.); the finished PDF and EPUB stay in the output folder."""
    shutil.rmtree(paths.WORK_DIR / "output" / book.id, ignore_errors=True)
    (paths.LOGS_DIR / f"{book.id}.log").unlink(missing_ok=True)


def safe_filename(title: str) -> str:
    """A title usable as a file name on every system (Windows forbids : * ? " < > | / \\)."""
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|]+', " ", title)).strip(" .") or "book"  # "A: B" → "A B", not "A  B"
