# manual/pipeline/run_book.py
# One command for the whole scanned-book pipeline: OCR → assemble → typeset one clean PDF → the matching EPUB, all drafts in the
# workspace. Checked books are moved to the library's pdf/ and epub/ by publish_book.py.
# The assembler is chosen by the book's "layout" in book_meta.json (verses → assemble_verses.py, prose → assemble_prose.py).
# Each stage runs as its own process, so the OCR model's memory is freed before typesetting starts; OCR resumes where it left off.
# Usage: poetry run python manual/pipeline/run_book.py <path/to/book.pdf> --library <path/to/book-library>

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import json
import subprocess
from pathlib import Path

import power

ASSEMBLERS = {"verses": "assemble_verses.py", "prose": "assemble_prose.py"}


def main():
    pdf = local_env.book_path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit(local_env.USAGE)
    book = pdf.stem
    meta = json.loads(local_env.META_FILE.read_text(encoding="utf-8"))
    if book not in meta:
        sys.exit(f"Add '{book}' to {local_env.META_FILE} first (title, author, layout: verses or prose)")
    with power.keep_awake():  # the whole run: a sleeping laptop would stop the OCR for hours
        run_stages(pdf, book, meta)
    print("\nAll stages done.")


def run_stages(pdf, book, meta):
    here = Path(__file__).parent
    for script in ["ocr_book.py", ASSEMBLERS[meta[book]["layout"]], "typeset_book.py", "book_to_epub.py"]:
        print(f"\n=== {script} {book} ===", flush=True)
        if subprocess.run([sys.executable, str(here / script), str(pdf), "--library", str(local_env.PROJECT_ROOT)]).returncode != 0:
            sys.exit(f"Stopped: {script} failed (fix the error above, then re-run — finished work is kept)")


if __name__ == "__main__":
    main()
