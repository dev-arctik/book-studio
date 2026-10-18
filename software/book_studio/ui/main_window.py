# software/book_studio/ui/main_window.py
# The main window: a toolbar (Add books · Make books · Open finished · Settings), the shelf of book covers, the selected
# book's panel, and a status bar that says in plain words what is happening ("Reading page 368 of 594 · about 2 h 40 min left",
# "Resting to cool down — 11:42"). Runs books one after another, each in a worker process, with the cool-down rests in between.

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps
from PySide6.QtCore import QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QSplitter, QVBoxLayout, QWidget)

from .. import APP_NAME, engine, paths, store, updater
from . import style
from .book_panel import BookPanel
from .cover_grid import CoverGrid
from .dialogs import CheckDialog, FixesDialog, OutputDialog, SettingsDialog, SetupDialog, Task, offer_update

STAGE_TEXT = {
    "starting": "Starting the page reader (this can take a minute)…",
    "text": "Reading the text of this digital PDF…",
    "assemble": "Putting the chapters together…",
    "typeset": "Making the PDF…",
    "epub": "Making the EPUB…",
}


def fmt_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{max(minutes, 1)} min"


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
        self.phase = ""
        self.progress_info: dict = {}
        self.rest_until = 0.0
        self.between_until = 0.0
        self.stop_requested = False
        self.last_event = ""
        self.did_read_pages = False
        self.delete_after_stop: str | None = None  # book whose progress to throw away once it has stopped
        self.current_hash = ""  # the book's settings when it started — edits made while it runs show as 'Changed' afterwards
        self.thumbs: dict[str, QPixmap] = {}

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(paths.ASSETS_DIR / "icon.png")))
        self.resize(1180, 760)
        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._toolbar())

        split = QSplitter()
        split.setHandleWidth(1)
        self.grid = CoverGrid(title_family)
        self.grid.itemSelectionChanged.connect(self._selection_changed)
        self.grid.filesDropped.connect(self.add_files)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        self.panel = BookPanel()
        self.panel.changed.connect(self._book_edited)
        self.panel.coverChanged.connect(self._cover_changed)
        self.panel.showCheck.connect(self.show_check)
        self.panel.fixes.setVisible(self.settings.expert)
        self.panel.showFixes.connect(self.show_fixes)
        self.panel.makeThis.connect(lambda bid: self.make_books([bid]))
        split.addWidget(self.grid)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 1)
        split.setSizes([800, 380])
        lay.addWidget(split, 1)
        lay.addWidget(self._statusbar())

        self.ticker = QTimer(self, interval=1000)  # countdowns for rests
        self.ticker.timeout.connect(self._tick)
        self.ticker.start()
        for b in self.library.books:
            self._refresh_tile(b)
        self._refresh_status()
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
        self.make_btn = self._tool("▶  Make books", lambda: self.make_books())
        self.make_btn.setObjectName("Primary")
        self.open_btn = self._tool("Open finished books")
        open_menu = QMenu(self)
        open_menu.addAction("PDF folder", lambda: self.open_folder(self.settings.pdf_folder()))
        open_menu.addAction("EPUB folder", lambda: self.open_folder(self.settings.epub_folder()))
        self.open_btn.setMenu(open_menu)
        self.folders_btn = self._tool("Output folders…", self.show_output_folders)
        self.settings_btn = self._tool("Settings", self.show_settings)
        for b in (self.add_btn, self.make_btn, self.open_btn, self.folders_btn):
            h.addWidget(b)
        h.addStretch()
        h.addWidget(self.settings_btn)
        return bar

    def _tool(self, text, slot=None) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("Tool")
        if slot:  # buttons with a menu open it instead
            b.clicked.connect(slot)
        return b

    def _statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("StatusBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 10, 16, 10)
        col = QVBoxLayout()
        self.status_text = QLabel()
        self.status_text.setTextFormat(Qt.RichText)
        self.status_text.setMinimumHeight(self.status_text.fontMetrics().lineSpacing() * 2 + 4)  # room for the rest countdown line
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        col.addWidget(self.status_text)
        col.addWidget(self.progress)
        h.addLayout(col, 1)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.skip_btn = QPushButton("Skip the rest")
        self.skip_btn.clicked.connect(self.skip_rest)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop)
        for b in (self.pause_btn, self.skip_btn, self.stop_btn):
            h.addWidget(b)
        return bar

    # ---------- first run, updates ----------

    def _first_run(self):
        if not (engine.engine_ready() and engine.model_ready()):
            SetupDialog(self.settings, self).exec()
        if paths.IS_INSTALLED or os.environ.get("BOOK_STUDIO_CHECK_UPDATES"):
            QTimer.singleShot(3000, lambda: self.check_updates(quiet=True))

    def check_updates(self, quiet: bool):
        self._update_task = Task(lambda progress: updater.latest_release(), parent=self)

        def found(release):
            if release is None:
                if not quiet:
                    QMessageBox.information(self, "Updates", "You have the newest Book Studio.")
            elif not self.runner and offer_update(self, self.settings, release, quiet):
                QApplication.quit()
        self._update_task.succeeded.connect(found)
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
                    self._refresh_tile(book)
                else:
                    skipped += 1
        finally:
            QApplication.restoreOverrideCursor()
        if added:
            self.grid.setCurrentItem(self.grid.item_for(added[-1].id))
        if skipped:
            QMessageBox.information(self, "Already added", f"{skipped} of these books {'is' if skipped == 1 else 'are'} already in Book Studio.")
        self._refresh_status()

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

    def status_of(self, b: store.Book) -> tuple[str, str]:
        if b.id == self.current:
            if self.phase == "ocr" and self.progress_info:
                return f"Reading {100 * self.progress_info['done'] // max(1, self.progress_info['total'])} %", style.ACCENT
            return {"rest": ("Resting", style.MUTED), "paused": ("Paused", style.WARN), "starting": ("Starting…", style.ACCENT)}.get(
                self.phase, ("Making…", style.ACCENT))
        if b.id in self.queue:
            return "In line", style.MUTED
        if b.error:
            return "Needs attention", style.BAD
        if b.built:
            fresh = b.built_hash == store.fingerprint(b, store.builtin_meta()) and Path(b.pdf).exists()
            return ("Ready", style.OK) if fresh else ("Changed", style.WARN)
        done = store.ocr_pages_done(b)
        if done == 0:
            return "New", style.MUTED
        return (f"Read {100 * done // max(1, b.pages)} %", style.WARN) if done < b.pages else ("Pages read", style.WARN)

    def needs_work(self, b: store.Book) -> bool:
        return self.status_of(b)[0] != "Ready"

    def status_html(self, b: store.Book) -> str:
        label, colour = self.status_of(b)
        detail = {
            "New": "Not started yet. Press <b>Make books</b> (or the button below) to start.",
            "In line": "Waiting for the book before it to finish.",
            "Starting…": "Being made now — the bar at the bottom shows how far it is.",
            "Making…": "Being made now — the bar at the bottom shows how far it is.",
            "Resting": "Resting to let the computer cool down; it continues by itself.",
            "Paused": "Paused — press Resume at the bottom to go on.",
            "Ready": f"Finished {b.built.replace('T', ' at ')[:16]}. The PDF and EPUB are in your finished-books folder.",
            "Changed": "You changed something since it was made. Make it again to update the PDF and EPUB — it only takes a moment.",
            "Needs attention": b.error,
            "Pages read": "All pages are read. Make it to put the book together.",
        }.get(label, "")
        if label.startswith("Reading "):
            detail = "Being made now — the bar at the bottom shows how far it is."
        if label.startswith("Read ") and b.id != self.current:
            detail = f"{store.ocr_pages_done(b)} of {b.pages} pages read. Press <b>Make books</b> to continue where it stopped."
        return f"<span style='color:{colour}'><b>{label}</b></span><br>{detail}"

    def _refresh_tile(self, b: store.Book, fresh_cover: bool = False):
        self.grid.set_book(b.id, b.title, self.thumbnail(b, fresh_cover), self.status_of(b))

    def _refresh_all(self):
        for b in self.library.books:
            self._refresh_tile(b)
        self._selection_changed(keep_edits=True)
        self._refresh_status()

    def _selection_changed(self, keep_edits: bool = False):
        if not keep_edits:
            self.panel.flush()
        book = self.library.get(self.grid.selected_id() or "")
        busy = book is not None and (book.id == self.current or book.id in self.queue)
        if keep_edits and self.panel.book is book and book is not None:
            self.panel.update_state(self.status_html(book), busy)
        else:
            self.panel.show_book(book, self.thumbs.get(book.id) if book else None, self.status_html(book) if book else "", busy)

    def _book_edited(self, book_id: str):
        self.library.save()
        b = self.library.get(book_id)
        b.error = "" if b.error and not b.built else b.error
        self._refresh_tile(b)
        self.panel.update_state(self.status_html(b), False)
        self._refresh_status()

    def _cover_changed(self, book_id: str):
        b = self.library.get(book_id)
        self.library.save()
        self._refresh_tile(b, fresh_cover=True)
        self.panel.show_book(b, self.thumbs[b.id], self.status_html(b))
        self._refresh_status()

    def _context_menu(self, pos):
        item = self.grid.itemAt(pos)
        if not item:
            return
        if not item.isSelected():
            self.grid.setCurrentItem(item)
        books = [self.library.get(i) for i in self.grid.selected_ids()]
        busy = any(b.id == self.current or b.id in self.queue for b in books)
        menu = QMenu(self)
        if len(books) > 1:  # several selected (⌘/Ctrl-click or Shift-click)
            menu.addAction(f"Make these {len(books)} books", lambda: self.make_books([b.id for b in books])).setEnabled(not busy)
            menu.addSeparator()
            menu.addAction(f"Clear working files of {len(books)} books", lambda: self.clear_work(*books)).setEnabled(not busy)
            menu.addAction(f"Remove {len(books)} books from Book Studio", lambda: self.remove_book(*books)).setEnabled(not busy)
            menu.exec(self.grid.viewport().mapToGlobal(pos))
            return
        b = books[0]
        menu.addAction("Make this book now", lambda: self.make_books([b.id])).setEnabled(not busy)
        menu.addSeparator()
        menu.addAction("Open PDF", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(b.pdf))).setEnabled(Path(b.pdf).exists() if b.pdf else False)
        menu.addAction("Open EPUB", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(b.epub))).setEnabled(Path(b.epub).exists() if b.epub else False)
        menu.addAction("Check book", lambda: self.show_check(b.id))
        if self.settings.expert:
            menu.addAction("Book fixes…", lambda: self.show_fixes(b.id)).setEnabled(not busy)
        menu.addSeparator()
        menu.addAction("Clear working files (free disk space)", lambda: self.clear_work(b)).setEnabled(not busy)
        menu.addAction("Remove from Book Studio", lambda: self.remove_book(b)).setEnabled(not busy)
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def clear_work(self, *books: store.Book):
        pages = sum(store.ocr_pages_done(b) for b in books)
        what = f"“{books[0].title}”" if len(books) == 1 else f"{len(books)} books"
        if QMessageBox.question(self, "Clear working files",
                                f"Delete the {pages} pages already read for {what}?\n\nFinished PDFs and EPUBs stay where they are, "
                                "but changing these books later would mean reading all their pages again.") == QMessageBox.Yes:
            for b in books:
                store.clear_work(b)
            self._refresh_all()

    def remove_book(self, *books: store.Book):
        what = f"“{books[0].title}”" if len(books) == 1 else f"these {len(books)} books"
        if QMessageBox.question(self, "Remove", f"Remove {what} from Book Studio?\n\n"
                                "Your original PDFs and the finished PDFs/EPUBs are not deleted.") == QMessageBox.Yes:
            for b in books:
                self.library.remove(b)
                self.grid.takeItem(self.grid.row(self.grid.item_for(b.id)))
                self.thumbs.pop(b.id, None)
            self._selection_changed()
            self._refresh_status()

    # ---------- dialogs ----------

    def show_settings(self):
        dlg = SettingsDialog(self.settings, self)
        dlg.redoSetup.connect(self.redo_setup)
        dlg.checkUpdates.connect(lambda: self.check_updates(quiet=False))
        if dlg.exec():
            self.library.write_meta()  # imported book settings may change books
            self.panel.fixes.setVisible(self.settings.expert)
            self._refresh_all()

    def redo_setup(self):
        if self.runner:
            QMessageBox.information(self, "Busy", "Stop the current book first.")
            return
        import shutil
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

    def show_output_folders(self):
        OutputDialog(self.settings, self).exec()

    # ---------- making books ----------

    def make_books(self, only: list[str] | None = None):
        self.panel.flush()
        if not (engine.engine_ready() and engine.model_ready()):
            SetupDialog(self.settings, self).exec()
            if not (engine.engine_ready() and engine.model_ready()):
                return
        todo = only or [b.id for b in self.library.books if self.needs_work(b)]
        todo = [i for i in todo if i != self.current and i not in self.queue]
        if not todo:
            if not self.runner:
                QMessageBox.information(self, "Nothing to do", "All books are ready." if self.library.books else "Add a book first.")
            return
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
        if kind == "ocr":
            now = time.monotonic()
            info = self.progress_info
            if not info:
                info.update(start_t=now, start_done=ev["done"], excluded=0.0)
            elif ev["done"] > info["start_done"]:
                self.did_read_pages = True
            info.update(done=ev["done"], total=ev["total"], t=now)
            if self.phase not in ("rest", "paused") and ev["done"] > info["start_done"]:
                self.phase = "ocr"
        elif kind == "stage":
            self.phase = ev["stage"]
        elif kind == "rest":
            self.phase, self.rest_until = "rest", time.monotonic() + ev["seconds"]
            self.progress_info["rest_start"] = time.monotonic()
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
            b.pdf, b.epub, b.error = ev["pdf"], ev["epub"], ""
            self.library.save()
        elif kind == "error":
            b.error = ev["message"]
            self.library.save()
        self._refresh_tile(b)
        self._selection_changed(keep_edits=True)
        self._refresh_status()

    def _on_ended(self, code: int, tail: str):
        b = self.library.get(self.current) if self.current else None
        if b and self.last_event not in ("done", "error", "stopped") and not self.stop_requested:
            b.error = "Book Studio stopped working on this book unexpectedly. Make books continues where it stopped."
            if tail:
                (paths.LOGS_DIR / f"{b.id}.log").open("a", encoding="utf-8").write(tail + "\n")
            self.library.save()
            engine.stop_stray_server()
        if b and self.delete_after_stop == b.id:
            store.clear_work(b)
            b.error = ""
            self.library.save()
        self.delete_after_stop = None
        self.runner = None
        finished = self.current
        self.current, self.phase, self.rest_until = None, "", 0.0
        if self.stop_requested:
            self.queue.clear()
        if b:
            self._refresh_tile(b)
        if self.queue:
            if self.did_read_pages and self.settings.cooldown and self.settings.between_minutes > 0:
                self.between_until = time.monotonic() + self.settings.between_minutes * 60
            else:
                self.start_next()
        elif finished and not self.stop_requested:
            ready = sum(1 for x in self.library.books if self.status_of(x)[0] == "Ready")
            QApplication.alert(self)
            self.status_done = f"✅ Done — {ready} of {len(self.library.books)} books are ready."
        self._refresh_all()

    def _tick(self):
        if self.between_until and time.monotonic() >= self.between_until:
            self.start_next()
        if self.rest_until or self.between_until or self.phase == "ocr":
            self._refresh_status()

    def toggle_pause(self):
        state = json.loads(paths.CONTROL_FILE.read_text()) if paths.CONTROL_FILE.exists() else {}
        state["paused"] = not state.get("paused")
        store.write_json(paths.CONTROL_FILE, state)
        self.pause_btn.setText("Resume" if state["paused"] else "Pause")
        if state["paused"]:
            self.status_text.setText("Pausing after the pages being read now…")

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
            self._refresh_all()
            return
        b = self.library.get(self.current)
        box = QMessageBox(self)
        box.setWindowTitle("Stop")
        box.setText(f"Stop making “{b.title}”?")
        box.setInformativeText("Keep progress: the pages already read are kept, and Make books continues from there.\n\n"
                               "Delete progress: everything done on this book so far is thrown away; next time it starts from page 1. "
                               "Finished PDFs and EPUBs are not touched.")
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
            self.status_text.setText("Stopping after the pages being read now…")
        else:
            # Starting up, reading a digital PDF, or making the PDF/EPUB: nothing to save half-way, so stop at once
            self.runner.kill()
            engine.stop_stray_server()
            self.status_text.setText("Stopping…")

    def _refresh_status(self):
        busy = self.runner is not None or bool(self.between_until)
        pending = sum(1 for b in self.library.books if self.needs_work(b) and b.id != self.current and b.id not in self.queue)
        self.make_btn.setText(f"▶  Make books ({pending})" if pending else "▶  Make books")
        self.make_btn.setEnabled(pending > 0 or not self.library.books)
        self.pause_btn.setVisible(self.runner is not None and self.phase in ("ocr", "paused", "starting"))
        self.pause_btn.setText("Resume" if self.phase == "paused" else "Pause")
        self.skip_btn.setVisible(bool(self.rest_until or self.between_until))
        self.stop_btn.setVisible(busy)
        self.progress.setVisible(busy)
        if self.between_until:
            nxt = self.library.get(self.queue[0]) if self.queue else None
            self.status_text.setText(f"Resting before the next book{f' (<i>{nxt.title}</i>)' if nxt else ''} — "
                                     f"starts in <b>{fmt_clock(self.between_until - time.monotonic())}</b>")
            self.progress.setRange(0, 0)
            return
        if not self.runner:
            text = getattr(self, "status_done", "")
            self.status_done = ""
            n = len(self.library.books)
            self.status_text.setText(text or (f"{n} book{'s' if n != 1 else ''} · {pending} to make" if n else
                                              "Add a scanned book (PDF) to begin."))
            return
        b = self.library.get(self.current)
        info = self.progress_info
        if self.phase in ("ocr", "rest", "paused") and info.get("total"):
            self.progress.setRange(0, info["total"])
            self.progress.setValue(info["done"])
            line = f"<i>{b.title}</i> — reading page {info['done']} of {info['total']}"
            read = info["done"] - info["start_done"]
            if read > 0 and self.phase == "ocr":
                spent = info["t"] - info["start_t"] - info.get("excluded", 0.0)
                left = spent / read * (info["total"] - info["done"])
                line += f" · about {fmt_duration(left)} left"
            if self.phase == "rest":
                line += f"<br>Resting to cool down — starts again in <b>{fmt_clock(self.rest_until - time.monotonic())}</b>"
            elif self.phase == "paused":
                line += "<br><b>Paused.</b> Press Resume to go on."
            self.status_text.setText(line)
        else:
            self.progress.setRange(0, 0)  # busy, no percentage
            self.status_text.setText(f"<i>{b.title}</i> — {STAGE_TEXT.get(self.phase, 'Working…')}")

    # ---------- quitting ----------

    def closeEvent(self, e):
        self.panel.flush()
        if self.runner:
            if QMessageBox.question(self, "Quit Book Studio", "A book is being made. Quit anyway?\n\n"
                                    "Pages already read are kept; Make books continues from there next time.") != QMessageBox.Yes:
                e.ignore()
                return
            store.write_json(paths.CONTROL_FILE, {"stop": True})
            self.runner.kill()
            self.runner.wait(5000)
            engine.stop_stray_server()
        e.accept()
