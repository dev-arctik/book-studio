# software/book_studio/ui/main_window.py
# The main window: a toolbar (Add books · Open finished books · Output folders · Settings); a run card that says where the
# whole run is ("2 of 5 books done · now Without Fear — reading page 212 of 594 · about 6 h left in all"); a selection bar
# (Select all, Make ticked books); the list of books, each with its tick box, step tracker and progress; and the collapsible
# details panel. Runs ticked books one after another, each in a worker process, with the cool-down rests in between.

import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps
from PySide6.QtCore import QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QPushButton, QSplitter, QVBoxLayout, QWidget)

from .. import APP_NAME, engine, paths, report, store, updater
from . import style
from .book_list import BookList, RowState
from .book_panel import BookPanel
from .dialogs import CheckDialog, FixesDialog, OutputDialog, SettingsDialog, SetupDialog, Task, UpdatesDialog, offer_update
from power import LOW_BATTERY, battery, keep_awake  # noqa: E402  (manual/pipeline/power.py, shared with the worker)

SCAN_STEPS = ["Read", "Chapters", "PDF", "EPUB"]
DIGITAL_STEPS = ["Text", "PDF", "EPUB"]
# Which step a worker stage belongs to (index into the book's steps; digital books have no Chapters step)
STAGE_STEP = {"starting": "first", "ocr": "first", "rest": "first", "paused": "first", "battery": "first", "text": "first",
              "assemble": "Chapters", "typeset": "PDF", "epub": "EPUB"}
STAGE_TEXT = {
    "starting": "Starting the page reader…",
    "text": "Reading the text of this digital PDF…",
    "assemble": "Putting the chapters together…",
    "typeset": "Making the PDF…",
    "epub": "Making the EPUB…",
}
AFTER_READING = 90  # seconds for chapters + PDF + EPUB once the pages are read — only for time-left estimates


def fmt_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{max(minutes, 1)} min"


def fmt_size(path: str | Path) -> str:
    """'19 MB' / '850 KB' for a file, '' if it's missing."""
    try:
        n = Path(path).stat().st_size
    except (OSError, TypeError):
        return ""
    return f"{n / 1e6:,.0f} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} KB"


def fmt_clock(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class WorkerRunner(QThread):
    """Starts `python -m book_studio.worker <book>` and turns its @@ lines into signals."""
    event = Signal(dict)
    ended = Signal(int, str)

    def __init__(self, book_id: str, env: dict, parent=None):
        super().__init__(parent)
        self.book_id, self.env, self.proc = book_id, env, None

    def run(self):
        python = Path(sys.executable)
        if python.name.lower() == "pythonw.exe":  # the window runs windowless; the worker needs a normal (hidden) console
            python = python.with_name("python.exe")
        self.proc = subprocess.Popen([str(python), "-m", "book_studio.worker", self.book_id], cwd=paths.APP_DIR, env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                     errors="replace", creationflags=engine.NO_WINDOW)
        tail = []
        for line in self.proc.stdout:
            if line.startswith("@@"):
                try:
                    self.event.emit(json.loads(line[2:]))
                except ValueError:
                    pass
            else:
                tail = (tail + [line.rstrip()])[-15:]  # crashes before the log opens land here
        self.ended.emit(self.proc.wait(), "\n".join(tail))

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


class MainWindow(QMainWindow):
    def __init__(self, title_family: str):
        super().__init__()
        self.settings = store.Settings.load()
        self.library = store.Library.load()
        self.library.write_meta()
        self.runner: WorkerRunner | None = None
        self.current: str | None = None
        self.queue: list[str] = []
        self.run_ids: list[str] = []  # every book in this run, in order (done, current and waiting)
        self.run_done: list[str] = []
        self.phase = ""
        self.progress_info: dict = {}
        self.rest_until = 0.0
        self.between_until = 0.0
        self.stop_requested = False
        self.last_event = ""
        self.did_read_pages = False
        self.retry_now = False  # the current book was stopped so failed books go first: no rest before them
        self.delete_after_stop: str | None = None  # book whose progress to throw away once it has stopped
        self.current_hash = ""  # the book's settings when it started — edits made while it runs show as 'Changed' afterwards
        self.finished_note = ""
        self.battery_pct = 0  # battery % when reading paused for low battery
        self.power_seen = 0.0  # when the power line was last refreshed
        self.awake: ExitStack | None = None  # holds off sleep for the whole run, rests between books included
        self.selected: str | None = None  # the book shown in the details panel
        self.thumbs: dict[str, QPixmap] = {}

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(paths.ASSETS_DIR / "icon.png")))
        self.resize(1280, 800)
        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._toolbar())

        self.split = QSplitter()
        self.split.setHandleWidth(1)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        lv.addWidget(self._run_card())
        lv.addWidget(self._select_bar())
        self.list = BookList(title_family)
        self.list.filesDropped.connect(self.add_files)
        lv.addWidget(self.list, 1)
        self.panel = BookPanel()
        self.panel.changed.connect(self._book_edited)
        self.panel.coverChanged.connect(self._cover_changed)
        self.panel.showCheck.connect(self.show_check)
        self.panel.showFixes.connect(self.show_fixes)
        self.panel.makeThis.connect(lambda bid: self.make_now([bid]))
        self.panel.fixes.setVisible(self.settings.expert)
        self.split.addWidget(left)
        self.split.addWidget(self.panel)
        self.split.setStretchFactor(0, 1)
        self.split.setSizes([900, 380])
        lay.addWidget(self.split, 1)
        self.panel.setVisible(self.settings.details_open)

        self.ticker = QTimer(self, interval=1000)  # countdowns and time-left
        self.ticker.timeout.connect(self._tick)
        self.ticker.start()
        for b in self.library.books:
            self._wire_row(b)
        self.selected = self.library.books[0].id if self.library.books else None
        self._refresh_all()
        QTimer.singleShot(0, self._first_run)

    # ---------- layout ----------

    def _toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Toolbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 6, 10, 6)
        self.add_btn = self._tool("＋  Add books")
        add_menu = QMenu(self)
        add_menu.addAction("PDF files…  (select one or several)", self.choose_files)
        add_menu.addAction("A whole folder of PDFs…", self.choose_folder)
        self.add_btn.setMenu(add_menu)
        self.open_btn = self._tool("Open finished books")
        open_menu = QMenu(self)
        open_menu.addAction("PDF folder", lambda: self.open_folder(self.settings.pdf_folder()))
        open_menu.addAction("EPUB folder", lambda: self.open_folder(self.settings.epub_folder()))
        self.open_btn.setMenu(open_menu)
        self.folders_btn = self._tool("Output folders…", self.show_output_folders)
        self.updates_btn = self._tool("Check for updates", self.show_updates)
        self.settings_btn = self._tool("Settings", self.show_settings)
        for b in (self.add_btn, self.open_btn, self.folders_btn):
            h.addWidget(b)
        h.addStretch()
        h.addWidget(self.updates_btn)
        h.addWidget(self.settings_btn)
        return bar

    def _tool(self, text, slot=None) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("Tool")
        if slot:  # buttons with a menu open it instead
            b.clicked.connect(slot)
        return b

    def _run_card(self) -> QWidget:
        """Top card: what the whole run is doing, or (when idle) what is ready to start."""
        outer = QWidget()
        o = QVBoxLayout(outer)
        o.setContentsMargins(12, 12, 12, 4)
        card = QFrame()
        card.setObjectName("RunCard")
        o.addWidget(card)
        h = QHBoxLayout(card)
        h.setContentsMargins(16, 12, 16, 12)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.run_title = QLabel()
        self.run_title.setObjectName("RunTitle")
        self.run_title.setTextFormat(Qt.RichText)
        self.run_line = QLabel()
        self.run_line.setTextFormat(Qt.RichText)
        self.run_line.setWordWrap(True)
        self.run_bar = QProgressBar()
        self.run_bar.setTextVisible(False)
        self.run_bar.setFixedHeight(10)
        self.run_numbers = QLabel()
        self.run_numbers.setObjectName("Hint")
        self.power_line = QLabel()  # plugged in / on battery, while books are being made
        self.power_line.setTextFormat(Qt.RichText)
        for w in (self.run_title, self.run_line, self.run_bar, self.run_numbers, self.power_line):
            col.addWidget(w)
        h.addLayout(col, 1)
        self.make_btn = QPushButton("▶  Make ticked books")
        self.make_btn.setObjectName("Primary")
        self.make_btn.clicked.connect(lambda: self.make_books())
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.retry_btn = QPushButton("Retry failed")
        self.retry_btn.setToolTip("Makes the books that failed again now — the book being read waits (its pages are kept) and continues after them")
        self.retry_btn.clicked.connect(self.retry_failed)
        self.report_btn = QPushButton("Copy report")
        self.report_btn.setToolTip("Copies what's worth a look in each book of the last run — to paste into a message for help")
        self.report_btn.clicked.connect(self.copy_run_report)
        self.skip_btn = QPushButton("Skip the rest")
        self.skip_btn.clicked.connect(self.skip_rest)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop)
        for b in (self.make_btn, self.pause_btn, self.retry_btn, self.report_btn, self.skip_btn, self.stop_btn):
            h.addWidget(b, alignment=Qt.AlignVCenter)
        return outer

    def _select_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("SelectBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(26, 6, 16, 4)
        self.select_all = QCheckBox("Select all")
        self.select_all.setTristate(False)
        self.select_all.clicked.connect(self._select_all_clicked)
        self.select_count = QLabel()
        self.select_count.setObjectName("Muted")
        self.bulk_btn = QPushButton("With ticked books ▾")
        self.bulk_btn.setObjectName("Link")
        bulk = QMenu(self)
        bulk.addAction("Clear their working files (free disk space)", lambda: self.clear_work(*self._ticked_books()))
        bulk.addAction("Remove them from Book Studio", lambda: self.remove_book(*self._ticked_books()))
        self.bulk_btn.setMenu(bulk)
        self.details_btn = QPushButton()
        self.details_btn.setObjectName("Link")
        self.details_btn.clicked.connect(lambda: self.set_details(not self.panel.isVisible()))
        h.addWidget(self.select_all)
        h.addWidget(self.select_count)
        h.addWidget(self.bulk_btn)
        h.addStretch()
        h.addWidget(self.details_btn)
        return bar

    def set_details(self, show: bool):
        """The details panel (title, cover, copyright, check book) slides in on the right; remembered between sessions."""
        self.panel.flush()
        self.panel.setVisible(show)
        self.settings.details_open = show
        self.settings.save()
        self._refresh_select_bar()

    # ---------- first run, updates ----------

    def _first_run(self):
        """On opening: look for an update first (a fix may matter for the books about to be made), then set up if needed."""
        if paths.IS_INSTALLED or os.environ.get("BOOK_STUDIO_CHECK_UPDATES"):
            self.run_title.setText("Checking for updates…")
            self.check_updates(quiet=True, then=self._setup_if_needed)
        else:
            self._setup_if_needed()

    def _setup_if_needed(self):
        self._refresh_run_card()
        if not (engine.engine_ready() and engine.model_ready()):
            SetupDialog(self.settings, self).exec()

    def check_updates(self, quiet: bool, then=None):
        """Asks GitHub for a newer release (offline: gives up after a few seconds); then() runs afterwards unless updating."""
        self._update_task = Task(lambda progress: updater.latest_release(), parent=self)

        def found(release):
            if release is None:
                if not quiet:
                    QMessageBox.information(self, "Updates", "You have the newest Book Studio.")
            elif not self.runner and offer_update(self, release):
                QApplication.quit()
                return
            if then:
                then()
        self._update_task.succeeded.connect(found)
        self._update_task.failed.connect(lambda _: then and then())
        self._update_task.start()

    # ---------- library ----------

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add books", str(Path.home()), "PDF files (*.pdf)")
        if files:
            self.add_files(files)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add every PDF in a folder", str(Path.home()))
        if folder:
            self.add_files([folder])

    def _expand(self, items: list[str]) -> list[str]:
        """Files as given; folders → every PDF inside them (subfolders too), except Book Studio's own finished books."""
        ours = {self.settings.pdf_folder().resolve(), self.settings.epub_folder().resolve()}
        files = []
        for item in items:
            path = Path(item)
            if path.is_dir():
                files += sorted(str(f) for f in path.rglob("*") if f.suffix.lower() == ".pdf" and f.is_file()
                                and not any(f.resolve().is_relative_to(o) for o in ours))
            elif path.suffix.lower() == ".pdf":
                files.append(item)
        return files

    def add_files(self, items: list[str]):
        files = self._expand(items)
        if not files:
            QMessageBox.information(self, "No PDFs", "No PDF files were found there.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        added, skipped = [], 0
        try:
            for f in files:
                try:
                    book = self.library.add_pdf(Path(f))
                except Exception as exc:  # noqa: BLE001 — a damaged PDF must not stop the others
                    QMessageBox.warning(self, "Couldn't add a book", f"{Path(f).name} could not be opened as a PDF.\n({exc})")
                    continue
                if book:
                    added.append(book)
                    self._wire_row(book)
                else:
                    skipped += 1
        finally:
            QApplication.restoreOverrideCursor()
        if added:
            self.selected = added[-1].id
        if skipped:
            QMessageBox.information(self, "Already added", f"{skipped} of these books {'is' if skipped == 1 else 'are'} already in Book Studio.")
        self._refresh_all()

    def thumbnail(self, book: store.Book, fresh: bool = False) -> QPixmap:
        file = paths.THUMBS_DIR / f"{book.id}.png"
        if fresh or not file.exists():
            if book.cover_file and (paths.COVERS_DIR / book.cover_file).exists():
                img = ImageOps.exif_transpose(Image.open(paths.COVERS_DIR / book.cover_file)).convert("RGB")
            else:
                page = pdfium.PdfDocument(str(paths.WORK_DIR / "books" / f"{book.id}.pdf"))[0]
                img = page.render(scale=400 / page.get_height()).to_pil().convert("RGB")
            img.thumbnail((300, 400))
            img.save(file)
        if fresh or book.id not in self.thumbs:
            self.thumbs[book.id] = QPixmap(str(file))
        return self.thumbs[book.id]

    def _wire_row(self, b: store.Book):
        row = self.list.row(b.id)
        if not row.property("wired"):
            row.setProperty("wired", True)
            row.clicked.connect(self._row_clicked)
            row.ticked.connect(self._row_ticked)
            row.menuRequested.connect(self._row_menu)
            row.openFile.connect(self._open_file)

    # ---------- what each book's row says ----------

    def is_ready(self, b: store.Book) -> bool:
        return bool(b.built) and b.built_hash == store.fingerprint(b, store.builtin_meta()) and Path(b.pdf).exists()

    def needs_work(self, b: store.Book) -> bool:
        return b.id != self.current and not self.is_ready(b)

    def steps_of(self, b: store.Book) -> list[tuple[str, str]]:
        names = DIGITAL_STEPS if b.kind == "digital" else SCAN_STEPS
        if b.id == self.current:
            key = STAGE_STEP.get(self.phase, "first")
            active = 0 if key == "first" else (names.index(key) if key in names else 1)
            look = "paused" if self.phase in ("paused", "rest", "battery") else "active"
            if active == 0 and b.kind != "digital" and self.progress_info.get("done", 0) >= b.pages > 0 and self.phase == "ocr":
                look = "active"
            return [(n, "done" if i < active else look if i == active else "todo") for i, n in enumerate(names)]
        if self.is_ready(b):
            return [(n, "done") for n in names]
        assembled = (paths.WORK_DIR / "output" / b.id / "2-assembled" / "book.json").exists()
        read = store.ocr_pages_done(b)
        states = {}
        if b.kind == "digital":
            states["Text"] = "done" if assembled else "todo"
        else:
            states["Read"] = "done" if read >= b.pages > 0 else "partial" if read else "todo"
            states["Chapters"] = "done" if assembled and read >= b.pages else "todo"
        made = bool(b.built) and Path(b.pdf).exists()
        states["PDF"] = "redo" if made else "todo"
        states["EPUB"] = "redo" if made and Path(b.epub).exists() else "todo"
        if b.error:  # mark where it went wrong: the first step not done
            first = next((n for n in names if states[n] != "done"), names[-1])
            states[first] = "failed"
        return [(n, states[n]) for n in names]

    def row_state(self, b: store.Book) -> RowState:
        read = store.ocr_pages_done(b)
        scan_size = fmt_size(paths.WORK_DIR / "books" / f"{b.id}.pdf")
        sub = " · ".join(x for x in (b.author, f"{b.pages} pages", scan_size, "digital PDF" if b.kind == "digital" else "") if x)
        st = RowState(title=b.title, subtitle=sub, thumb=self.thumbnail(b), ticked=b.ticked, steps=self.steps_of(b),
                      status="", colour=style.MUTED, busy=b.id == self.current or b.id in self.queue,
                      can_open=(bool(b.pdf) and Path(b.pdf).exists(), bool(b.epub) and Path(b.epub).exists()))
        if b.id == self.current:
            info = self.progress_info
            st.colour = style.ACCENT
            if self.phase in ("ocr", "rest", "paused", "battery") and info.get("total"):
                st.status = f"Reading pages — {info['done']} of {info['total']}"
                st.progress = (info["done"], info["total"])
                left = self.book_seconds_left(b)
                if self.phase == "rest":
                    st.status, st.colour = f"Resting to cool down — {fmt_clock(self.rest_until - time.monotonic())}", style.WARN
                    st.detail = f"{info['done']} of {info['total']} pages read"
                elif self.phase == "battery":
                    st.status, st.colour = f"Battery low ({self.battery_pct} %) — paused", style.BAD
                    st.detail = "plug in the charger — it continues by itself"
                elif self.phase == "paused":
                    st.status, st.colour = "Paused", style.WARN
                    st.detail = f"{info['done']} of {info['total']} pages read — press Resume"
                else:
                    st.detail = f"about {fmt_duration(left)} left for this book" if left else "working out the time left…"
            else:
                st.status = STAGE_TEXT.get(self.phase, "Working…")
                st.progress = (0, 0)
                st.detail = "a minute or two" if self.phase in ("assemble", "typeset", "epub") else ""
        elif b.id in self.queue:
            n = self.queue.index(b.id)
            st.status = "In line — next" if n == 0 else f"In line — {n + 1}th" if n > 2 else f"In line — {('2nd', '3rd')[n - 1]}"
            left = self.book_seconds_left(b)
            st.detail = f"about {fmt_duration(left)} once it starts" if left else ""
        elif b.error:
            st.status, st.colour = "Needs attention", style.BAD
            st.detail = "open ⋯ → Check book to see why"
        elif self.is_ready(b):
            st.status, st.colour = ("Ready — " + b.look, style.WARN) if b.look else ("Ready ✓", style.OK)
            made = [f"{kind} {size}" for kind, size in (("PDF", fmt_size(b.pdf)), ("EPUB", fmt_size(b.epub))) if size]
            st.detail = " · ".join([f"made {datetime.fromisoformat(b.built):%d %b, %H:%M}"] + made)
            if b.look:
                st.detail = "open ⋯ → Check book · " + st.detail
        elif b.built:
            st.status, st.colour = "Changed — make it again", style.WARN
            st.detail = "takes a moment, no reading again"
        elif read and read < b.pages:
            st.status, st.colour = f"Stopped at page {read} of {b.pages}", style.WARN
            st.progress = (read, b.pages)
            st.detail = "Make continues from here"
        elif read >= b.pages > 0:
            st.status, st.colour = "Pages read — make to finish", style.WARN
        else:
            st.status = "Not started" if b.ticked else "Not ticked — won't be made"
        return st

    # ---------- time left ----------

    def _rate(self) -> float:
        """Seconds per page while reading: measured on this run, else what this computer did last time."""
        info = self.progress_info
        read = info.get("done", 0) - info.get("start_done", 0)
        if read > 0:
            return (info["t"] - info["start_t"] - info.get("excluded", 0.0)) / read
        return self.settings.sec_per_page

    def _cool_factor(self) -> float:
        s = self.settings
        return (s.work_minutes + s.rest_minutes) / s.work_minutes if s.cooldown and s.work_minutes else 1.0

    def book_seconds_left(self, b: store.Book) -> float | None:
        rate = self._rate()
        if b.kind == "digital":
            return AFTER_READING
        done = self.progress_info.get("done", 0) if b.id == self.current else store.ocr_pages_done(b)
        if not rate:
            return None
        return max(0, b.pages - done) * rate * self._cool_factor() + AFTER_READING

    def run_seconds_left(self) -> float | None:
        ids = ([self.current] if self.current else []) + self.queue
        parts = [self.book_seconds_left(self.library.get(i)) for i in ids if self.library.get(i)]
        if any(p is None for p in parts):
            return None
        rests = len(self.queue) * self.settings.between_minutes * 60 if self.settings.cooldown else 0
        if self.between_until:
            rests += max(0, self.between_until - time.monotonic())
        return sum(parts) + rests

    # ---------- refreshing ----------

    def _refresh_row(self, b: store.Book):
        self.list.row(b.id).show_state(self.row_state(b), current=b.id == self.selected and self.panel.isVisible())

    def _refresh_all(self):
        self._refresh_power()
        for b in self.library.books:
            self._refresh_row(b)
        self._refresh_panel()
        self._refresh_select_bar()
        self._refresh_run_card()

    def _refresh_panel(self, keep_edits: bool = True):
        book = self.library.get(self.selected or "")
        busy = book is not None and (book.id == self.current or book.id in self.queue)
        html = self.status_html(book) if book else ""
        if keep_edits and self.panel.book is book and book is not None:
            self.panel.update_state(html, busy)
        else:
            self.panel.show_book(book, self.thumbs.get(book.id) if book else None, html, busy)

    def status_html(self, b: store.Book) -> str:
        st = self.row_state(b)
        return f"<span style='color:{st.colour}'><b>{st.status}</b></span><br>{st.detail}"

    def _refresh_select_bar(self):
        books = self.library.books
        ticked = sum(b.ticked for b in books)
        self.select_all.setChecked(bool(books) and ticked == len(books))
        self.select_all.setEnabled(bool(books))
        self.select_count.setText(f"{ticked} of {len(books)} ticked" if books else "")
        self.bulk_btn.setVisible(ticked > 0 and not self.runner and not self.between_until)
        self.details_btn.setText("Hide details ▸" if self.panel.isVisible() else "◂ Show details")
        self.details_btn.setVisible(bool(books))

    def _refresh_run_card(self):
        books = self.library.books
        todo = [b for b in books if b.ticked and self.needs_work(b) and b.id not in self.queue]
        running = self.runner is not None or bool(self.between_until)
        self.make_btn.setVisible(not running)
        self.make_btn.setEnabled(bool(todo))
        self.make_btn.setText(f"▶  Make ticked books ({len(todo)})" if todo else "▶  Make ticked books")
        self.pause_btn.setVisible(self.runner is not None and self.phase in ("ocr", "paused", "starting"))
        self.pause_btn.setText("Resume" if self.phase == "paused" else "Pause")
        failed = self.failed_books()
        self.retry_btn.setVisible(bool(failed))
        self.retry_btn.setText(f"Retry failed ({len(failed)})")
        self.report_btn.setVisible(not running and bool(self.report_books()))
        self.skip_btn.setVisible(running and bool((self.runner and self.rest_until) or self.between_until))
        self.stop_btn.setVisible(running)
        if not running:
            ready = sum(self.is_ready(b) for b in books)
            self.run_bar.setVisible(bool(books))
            self.run_bar.setRange(0, max(1, len(books)))
            self.run_bar.setValue(ready)
            if not books:
                self.run_title.setText("Welcome")
                self.run_line.setText("Add scanned books (PDFs) with <b>＋ Add books</b> to begin.")
            else:
                self.run_title.setText(self.finished_note or f"{ready} of {len(books)} books ready")
                waiting = sum(1 for b in books if self.needs_work(b))
                self.run_line.setText((f"{len(todo)} ticked book{'s' if len(todo) != 1 else ''} to make — press "
                                       "<b>Make ticked books</b>." if todo else
                                       "Tick the books you want to make." if waiting else "Everything is made. ✓"))
            self.run_numbers.setText("")
            return
        # A run is going: whole-run progress in pages
        run_books = [self.library.get(i) for i in self.run_ids if self.library.get(i)]
        total = sum(b.pages for b in run_books)
        done = sum(b.pages for b in run_books if b.id in self.run_done)
        cur = self.library.get(self.current) if self.current else None
        if cur:
            past_reading = self.phase in ("assemble", "typeset", "epub") or cur.kind == "digital"
            done += cur.pages if past_reading else self.progress_info.get("done", 0)
        self.run_bar.setVisible(True)
        self.run_bar.setRange(0, max(1, total))
        self.run_bar.setValue(done)
        n_done = len(self.run_done)
        title = f"Making {len(run_books)} book{'s' if len(run_books) != 1 else ''} — {n_done} done"
        left = self.run_seconds_left()
        self.run_numbers.setText(f"{done:,} of {total:,} pages" + (f" · about {fmt_duration(left)} left for the whole run"
                                                                   if left else " · working out the time left…"))
        if self.between_until:
            nxt = self.library.get(self.queue[0]) if self.queue else None
            self.run_title.setText(title)
            self.run_line.setText(f"Resting before the next book{f' (<i>{nxt.title}</i>)' if nxt else ''} — starts in "
                                  f"<b>{fmt_clock(self.between_until - time.monotonic())}</b>")
            return
        self.run_title.setText(f"{title} · now: <i>{cur.title}</i>" if cur else title)
        st = self.row_state(cur) if cur else None
        self.run_line.setText(f"{st.status}" + (f" · {st.detail}" if st and st.detail else "") if st else "Stopping…")

    def _tick(self):
        if self.between_until and time.monotonic() >= self.between_until:
            self.start_next()
        self._hold_awake(self.runner is not None or bool(self.between_until))
        if time.monotonic() - self.power_seen > 10:
            self.power_seen = time.monotonic()
            self._refresh_power()
        if self.runner or self.between_until:
            if self.current:
                self._refresh_row(self.library.get(self.current))
            self._refresh_run_card()

    def _hold_awake(self, on: bool):
        """The worker keeps the computer awake only while it makes a book; in the rest between books no worker runs, and a
        sleeping laptop would stop the whole run until someone wakes it — so the window holds it awake from start to finish."""
        if on and self.awake is None:
            self.awake = ExitStack()
            self.awake.enter_context(keep_awake())
        elif not on and self.awake is not None:
            self.awake.close()
            self.awake = None

    def _refresh_power(self):
        """While books are being made: plugged in (keep the lid open) or on battery (plug in; pauses below 15 %)."""
        working = self.runner is not None or bool(self.between_until)
        b = battery() if working else None
        self.power_line.setVisible(b is not None)
        if b is None:
            return
        percent, plugged = b
        if plugged:
            self.power_line.setText(f"<span style='color:{style.OK}'>🔌 Plugged in</span> · the computer stays awake while books are "
                                    "made — keep the lid open")
        else:
            self.power_line.setText(f"<span style='color:{style.WARN}'><b>🔋 On battery ({percent} %) — please plug in the charger.</b></span> "
                                    f"Book Studio pauses by itself below {LOW_BATTERY} %.")

    # ---------- rows: click, tick, menu ----------

    def _row_clicked(self, book_id: str):
        self.panel.flush()
        old, self.selected = self.selected, book_id
        if not self.panel.isVisible():
            self.set_details(True)
        for i in {old, book_id} - {None}:
            if self.library.get(i):
                self._refresh_row(self.library.get(i))
        self._refresh_panel(keep_edits=False)

    def _row_ticked(self, book_id: str, on: bool):
        self.library.get(book_id).ticked = on
        self.library.save()
        self._refresh_all()

    def _select_all_clicked(self, on: bool):
        for b in self.library.books:
            if b.id != self.current and b.id not in self.queue:
                b.ticked = on
        self.library.save()
        self._refresh_all()

    def _ticked_books(self) -> list[store.Book]:
        return [b for b in self.library.books if b.ticked and b.id != self.current and b.id not in self.queue]

    def _open_file(self, book_id: str, kind: str):
        b = self.library.get(book_id)
        f = b.pdf if kind == "pdf" else b.epub
        if f and Path(f).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(f))

    def _row_menu(self, book_id: str, pos):
        b = self.library.get(book_id)
        busy = b.id == self.current or b.id in self.queue
        menu = QMenu(self)
        menu.addAction("Retry now" if b.error else "Make this book now", lambda: self.make_now([b.id])).setEnabled(not busy and not self.is_ready(b))
        menu.addAction("Details", lambda: self._row_clicked(b.id))
        menu.addAction("Check book", lambda: self.show_check(b.id))
        if self.settings.expert:
            menu.addAction("Book fixes…", lambda: self.show_fixes(b.id)).setEnabled(not busy)
        menu.addSeparator()
        menu.addAction("Open PDF", lambda: self._open_file(b.id, "pdf")).setEnabled(bool(b.pdf) and Path(b.pdf).exists())
        menu.addAction("Open EPUB", lambda: self._open_file(b.id, "epub")).setEnabled(bool(b.epub) and Path(b.epub).exists())
        menu.addSeparator()
        menu.addAction("Clear working files (free disk space)", lambda: self.clear_work(b)).setEnabled(not busy)
        menu.addAction("Remove from Book Studio", lambda: self.remove_book(b)).setEnabled(not busy)
        menu.exec(pos)

    def _book_edited(self, book_id: str):
        self.library.save()
        self._refresh_row(self.library.get(book_id))
        self._refresh_panel()
        self._refresh_run_card()

    def _cover_changed(self, book_id: str):
        b = self.library.get(book_id)
        self.library.save()
        self.thumbnail(b, fresh=True)
        self._refresh_row(b)
        self.panel.show_book(b, self.thumbs[b.id], self.status_html(b))
        self._refresh_run_card()

    def clear_work(self, *books: store.Book):
        if not books:
            return
        pages = sum(store.ocr_pages_done(b) for b in books)
        what = f"“{books[0].title}”" if len(books) == 1 else f"{len(books)} books"
        if QMessageBox.question(self, "Clear working files",
                                f"Delete the {pages} pages already read for {what}?\n\nFinished PDFs and EPUBs stay where they are, "
                                "but changing these books later would mean reading all their pages again.") == QMessageBox.Yes:
            for b in books:
                store.clear_work(b)
            self._refresh_all()

    def remove_book(self, *books: store.Book):
        if not books:
            return
        what = f"“{books[0].title}”" if len(books) == 1 else f"these {len(books)} books"
        if QMessageBox.question(self, "Remove", f"Remove {what} from Book Studio?\n\n"
                                "Your original PDFs and the finished PDFs/EPUBs are not deleted.") == QMessageBox.Yes:
            for b in books:
                self.library.remove(b)
                self.list.remove(b.id)
                self.thumbs.pop(b.id, None)
            if self.selected not in {b.id for b in self.library.books}:
                self.selected = self.library.books[0].id if self.library.books else None
            self._refresh_all()

    # ---------- dialogs ----------

    def show_settings(self):
        dlg = SettingsDialog(self.settings, self)
        dlg.redoSetup.connect(self.redo_setup)
        dlg.checkUpdates.connect(self.show_updates)
        if dlg.exec():
            self.library.write_meta()  # imported book settings may change books
            self.panel.fixes.setVisible(self.settings.expert)
            self._refresh_all()

    def redo_setup(self):
        if self.runner:
            QMessageBox.information(self, "Busy", "Stop the current book first.")
            return
        shutil.rmtree(paths.WORK_DIR / "tools" / "llama.cpp", ignore_errors=True)
        SetupDialog(self.settings, self).exec()

    def show_check(self, book_id: str):
        CheckDialog(self.library.get(book_id), self).exec()

    def show_fixes(self, book_id: str):
        b = self.library.get(book_id)
        if FixesDialog(b, self).exec():
            self.library.save()
            self._refresh_all()

    def open_folder(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def show_updates(self):
        dlg = UpdatesDialog(self.settings, busy=self.runner is not None or bool(self.between_until), parent=self)
        dlg.exec()
        if dlg.restart:
            QApplication.quit()

    def show_output_folders(self):
        OutputDialog(self.settings, self).exec()

    # ---------- making books ----------

    def make_books(self, only: list[str] | None = None):
        """Makes the given books, or every ticked book that isn't ready, one after another."""
        self.panel.flush()
        if not (engine.engine_ready() and engine.model_ready()):
            SetupDialog(self.settings, self).exec()
            if not (engine.engine_ready() and engine.model_ready()):
                return
        todo = only or [b.id for b in self.library.books if b.ticked and self.needs_work(b)]
        todo = [i for i in todo if i != self.current and i not in self.queue]
        if not todo:
            if not self.runner:
                QMessageBox.information(self, "Nothing to do", "Tick the books to make first." if self.library.books else "Add a book first.")
            return
        if not self.runner and not self.between_until:  # a new run
            self.run_ids, self.run_done, self.finished_note = [], [], ""
            b = battery()
            if b and not b[1]:
                QMessageBox.information(self, "Plug in the charger",
                                        f"This computer is on battery ({b[0]} %). Making books takes hours — please plug in the charger "
                                        "and keep the lid open.\n\nBook Studio keeps the computer awake while it works, and pauses by itself "
                                        f"if the battery drops below {LOW_BATTERY} %.")
        self.run_ids += todo
        self.queue += todo
        self.stop_requested = False
        if not self.runner and not self.between_until:
            self.start_next()
        self._refresh_all()

    def start_next(self):
        self.between_until = 0.0
        if not self.queue:
            self.current = None
            self._refresh_all()
            return
        book_id = self.queue.pop(0)
        b = self.library.get(book_id)
        if b is None:
            return self.start_next()
        b.error = ""
        self.library.save()
        self.current_hash = store.fingerprint(b, store.builtin_meta())
        store.write_json(paths.CONTROL_FILE, {})
        self.current, self.phase, self.progress_info, self.last_event = book_id, "starting", {}, ""
        self.did_read_pages = False
        self.runner = WorkerRunner(book_id, engine.worker_env(self.settings), self)
        self.runner.event.connect(self._on_event)
        self.runner.ended.connect(self._on_ended)
        self.runner.start()
        self._refresh_all()

    def _on_event(self, ev: dict):
        kind = ev["event"]
        self.last_event = kind
        b = self.library.get(self.current)
        if kind == "kind":
            b.kind = ev["kind"]
            self.library.save()
        elif kind == "ocr":
            now = time.monotonic()
            info = self.progress_info
            if not info:
                info.update(start_t=now, start_done=ev["done"], excluded=0.0)
            elif ev["done"] > info["start_done"]:
                self.did_read_pages = True
            info.update(done=ev["done"], total=ev["total"], t=now)
            if self.phase not in ("rest", "paused") and ev["done"] > info["start_done"]:
                self.phase = "ocr"
                self.settings.sec_per_page = round(self._rate(), 2)  # remembered for the next run's estimates
                self.settings.save()
        elif kind == "stage":
            self.phase = ev["stage"]
            if self.phase == "typeset":  # the worker reads the book's settings now: edits made until here are in this build
                self.panel.flush()
                self.library.save()
                self.current_hash = store.fingerprint(b, store.builtin_meta())
        elif kind == "rest":
            self.phase, self.rest_until = "rest", time.monotonic() + ev["seconds"]
            self.progress_info["rest_start"] = time.monotonic()
        elif kind == "battery":
            self.phase, self.battery_pct = "battery", ev["percent"]
            self.progress_info["rest_start"] = time.monotonic()
            QApplication.alert(self)
            self._refresh_power()
        elif kind == "paused":
            self.phase = "paused"
            self.progress_info["rest_start"] = time.monotonic()
        elif kind == "resumed":
            started = self.progress_info.pop("rest_start", None)
            if started:
                self.progress_info["excluded"] = self.progress_info.get("excluded", 0.0) + time.monotonic() - started
            self.phase, self.rest_until = "ocr", 0.0
        elif kind == "done":
            b.built = datetime.now().isoformat(timespec="seconds")
            b.built_hash = self.current_hash
            b.pdf, b.epub, b.error, b.look = ev["pdf"], ev["epub"], "", ev.get("look", "")
            self.library.save()
        elif kind == "error":
            b.error = ev["message"]
            self.library.save()
        self._refresh_row(b)
        if b.id == self.selected:
            self._refresh_panel()
        self._refresh_run_card()

    def _on_ended(self, code: int, tail: str):
        b = self.library.get(self.current) if self.current else None
        if b and self.last_event not in ("done", "error", "stopped") and not self.stop_requested:
            b.error = "Book Studio stopped working on this book unexpectedly. Make continues where it stopped."
            if tail:
                (paths.LOGS_DIR / f"{b.id}.log").open("a", encoding="utf-8").write(tail + "\n")
            self.library.save()
            engine.stop_stray_server()
        if b and self.delete_after_stop == b.id:
            store.clear_work(b)
            b.error = ""
            self.library.save()
        self.delete_after_stop = None
        if b and self.last_event == "done":
            self.run_done.append(b.id)
        self.runner = None
        finished = self.current
        self.current, self.phase, self.rest_until = None, "", 0.0
        if self.stop_requested:
            self.queue.clear()
            self.finished_note = "Stopped"
        if self.queue:
            if self.did_read_pages and self.settings.cooldown and self.settings.between_minutes > 0 and not self.retry_now:
                self.between_until = time.monotonic() + self.settings.between_minutes * 60
            else:
                self.start_next()
            self.retry_now = False
        elif finished and not self.stop_requested:
            QApplication.alert(self)
            failed = [i for i in self.run_ids if i not in self.run_done]
            if not self.run_done:
                self.finished_note = "None of the books could be made — open ⋯ → Check book on one to see why, or press Retry failed"
            else:
                self.finished_note = (f"Done — {len(self.run_done)} book{'s' if len(self.run_done) != 1 else ''} made ✓" +
                                      (f", {len(failed)} need{'s' if len(failed) == 1 else ''} attention — press Retry failed" if failed else ""))
        self._refresh_all()

    def report_books(self) -> list[store.Book]:
        """The books of the last run; before any run, every book that was made or failed."""
        ids = self.run_ids or [b.id for b in self.library.books if b.built or b.error]
        return [b for b in (self.library.get(i) for i in ids) if b]

    def copy_run_report(self):
        QApplication.clipboard().setText(report.run_report(self.report_books()))
        self.report_btn.setText("Copied ✓")
        QTimer.singleShot(3000, lambda: self.report_btn.setText("Copy report"))

    def failed_books(self) -> list[str]:
        """Books whose last try failed and that aren't already in line."""
        return [b.id for b in self.library.books if b.error and b.id != self.current and b.id not in self.queue]

    def retry_failed(self):
        self.make_now(self.failed_books())

    def make_now(self, ids: list[str]):
        """These books go first ("Retry failed", "Retry now", "Make this book now"). A book being read stops after the pages
        in hand (they're kept) and continues after them; one in its last steps (chapters, PDF, EPUB — minutes) finishes first."""
        ids = [i for i in ids if i != self.current]
        if not ids:
            return
        if not self.runner and not self.between_until:
            self.make_books(ids)
            return
        self.queue = ids + [i for i in self.queue if i not in ids]
        self.run_ids += [i for i in ids if i not in self.run_ids]
        if self.runner and self.phase in ("ocr", "rest", "paused", "battery") and self.current not in self.queue:  # not yet stopping
            self.queue.insert(len(ids), self.current)
            self.retry_now = True
            store.write_json(paths.CONTROL_FILE, {"stop": True})
            self.run_line.setText("Pausing this book after the pages being read now — it continues after the ones you asked for…")
        elif self.between_until:
            self.start_next()
        self._refresh_all()

    def toggle_pause(self):
        state = json.loads(paths.CONTROL_FILE.read_text()) if paths.CONTROL_FILE.exists() else {}
        state["paused"] = not state.get("paused")
        store.write_json(paths.CONTROL_FILE, state)
        self.pause_btn.setText("Resume" if state["paused"] else "Pause")
        if state["paused"]:
            self.run_line.setText("Pausing after the pages being read now…")

    def skip_rest(self):
        if self.between_until:
            self.start_next()
            return
        state = json.loads(paths.CONTROL_FILE.read_text()) if paths.CONTROL_FILE.exists() else {}
        store.write_json(paths.CONTROL_FILE, state | {"skip_rest": True})
        QTimer.singleShot(3000, lambda: store.write_json(paths.CONTROL_FILE, {k: v for k, v in state.items() if k != "skip_rest"}))

    def stop(self):
        if self.between_until:
            self.between_until = 0.0
            self.queue.clear()
            self.finished_note = "Stopped"
            self._refresh_all()
            return
        b = self.library.get(self.current)
        box = QMessageBox(self)
        box.setWindowTitle("Stop")
        box.setText(f"Stop making “{b.title}”?")
        box.setInformativeText("Keep progress: the pages already read are kept, and Make continues from there.\n\n"
                               "Delete progress: everything done on this book so far is thrown away; next time it starts from page 1. "
                               "Finished PDFs and EPUBs are not touched.\n\nBooks still in line are not started.")
        keep = box.addButton("Stop, keep progress", QMessageBox.AcceptRole)
        delete = box.addButton("Stop, delete progress", QMessageBox.DestructiveRole)
        box.addButton("Keep going", QMessageBox.RejectRole)
        box.setDefaultButton(keep)
        box.exec()
        if box.clickedButton() not in (keep, delete):
            return
        self.stop_requested = True
        self.delete_after_stop = b.id if box.clickedButton() is delete else None
        if self.phase in ("ocr", "rest", "paused"):
            # Between page batches the OCR engine shuts down cleanly; a batch takes a few minutes at most
            store.write_json(paths.CONTROL_FILE, {"stop": True})
            self.run_line.setText("Stopping after the pages being read now…")
        else:
            # Starting up, reading a digital PDF, or making the PDF/EPUB: nothing to save half-way, so stop at once
            self.runner.kill()
            engine.stop_stray_server()
            self.run_line.setText("Stopping…")

    # ---------- quitting ----------

    def closeEvent(self, e):
        self.panel.flush()
        if self.runner:
            if QMessageBox.question(self, "Quit Book Studio", "A book is being made. Quit anyway?\n\n"
                                    "Pages already read are kept; Make continues from there next time.") != QMessageBox.Yes:
                e.ignore()
                return
            store.write_json(paths.CONTROL_FILE, {"stop": True})
            self.runner.kill()
            self.runner.wait(5000)
            engine.stop_stray_server()
        self._hold_awake(False)
        e.accept()
