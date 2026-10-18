# software/book_studio/ui/book_panel.py
# The right-hand panel for the selected book: cover (page 1 of the PDF, or an image the user picks), title, subtitle,
# author, whether to keep the book's own copyright page, and buttons to open the finished files, see warnings and (advanced) book fixes.
# Every edit is saved at once; the book then shows "Changed" until it is made again.

import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import paths
from ..store import Book


class BookPanel(QScrollArea):
    changed = Signal(str)  # book id — saved; grid and status need a refresh
    coverChanged = Signal(str)
    showCheck = Signal(str)
    showFixes = Signal(str)
    makeThis = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumWidth(330)
        self.book: Book | None = None
        self._loading = False
        self._save_timer = QTimer(self, singleShot=True, interval=600)  # save shortly after typing stops
        self._save_timer.timeout.connect(self._save)

        body = QWidget()
        body.setObjectName("Panel")
        self.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        self.empty = QLabel("Select a book on the left\nto see and change its details.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.empty, 1)

        self.form = QWidget()
        lay.addWidget(self.form)
        f = QVBoxLayout(self.form)
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(10)

        # Cover
        cover_row = QHBoxLayout()
        self.cover = QLabel()
        self.cover.setFixedSize(QSize(120, 170))
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background: #f3eee7; border-radius: 4px;")
        cover_row.addWidget(self.cover)
        cover_btns = QVBoxLayout()
        cover_btns.addWidget(QLabel("<b>Cover</b>"))
        self.cover_note = QLabel()
        self.cover_note.setObjectName("Hint")
        self.cover_note.setWordWrap(True)
        cover_btns.addWidget(self.cover_note)
        self.pick_cover = QPushButton("Choose image…")
        self.pick_cover.clicked.connect(self._choose_cover)
        self.page1_cover = QPushButton("Use page 1 of the PDF")
        self.page1_cover.setObjectName("Link")
        self.page1_cover.clicked.connect(self._use_page1)
        cover_btns.addWidget(self.pick_cover)
        cover_btns.addWidget(self.page1_cover)
        cover_btns.addStretch()
        cover_row.addLayout(cover_btns, 1)
        f.addLayout(cover_row)

        # Title page details
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.title = QLineEdit()
        self.subtitle = QLineEdit()
        self.author = QLineEdit()
        for w in (self.title, self.subtitle, self.author):
            w.textEdited.connect(self._edited)
        form.addRow("Title", self.title)
        form.addRow("Subtitle", self.subtitle)
        form.addRow("Author", self.author)
        f.addLayout(form)

        self.keep_copyright = QCheckBox("Keep the book's copyright page")
        self.keep_copyright.setToolTip("The page with ©, ISBN and publisher from the original book, placed after the title page")
        self.keep_copyright.toggled.connect(self._edited)
        f.addWidget(self.keep_copyright)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        f.addWidget(self.status)

        self.make_btn = QPushButton("Make this book now")
        self.make_btn.setObjectName("Primary")
        self.make_btn.clicked.connect(lambda: self.book and self.makeThis.emit(self.book.id))
        f.addWidget(self.make_btn)

        files = QHBoxLayout()
        self.open_pdf = QPushButton("Open PDF")
        self.open_epub = QPushButton("Open EPUB")
        self.open_pdf.clicked.connect(lambda: self._open(self.book.pdf))
        self.open_epub.clicked.connect(lambda: self._open(self.book.epub))
        files.addWidget(self.open_pdf)
        files.addWidget(self.open_epub)
        f.addLayout(files)

        extra = QHBoxLayout()
        self.check = QPushButton("Check book")
        self.check.setToolTip("Did everything come out? Chapters found and pages worth a look, beside the scan")
        self.check.clicked.connect(lambda: self.showCheck.emit(self.book.id))
        self.fixes = QPushButton("Book fixes…")
        self.fixes.setToolTip("Advanced: settings for books with an unusual layout")
        self.fixes.clicked.connect(lambda: self.showFixes.emit(self.book.id))
        extra.addWidget(self.check)
        extra.addWidget(self.fixes)
        self.fixes.hide()  # expert tool: shown only when Settings → Advanced → Show expert tools is on
        f.addLayout(extra)

        self.source = QLabel()
        self.source.setObjectName("Hint")
        self.source.setWordWrap(True)
        f.addWidget(self.source)
        f.addStretch()
        self.show_book(None)

    # ---------- showing a book ----------

    def show_book(self, book: Book | None, pixmap: QPixmap | None = None, status_html: str = "", busy: bool = False) -> None:
        self._save_timer.stop()
        self.book = book
        self.empty.setVisible(book is None)
        self.form.setVisible(book is not None)
        if book is None:
            return
        self._loading = True
        self.title.setText(book.title)
        self.subtitle.setText(book.subtitle)
        self.author.setText(book.author)
        self.keep_copyright.setChecked(book.keep_copyright)
        self._loading = False
        self.set_cover(pixmap)
        self.cover_note.setText("Your own image." if book.cover_file else "Page 1 of the PDF (the original cover).")
        self.page1_cover.setVisible(bool(book.cover_file))
        self.source.setText(f"{book.pages} pages · added from {book.source}")
        self.update_state(status_html, busy)

    def set_cover(self, pixmap: QPixmap | None) -> None:
        if pixmap and not pixmap.isNull():
            self.cover.setPixmap(pixmap.scaled(self.cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cover.clear()

    def update_state(self, status_html: str, busy: bool) -> None:
        b = self.book
        if b is None:
            return
        self.status.setText(status_html)
        self.open_pdf.setEnabled(bool(b.pdf) and Path(b.pdf).exists())
        self.open_epub.setEnabled(bool(b.epub) and Path(b.epub).exists())
        self.check.setEnabled((paths.WORK_DIR / "output" / b.id / "2-assembled" / "report.txt").exists() or bool(b.error))
        # Details stay editable while the book is being made: changes apply the next time it is made, which takes seconds
        self.make_btn.setEnabled(not busy)

    # ---------- edits ----------

    def _edited(self, *_):
        if self._loading or not self.book:
            return
        self._save_timer.start()

    def _save(self):
        b = self.book
        if not b:
            return
        b.title, b.subtitle, b.author = self.title.text().strip(), self.subtitle.text().strip(), self.author.text().strip()
        b.keep_copyright = self.keep_copyright.isChecked()
        self.changed.emit(b.id)

    def flush(self):
        """Save a pending edit now (before making a book or switching to another one)."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save()

    def _choose_cover(self):
        start = str(Path(self.book.source).parent) if self.book.source else str(Path.home())
        file, _ = QFileDialog.getOpenFileName(self, "Choose a cover picture", start, "Pictures (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp)")
        if not file:
            return
        # A copy, so moving or deleting the original picture later can't break the book
        if self.book.cover_file:
            (paths.COVERS_DIR / self.book.cover_file).unlink(missing_ok=True)
        name = f"{self.book.id}{Path(file).suffix.lower()}"
        shutil.copy2(file, paths.COVERS_DIR / name)
        self.book.cover_file = name
        self.coverChanged.emit(self.book.id)

    def _use_page1(self):
        if self.book.cover_file:
            (paths.COVERS_DIR / self.book.cover_file).unlink(missing_ok=True)
        self.book.cover_file = ""
        self.coverChanged.emit(self.book.id)

    def _open(self, file: str):
        if file and Path(file).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(file))
