# software/book_studio/worker.py
# Makes one book in its own process, started by the window: read pages (OCR, or the text of a digital PDF) → chapters →
# PDF → EPUB, then puts both files in the output folder. Its own process so the window never freezes and memory is freed after.
# Talks to the window with "@@{json}" lines on stdout; whatever the pipeline prints goes to logs/<book>.log.
# Usage (by the window): python -m book_studio.worker <book-id>

import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import paths, store

sys.dont_write_bytecode = True  # keep the pipeline folder free of __pycache__
EVENTS = sys.stdout  # the pipe to the window; sys.stdout itself is redirected to the log below


def emit(event: str, **data) -> None:
    EVENTS.write("@@" + json.dumps({"event": event, **data}, ensure_ascii=False) + "\n")
    EVENTS.flush()


class Stopped(Exception):
    pass


def control() -> dict:
    try:
        return json.loads(paths.CONTROL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_while_paused() -> None:
    told = False
    while (c := control()).get("paused") and not c.get("stop"):
        if not told:
            emit("paused")
            told = True
        time.sleep(1)
    if control().get("stop"):
        raise Stopped
    if told:
        emit("resumed")


def rest(seconds: int) -> None:
    """Cool-down: the OCR waits between batches (the engine stays loaded, but the graphics chip and processor go idle)."""
    emit("rest", seconds=seconds)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        c = control()
        if c.get("stop"):
            raise Stopped
        if c.get("skip_rest"):
            break
        time.sleep(1)
    emit("resumed")


def is_digital(book: store.Book, pdf: Path) -> bool:
    """A PDF with real text and a chapter outline (like Heart and Soul) needs no OCR; scans do."""
    kind = book.fixes.get("kind", "auto")
    if kind != "auto":
        return kind == "digital"
    import pymupdf

    with pymupdf.open(pdf) as doc:
        if not doc.get_toc():
            return False
        sample = range(min(len(doc), 30))
        with_text = sum(len(doc[i].get_text().strip()) > 100 for i in sample)
        return with_text >= 0.8 * len(sample)


FRIENDLY = {
    "starting": "The page reader could not start. Try Settings → 'Set up the page reader again', or restart the computer.",
    "ocr": "Reading the pages stopped unexpectedly. The pages already read are saved — press Make books to continue.",
    "assemble": "Book Studio could not work out this book's chapters by itself. Open Warnings to see what it found, or send the book to Devansh.",
    "typeset": "Making the PDF failed. Please send the log file (Warnings → Open log) to Devansh.",
    "epub": "Making the EPUB failed. Please send the log file (Warnings → Open log) to Devansh.",
}


def make_book(book_id: str) -> None:
    library, settings = store.Library.load(), store.Settings.load()
    book = library.get(book_id)
    sys.path.insert(0, str(paths.PIPELINE_DIR))
    import local_env  # reads the BOOK_STUDIO_* paths the window put in this process's environment

    pdf = local_env.find_book(book_id)
    meta = json.loads(local_env.META_FILE.read_text(encoding="utf-8"))[book_id]
    stage = "starting"
    try:
        if is_digital(book, pdf):
            stage = "assemble"
            emit("stage", stage="text")
            import pdf_to_book

            pdf_to_book.convert(book_id)
        else:
            import ocr_book  # loads Surya (and PyTorch) — a few seconds

            ocr_dir = local_env.stage_dir(book_id, "ocr")
            done = lambda: sum(1 for _ in ocr_dir.glob("page-*.json"))  # noqa: E731
            emit("ocr", done=done(), total=book.pages)
            if done() < book.pages:
                emit("stage", stage="starting")
                work_start = time.monotonic()

                def after_chunk(_pages):
                    nonlocal stage, work_start
                    stage = "ocr"
                    emit("ocr", done=done(), total=book.pages)
                    wait_while_paused()
                    if settings.cooldown and time.monotonic() - work_start >= settings.work_minutes * 60 and done() < book.pages:
                        rest(settings.rest_minutes * 60)
                        work_start = time.monotonic()

                wait_while_paused()
                ocr_book.ocr_all(pdf, ocr_dir, 1, book.pages, after_chunk=after_chunk)
            stage = "assemble"
            emit("stage", stage="assemble")
            import assemble_prose
            import assemble_verses

            sys.argv = ["assemble", book_id]
            (assemble_verses if meta["layout"] == "verses" else assemble_prose).main()

        # Finished books: PDFs and e-books in separate folders, so each set is easy to find and share
        out_dir = Path(settings.output_dir)
        (out_dir / "PDF").mkdir(parents=True, exist_ok=True)
        (out_dir / "EPUB").mkdir(parents=True, exist_ok=True)
        name = store.safe_filename(meta["title"])

        stage = "typeset"
        emit("stage", stage="typeset")
        import typeset_book

        sys.argv = ["typeset", book_id]
        typeset_book.main()
        pdf_out = out_dir / "PDF" / f"{name}.pdf"
        shutil.move(local_env.stage_dir(book_id, "clean-pdf") / f"{book_id}.pdf", pdf_out)

        stage = "epub"
        emit("stage", stage="epub")
        import book_to_epub

        book_to_epub.convert(book_id)
        epub_out = out_dir / "EPUB" / f"{name}.epub"
        shutil.move(local_env.final_path(f"{book_id}_en.epub"), epub_out)
        emit("done", pdf=str(pdf_out), epub=str(epub_out))
    except Stopped:
        emit("stopped")
    except Exception as exc:  # noqa: BLE001 — every failure must reach the window as a readable message
        traceback.print_exc()
        emit("error", stage=stage, message=FRIENDLY.get(stage, str(exc)), detail=f"{type(exc).__name__}: {exc}")


def main() -> None:
    book_id = sys.argv[1]
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log = open(paths.LOGS_DIR / f"{book_id}.log", "a", encoding="utf-8", buffering=1)
    log.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M} — making {book_id} =====\n")
    sys.stdout = sys.stderr = log
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    make_book(book_id)


if __name__ == "__main__":
    main()
