# software/book_studio/ui/dialogs.py
# Book Studio's dialogs: first-time setup (page reader + reading model + Desktop icon), Settings (output folder, cool-down,
# advanced cores/slots), Book fixes (advanced per-book options), Warnings (the report next to the scanned page it mentions)
# and the update prompt. Long jobs run in a Task thread so the window never freezes.

import json
import os
import re
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__, engine, paths, store, updater


class Task(QThread):
    """Runs fn(*args, progress) in the background; progress(text, 0..1) and the result come back as signals."""
    progress = Signal(str, float)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.succeeded.emit(self.fn(*self.args, lambda text, frac: self.progress.emit(text, frac)))
        except Exception as exc:  # noqa: BLE001 — shown to the user in plain words
            self.failed.emit(str(exc) or type(exc).__name__)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


# ---------- first-time setup ----------

class SetupDialog(QDialog):
    """Shown until the page reader and the reading model are on this computer. Needs internet once (or a USB copy of the model)."""

    def __init__(self, settings: store.Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.task: Task | None = None
        self.setWindowTitle("Welcome to Book Studio")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        title = QLabel("Welcome to Book Studio")
        title.setObjectName("H1")
        lay.addWidget(title)
        lay.addWidget(_hint("Two things are needed once on this computer. After this, Book Studio works without internet."))

        box1 = QGroupBox("1. The page reader")
        b1 = QVBoxLayout(box1)
        self.engine_text = QLabel()
        self.engine_text.setWordWrap(True)
        self.engine_bar = QProgressBar()
        self.engine_retry = QPushButton("Try again")
        self.engine_retry.clicked.connect(self.install_engine)
        b1.addWidget(self.engine_text)
        b1.addWidget(self.engine_bar)
        b1.addWidget(self.engine_retry)
        lay.addWidget(box1)

        box2 = QGroupBox("2. The reading model (1.4 GB)")
        b2 = QVBoxLayout(box2)
        self.model_text = QLabel()
        self.model_text.setWordWrap(True)
        self.model_bar = QProgressBar()
        row = QHBoxLayout()
        self.model_download = QPushButton("Download it")
        self.model_download.setObjectName("Primary")
        self.model_download.clicked.connect(self.download_model)
        self.model_folder = QPushButton("Load from a folder or USB stick…")
        self.model_folder.clicked.connect(self.load_model)
        row.addWidget(self.model_download)
        row.addWidget(self.model_folder)
        row.addStretch()
        b2.addWidget(self.model_text)
        b2.addWidget(self.model_bar)
        b2.addLayout(row)
        lay.addWidget(box2)

        self.shortcut = QCheckBox("Put a Book Studio icon on the Desktop")
        self.shortcut.setChecked(paths.IS_INSTALLED)
        self.shortcut.setVisible(paths.IS_INSTALLED)
        lay.addWidget(self.shortcut)

        self.done_btn = QPushButton("Start using Book Studio")
        self.done_btn.setObjectName("Primary")
        self.done_btn.clicked.connect(self.finish)
        lay.addWidget(self.done_btn, alignment=Qt.AlignRight)
        self.refresh()
        if not engine.engine_ready():
            self.install_engine()

    def refresh(self):
        e, m = engine.engine_ready(), engine.model_ready()
        busy = self.task is not None and self.task.isRunning()
        if e:
            self.engine_text.setText(f"✅ Ready — uses: {engine.engine_label(self.settings.engine)}")
            self.engine_bar.hide()
        self.engine_retry.setVisible(not e and not busy)
        if m:
            self.model_text.setText("✅ Ready")
            self.model_bar.hide()
        elif not busy:
            self.model_text.setText("Download it (needs internet, about 1.4 GB), or load it from a folder — for example a USB "
                                    "stick, or the Book Studio data folder copied from another computer.")
        self.model_download.setVisible(not m)
        self.model_folder.setVisible(not m)
        self.model_download.setEnabled(not busy)
        self.model_folder.setEnabled(not busy)
        self.done_btn.setEnabled(e and m and not busy)

    def _run(self, fn, label: QLabel, bar: QProgressBar, *args):
        self.task = Task(fn, *args, parent=self)
        bar.show()
        bar.setRange(0, 1000)
        self.task.progress.connect(lambda text, frac: (label.setText(text), bar.setValue(int(frac * 1000))))
        self.task.succeeded.connect(lambda _: self.refresh())
        self.task.failed.connect(lambda msg: (label.setText(f"⚠️ {msg}\nCheck the internet connection and try again."), self.refresh()))
        self.task.finished.connect(self.refresh)
        self.task.start()
        self.refresh()

    def install_engine(self):
        self.engine_text.setText("Finding the right page reader for this computer…")
        self._run(lambda progress: engine.install_engine(self.settings, progress), self.engine_text, self.engine_bar)

    def download_model(self):
        self._run(engine.download_model, self.model_text, self.model_bar)

    def load_model(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder that contains surya-2.gguf and surya-2-mmproj.gguf")
        if not folder:
            return
        files = engine.find_model_files(Path(folder))
        if len(files) < len(paths.MODEL_FILES):
            QMessageBox.warning(self, "Model not found", "That folder doesn't contain both model files:\n"
                                + "\n".join(paths.MODEL_FILES))
            return
        self._run(engine.copy_model, self.model_text, self.model_bar, files)

    def finish(self):
        if self.shortcut.isChecked():
            try:
                engine.create_shortcuts()
            except Exception as exc:  # noqa: BLE001 — the icon is a convenience; never block the app on it
                QMessageBox.information(self, "Desktop icon", f"The Desktop icon could not be made ({exc}).\n"
                                        "You can keep starting Book Studio from its folder.")
        self.accept()

    def reject(self):
        if self.task and self.task.isRunning():
            return  # downloads finish or fail on their own; closing mid-way would leave half a file
        super().reject()


# ---------- settings ----------

class SettingsDialog(QDialog):
    redoSetup = Signal()
    checkUpdates = Signal()

    def __init__(self, settings: store.Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(600)
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        general = QWidget()
        lay = QVBoxLayout(general)
        tabs.addTab(general, "General")

        out = QGroupBox("Finished books go to")
        o = QHBoxLayout(out)
        self.output = QLineEdit(settings.output_dir)
        browse = QPushButton("Change…")
        browse.clicked.connect(self._browse)
        o.addWidget(self.output, 1)
        o.addWidget(browse)
        lay.addWidget(out)

        cool = QGroupBox("Cool-down")
        c = QFormLayout(cool)
        self.cooldown = QCheckBox("Let the computer rest while it reads pages")
        self.cooldown.setChecked(settings.cooldown)
        c.addRow(self.cooldown)
        self.work = self._minutes(settings.work_minutes, 5, 600)
        self.rest = self._minutes(settings.rest_minutes, 1, 240)
        self.between = self._minutes(settings.between_minutes, 0, 600)
        c.addRow("Work for", self.work)
        c.addRow("then rest for", self.rest)
        c.addRow("Rest between books", self.between)
        c.addRow(_hint("Reading pages keeps the processor and graphics chip busy for hours; resting lets a laptop cool down. "
                       "Nothing is lost by resting or pausing."))
        self.cooldown.toggled.connect(lambda on: [w.setEnabled(on) for w in (self.work, self.rest, self.between)])
        self.cooldown.toggled.emit(settings.cooldown)
        lay.addWidget(cool)
        lay.addStretch()

        # Advanced: only for people who know what they change; the defaults suit most computers
        advanced = QWidget()
        adv = QVBoxLayout(advanced)
        tabs.addTab(advanced, "Advanced")
        speed = QGroupBox("Speed and heat")
        a = QFormLayout(speed)
        cpus = os.cpu_count() or 2
        self.cores = QSlider(Qt.Horizontal)
        self.cores.setRange(1, cpus)
        self.cores.setValue(min(settings.cores, cpus))
        self.cores_label = QLabel()
        self.cores.valueChanged.connect(lambda v: self.cores_label.setText(f"{v} of {cpus}"))
        self.cores.valueChanged.emit(self.cores.value())
        a.addRow("Processor cores", self._row(self.cores, self.cores_label))
        self.slots = QSlider(Qt.Horizontal)
        self.slots.setRange(1, 8)
        self.slots.setValue(settings.slots)
        self.slots_label = QLabel()
        self.slots.valueChanged.connect(lambda v: self.slots_label.setText(f"{v}  (about {1.2 + 0.13 * v:.1f} GB memory)"))
        self.slots.valueChanged.emit(self.slots.value())
        a.addRow("Pages read at once", self._row(self.slots, self.slots_label))
        a.addRow(_hint("Fewer cores and pages at once = cooler and quieter, but slower. 4 pages at once suits a 16 GB computer; "
                       "use 2 on an 8 GB one."))
        adv.addWidget(speed)
        tools = QGroupBox("Page reader and book settings")
        t = QFormLayout(tools)
        t.addRow("Page reader", QLabel(engine.engine_label(settings.engine)))
        redo = QPushButton("Set up the page reader again")
        redo.clicked.connect(lambda: (self.accept(), self.redoSetup.emit()))
        imp = QPushButton("Import book settings…")
        imp.setToolTip("A book_meta.json from Devansh with the settings for books that need special handling")
        imp.clicked.connect(self._import_meta)
        upd = QPushButton("Check for updates")
        upd.clicked.connect(lambda: (self.accept(), self.checkUpdates.emit()))
        data = QPushButton("Open data folder")
        data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.DATA_DIR))))
        t.addRow(self._row(redo, imp))
        t.addRow(self._row(upd, data))
        adv.addWidget(tools)
        adv.addWidget(_hint(f"Book Studio {__version__} · data folder: {paths.DATA_DIR}"))
        adv.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    @staticmethod
    def _minutes(value: int, lo: int, hi: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(value)
        s.setSuffix(" min")
        return s

    @staticmethod
    def _row(*widgets) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            h.addWidget(x)
        return w

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Where should finished books go?", self.output.text())
        if folder:
            self.output.setText(folder)

    def _import_meta(self):
        file, _ = QFileDialog.getOpenFileName(self, "Book settings file", str(Path.home()), "Book settings (*.json)")
        if not file:
            return
        try:
            data = json.loads(Path(file).read_text(encoding="utf-8"))
            assert isinstance(data, dict) and all(isinstance(v, dict) for v in data.values())
        except Exception:  # noqa: BLE001
            QMessageBox.warning(self, "Not a book settings file", "This file isn't a book settings file (book_meta.json).")
            return
        current = store.builtin_meta() if paths.BUILTIN_META_FILE.exists() else {}
        store.write_json(paths.BUILTIN_META_FILE, current | data)
        QMessageBox.information(self, "Book settings imported",
                                f"Settings for {len(data)} books imported. They apply to books with the same file name.")

    def _save(self):
        s = self.settings
        s.output_dir = self.output.text().strip() or s.output_dir
        s.cooldown = self.cooldown.isChecked()
        s.work_minutes, s.rest_minutes, s.between_minutes = self.work.value(), self.rest.value(), self.between.value()
        s.cores, s.slots = self.cores.value(), self.slots.value()
        s.save()
        self.accept()


# ---------- book fixes ----------

FIX_HELP = """Options for books with an unusual layout (the same names as in book_meta.json):
text_fixes [["wrong", "right"]] · title_fixes {"old": "new"} · skip_pages [3, 4] · page_moves [[page, after]] · last_page 590
contents_pages [19, 20] · chapter_subentries true · unnumbered_sections ["Epilogue"] · drop_sections ["Index"] · front_sections ["Preface"]
heading_aliases {"Contents title": "Heading on the page"} · running_heads ["^Chapter .*"] · frontispiece_skip [2]
figure_captions {"12": "Caption"} · facsimile_pages [40] · restore_r_dot true · italic_prose true · inset_quotes true · academic true"""


class FixesDialog(QDialog):
    def __init__(self, book: store.Book, parent=None):
        super().__init__(parent)
        self.book = book
        self.setWindowTitle(f"Book fixes — {book.title}")
        self.setMinimumSize(720, 520)
        builtin = store.builtin_meta().get(book.id, {})
        lay = QVBoxLayout(self)
        lay.addWidget(_hint("For books that don't come out right by themselves. Changes here are applied the next time the "
                            "book is made — the pages already read are kept, so it takes seconds, not hours."))
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("Find out automatically", "auto")
        self.kind.addItem("Scanned pages (read with OCR)", "scanned")
        self.kind.addItem("Digital PDF with real text (no OCR)", "digital")
        self.kind.setCurrentIndex(max(0, self.kind.findData(book.fixes.get("kind", "auto"))))
        form.addRow("Book type", self.kind)
        self.layout_box = QComboBox()
        self.layout_box.addItem("Chapters of text (most books)", "prose")
        self.layout_box.addItem("Verse collection (Verse 1, 2, … with word-for-word)", "verses")
        layout = book.fixes.get("layout") or builtin.get("layout", "prose")
        self.layout_box.setCurrentIndex(max(0, self.layout_box.findData(layout)))
        form.addRow("Book layout", self.layout_box)
        lay.addLayout(form)
        if builtin:
            lay.addWidget(_hint(f"This book also has {len(builtin)} built-in settings from the imported book settings; "
                                "anything below overrides them."))
        self.editor = QPlainTextEdit()
        extra = {k: v for k, v in book.fixes.items() if k not in ("kind", "layout")}
        self.editor.setPlainText(json.dumps(extra, ensure_ascii=False, indent=2) if extra else "{\n}")
        f = self.editor.font()
        f.setFamily("Menlo, Consolas, monospace")
        self.editor.setFont(f)
        lay.addWidget(self.editor, 1)
        lay.addWidget(_hint(FIX_HELP))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _save(self):
        try:
            extra = json.loads(self.editor.toPlainText() or "{}")
            assert isinstance(extra, dict)
        except Exception:  # noqa: BLE001
            QMessageBox.warning(self, "Can't read the fixes", "The options box must be JSON, like {\"skip_pages\": [3]}.")
            return
        fixes = dict(extra)
        if self.kind.currentData() != "auto":
            fixes["kind"] = self.kind.currentData()
        builtin_layout = store.builtin_meta().get(self.book.id, {}).get("layout", "prose")
        if self.layout_box.currentData() != builtin_layout:
            fixes["layout"] = self.layout_box.currentData()
        self.book.fixes = fixes
        self.accept()


# ---------- warnings ----------

PAGE_RE = re.compile(r"\bp\.?\s*(\d{1,4})\b|\bpages?\s*:?\s*\[?(\d{1,4})|\[(\d{1,4})[,\]]")


class WarningsDialog(QDialog):
    """The book's report (what was found, what looked odd) beside the scanned page each line mentions."""

    def __init__(self, book: store.Book, parent=None):
        super().__init__(parent)
        self.book = book
        self.setWindowTitle(f"Warnings — {book.title}")
        self.resize(1100, 720)
        self.pdf = pdfium.PdfDocument(str(paths.WORK_DIR / "books" / f"{book.id}.pdf"))
        lay = QVBoxLayout(self)
        if book.error:
            err = QLabel(f"<b>⚠️ {book.error}</b>")
            err.setWordWrap(True)
            lay.addWidget(err)
        lay.addWidget(_hint("Click a line to see the page it talks about. 'Contents check: 36 listed, 36 found' means every "
                            "chapter was found. Pages with no text are usually pictures — check they really are."))
        split = QSplitter()
        self.lines = QListWidget()
        self.lines.setWordWrap(True)
        report = paths.WORK_DIR / "output" / book.id / "2-assembled" / "report.txt"
        text = report.read_text(encoding="utf-8") if report.exists() else "No report yet — the book's pages haven't been put together."
        self.lines.addItems([l for l in text.splitlines() if l.strip()])
        self.lines.currentTextChanged.connect(self._line_chosen)
        split.addWidget(self.lines)
        right = QWidget()
        r = QVBoxLayout(right)
        nav = QHBoxLayout()
        nav.addWidget(QLabel("Page"))
        self.page = QSpinBox()
        self.page.setRange(1, len(self.pdf))
        self.page.valueChanged.connect(self._show_page)
        nav.addWidget(self.page)
        nav.addWidget(QLabel(f"of {len(self.pdf)}"))
        nav.addStretch()
        log = QPushButton("Open log")
        log.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.LOGS_DIR / f"{book.id}.log"))))
        nav.addWidget(log)
        r.addLayout(nav)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidget(self.view)
        scroll.setWidgetResizable(True)
        r.addWidget(scroll, 1)
        split.addWidget(right)
        split.setSizes([560, 540])
        lay.addWidget(split, 1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay.addWidget(close)
        self._show_page(1)

    def _line_chosen(self, line: str):
        m = PAGE_RE.search(line or "")
        if m:
            self.page.setValue(int(next(g for g in m.groups() if g)))

    def _show_page(self, n: int):
        page = self.pdf[n - 1]
        img = page.render(scale=500 / page.get_width()).to_pil().convert("RGB")
        q = QImage(img.tobytes(), img.width, img.height, img.width * 3, QImage.Format_RGB888)
        self.view.setPixmap(QPixmap.fromImage(q.copy()))


# ---------- updates ----------

def offer_update(parent, settings: store.Settings, release: dict, quiet: bool) -> bool:
    """Asks to update; returns True when the update is staged and the app should quit so the launcher can swap it in."""
    if quiet and release["version"] == settings.skipped_version:
        return False
    box = QMessageBox(parent)
    box.setWindowTitle("Update available")
    box.setText(f"<b>Book Studio {release['version']}</b> is available (you have {__version__}).")
    box.setInformativeText((release["notes"][:800] + "\n\n" if release["notes"] else "")
                           + "Your books, settings and the pages already read are kept.")
    now = box.addButton("Update now", QMessageBox.AcceptRole)
    box.addButton("Later", QMessageBox.RejectRole)
    skip = box.addButton("Skip this version", QMessageBox.DestructiveRole) if quiet else None
    box.exec()
    if box.clickedButton() is skip:
        settings.skipped_version = release["version"]
        settings.save()
        return False
    if box.clickedButton() is not now:
        return False
    if not paths.IS_INSTALLED:
        QMessageBox.information(parent, "Update", "This copy runs from the source code — update it with git instead.")
        return False
    dlg = QDialog(parent)
    dlg.setWindowTitle("Updating Book Studio")
    v = QVBoxLayout(dlg)
    label = QLabel("Downloading…")
    bar = QProgressBar()
    bar.setRange(0, 1000)
    v.addWidget(label)
    v.addWidget(bar)
    task = Task(updater.prepare, release, parent=dlg)
    result = {"ok": False}
    task.progress.connect(lambda t, f: (label.setText(t), bar.setValue(int(f * 1000))))
    task.succeeded.connect(lambda _: (result.update(ok=True), dlg.accept()))
    task.failed.connect(lambda msg: (QMessageBox.warning(dlg, "Update failed", f"The update could not be downloaded: {msg}"), dlg.reject()))
    task.start()
    dlg.exec()
    task.wait()
    if result["ok"]:
        QMessageBox.information(parent, "Update ready", "Book Studio will now close and open again in a minute with the new version.")
        updater.apply_and_restart()
        return True
    return False
