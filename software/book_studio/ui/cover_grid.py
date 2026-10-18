# software/book_studio/ui/cover_grid.py
# The library shown as book covers (like a bookshelf): each tile is the cover, the title in Gentium, and a coloured
# status pill — New, Reading 62 %, Resting, Ready, Changed, Needs attention — so "how much is done" is visible at a glance.

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from . import style

COVER_W, COVER_H = 130, 184
TILE = QSize(COVER_W + 34, COVER_H + 96)
ROLE_STATUS = Qt.UserRole + 1  # (text, colour)
ROLE_ID = Qt.UserRole + 2


class TileDelegate(QStyledItemDelegate):
    def __init__(self, title_family: str, parent=None):
        super().__init__(parent)
        self.title_font = QFont(title_family, 11)

    def sizeHint(self, option, index):
        return TILE

    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        if option.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(style.ACCENT_SOFT))
            p.drawRoundedRect(r.adjusted(3, 3, -3, -3), 10, 10)
        # Cover, scaled to fit the tile with its own proportions, on a soft shadow
        cover = QRect(r.x() + (r.width() - COVER_W) // 2, r.y() + 10, COVER_W, COVER_H)
        pix = index.data(Qt.DecorationRole)
        if isinstance(pix, QPixmap) and not pix.isNull():
            scaled = pix.scaled(cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            cover = QRect(cover.x() + (COVER_W - scaled.width()) // 2, cover.bottom() - scaled.height() + 1, scaled.width(), scaled.height())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 30))
            p.drawRoundedRect(cover.adjusted(2, 3, 2, 3), 4, 4)
            clip = QPainterPath()
            clip.addRoundedRect(cover, 4, 4)
            p.setClipPath(clip)
            p.drawPixmap(cover, scaled)
            p.setClipping(False)
        # Title: two lines at most
        p.setPen(QColor(style.TEXT))
        p.setFont(self.title_font)
        title_rect = QRect(r.x() + 6, r.y() + COVER_H + 16, r.width() - 12, 44)
        title = p.fontMetrics().elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight, title_rect.width() * 2 - 10)
        p.drawText(title_rect, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, title)
        # Status pill
        text, colour = index.data(ROLE_STATUS) or ("", style.MUTED)
        if text:
            f = QFont(p.font())
            f.setFamily("")
            f.setPointSize(9)
            f.setBold(True)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(text) + 18
            pill = QRect(r.x() + (r.width() - w) // 2, r.y() + COVER_H + 64, w, 20)
            c = QColor(colour)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c.red(), c.green(), c.blue(), 30))
            p.drawRoundedRect(pill, 10, 10)
            p.setPen(c)
            p.drawText(pill, Qt.AlignCenter, text)
        p.restore()


class CoverGrid(QListWidget):
    filesDropped = Signal(list)

    def __init__(self, title_family: str):
        super().__init__()
        self.setObjectName("Grid")
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setItemDelegate(TileDelegate(title_family, self))
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def set_book(self, book_id: str, title: str, pixmap: QPixmap | None, status: tuple[str, str]) -> None:
        item = self.item_for(book_id)
        if item is None:
            item = QListWidgetItem()
            item.setData(ROLE_ID, book_id)
            self.addItem(item)
        item.setText(title)
        if pixmap is not None:
            item.setData(Qt.DecorationRole, pixmap)
        item.setData(ROLE_STATUS, status)

    def item_for(self, book_id: str) -> QListWidgetItem | None:
        return next((self.item(i) for i in range(self.count()) if self.item(i).data(ROLE_ID) == book_id), None)

    def selected_id(self) -> str | None:
        items = self.selectedItems()
        return items[0].data(ROLE_ID) if items else None

    # Drag PDFs from Finder / Explorer onto the shelf
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(".pdf")]
        if files:
            self.filesDropped.emit(files)
        e.acceptProposedAction()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0:  # empty shelf: say what to do
            p = QPainter(self.viewport())
            p.setPen(QColor(style.MUTED))
            f = QFont(p.font())
            f.setPointSize(15)
            p.setFont(f)
            p.drawText(self.viewport().rect(), Qt.AlignCenter,
                       "No books yet.\n\nClick  “＋ Add books”  above,\nor drag PDF files here.")
