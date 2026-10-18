# software/book_studio/ui/book_list.py
# The library as a list, one row per book (like a download manager): a tick box (is it in the next run?), the cover, title and
# author, a step tracker — Read pages → Chapters → PDF → EPUB (digital PDFs: Read text → PDF → EPUB) with done / now / to do —
# and on the right the status in words, a progress bar with pages done, and the time left.

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import style

# A step's state → (symbol in the circle, circle colour, filled?)
STEP_LOOK = {
    "done": ("✓", style.OK, True),
    "active": ("●", style.ACCENT, True),
    "paused": ("❚❚", style.WARN, True),
    "partial": ("◐", style.WARN, False),
    "redo": ("↻", style.WARN, False),
    "failed": ("!", style.BAD, True),
    "todo": ("", "#c9bfb2", False),
}


@dataclass
class RowState:
    title: str
    subtitle: str  # "Rūpa-vilāsa Dāsa · 594 pages"
    thumb: QPixmap | None
    ticked: bool
    steps: list[tuple[str, str]]  # (name, state)
    status: str  # rich text, one line
    colour: str
    detail: str = ""  # second line: time left, rest countdown…
    progress: tuple[int, int] | None = None  # (done, total); (0, 0) = busy without a percentage
    can_open: tuple[bool, bool] = (False, False)  # PDF, EPUB exist
    busy: bool = False


class StepTracker(QWidget):
    """Four (or three) circles joined by a line, each with its name underneath — where this book is in the process."""

    def __init__(self):
        super().__init__()
        self.steps: list[tuple[str, str]] = []
        self.setFixedHeight(46)
        self.setMinimumWidth(236)  # fits beside the details panel
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_steps(self, steps):
        self.steps = steps
        self.update()

    def paintEvent(self, _):
        if not self.steps:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n, w, r = len(self.steps), self.width(), 9
        xs = [w * (i + 0.5) / n for i in range(n)]
        cy = 13
        for i in range(n - 1):  # joining line: solid where the earlier step is done
            p.setPen(QPen(QColor(style.OK if self.steps[i][1] == "done" else "#ddd3c7"), 2))
            p.drawLine(int(xs[i] + r + 3), cy, int(xs[i + 1] - r - 3), cy)
        small = QFont(self.font())
        small.setPointSize(9)
        for (name, state), x in zip(self.steps, xs):
            symbol, colour, filled = STEP_LOOK.get(state, STEP_LOOK["todo"])
            c = QColor(colour)
            p.setPen(QPen(c, 2))
            p.setBrush(c if filled else QColor("white"))
            p.drawEllipse(QRectF(x - r, cy - r, 2 * r, 2 * r))
            if symbol:
                p.setPen(QColor("white") if filled else c)
                f = QFont(small)
                f.setBold(True)
                f.setPointSize(8 if len(symbol) > 1 else 9)
                p.setFont(f)
                p.drawText(QRectF(x - r, cy - r, 2 * r, 2 * r), Qt.AlignCenter, symbol)
            p.setFont(small)
            p.setPen(QColor(style.TEXT if state in ("active", "paused") else style.MUTED))
            p.drawText(QRectF(x - 50, cy + r + 3, 100, 16), Qt.AlignHCenter | Qt.AlignTop, name)
        p.end()


class BookRow(QFrame):
    clicked = Signal(str)
    ticked = Signal(str, bool)
    menuRequested = Signal(str, QPoint)
    openFile = Signal(str, str)  # book id, "pdf" / "epub"

    def __init__(self, book_id: str, title_family: str):
        super().__init__()
        self.book_id = book_id
        self.setObjectName("Row")
        self.setProperty("current", False)
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(12)

        self.tick = QCheckBox()
        self.tick.setToolTip("Tick to include this book when you press Make")
        self.tick.toggled.connect(lambda on: self.ticked.emit(self.book_id, on))
        h.addWidget(self.tick)

        self.thumb = QLabel()
        self.thumb.setFixedSize(QSize(40, 56))
        self.thumb.setAlignment(Qt.AlignCenter)
        h.addWidget(self.thumb)

        names = QVBoxLayout()
        names.setSpacing(2)
        self.title = QLabel()
        self.title.setFont(QFont(title_family, 14))
        self.title.setMinimumWidth(1)  # long titles are cut with … instead of widening the row
        self.sub = QLabel()
        self.sub.setObjectName("Muted")
        self.sub.setMinimumWidth(1)
        names.addWidget(self.title)
        names.addWidget(self.sub)
        holder = QWidget()
        holder.setLayout(names)
        holder.setMinimumWidth(140)
        holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        h.addWidget(holder, 3)

        self.steps = StepTracker()
        h.addWidget(self.steps, 3)

        right = QVBoxLayout()
        right.setSpacing(3)
        self.status = QLabel()
        self.status.setTextFormat(Qt.RichText)
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.detail = QLabel()
        self.detail.setObjectName("Hint")
        right.addWidget(self.status)
        right.addWidget(self.bar)
        right.addWidget(self.detail)
        box = QWidget()
        box.setLayout(right)
        box.setFixedWidth(215)
        h.addWidget(box)

        self.pdf_btn = self._link("PDF", lambda: self.openFile.emit(self.book_id, "pdf"))
        self.epub_btn = self._link("EPUB", lambda: self.openFile.emit(self.book_id, "epub"))
        more = self._link("⋯", lambda: self.menuRequested.emit(self.book_id, more.mapToGlobal(more.rect().bottomLeft())))
        more.setToolTip("More: make now, check book, clear, remove…")
        for b in (self.pdf_btn, self.epub_btn, more):
            h.addWidget(b)

    @staticmethod
    def _link(text, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("Link")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def show_state(self, s: RowState, current: bool):
        self.title.setText(s.title)
        self.sub.setText(s.subtitle)
        if s.thumb is not None and not s.thumb.isNull():
            self.thumb.setPixmap(s.thumb.scaled(self.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.tick.blockSignals(True)
        self.tick.setChecked(s.ticked)
        self.tick.blockSignals(False)
        self.tick.setEnabled(not s.busy)
        self.steps.set_steps(s.steps)
        self.status.setText(f"<span style='color:{s.colour}'><b>{s.status}</b></span>")
        self.detail.setText(s.detail)
        self.detail.setVisible(bool(s.detail))
        self.bar.setVisible(s.progress is not None)
        if s.progress is not None:
            done, total = s.progress
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        self.pdf_btn.setVisible(s.can_open[0])
        self.epub_btn.setVisible(s.can_open[1])
        if self.property("current") != current:  # re-polish only when it changes (it restyles the whole row)
            self.setProperty("current", current)
            self.style().unpolish(self)
            self.style().polish(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.book_id)
        elif e.button() == Qt.RightButton:
            self.menuRequested.emit(self.book_id, e.globalPosition().toPoint())


class BookList(QScrollArea):
    """The rows in library order, plus drag-and-drop of PDFs or folders and an empty-shelf message."""
    filesDropped = Signal(list)

    def __init__(self, title_family: str):
        super().__init__()
        self.title_family = title_family
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setAcceptDrops(True)
        body = QWidget()
        body.setObjectName("ListBody")
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(12, 8, 12, 12)
        self.lay.setSpacing(6)
        self.empty = QLabel("No books yet.\n\nClick  “＋ Add books”  above,\nor drag PDF files or a folder here.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("font-size: 16px; padding: 80px;")
        self.lay.addWidget(self.empty)
        self.lay.addStretch()
        self.setWidget(body)
        self.rows: dict[str, BookRow] = {}

    def row(self, book_id: str) -> BookRow:
        if book_id not in self.rows:
            row = BookRow(book_id, self.title_family)
            self.rows[book_id] = row
            self.lay.insertWidget(self.lay.count() - 1, row)  # before the stretch
        self.empty.setVisible(False)
        return self.rows[book_id]

    def remove(self, book_id: str):
        row = self.rows.pop(book_id, None)
        if row:
            row.setParent(None)
            row.deleteLater()
        self.empty.setVisible(not self.rows)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        items = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if items:
            self.filesDropped.emit(items)
        e.acceptProposedAction()
