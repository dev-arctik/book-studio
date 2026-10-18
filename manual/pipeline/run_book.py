# pipeline/run_book.py
# One command for the whole scanned-book pipeline: OCR → assemble → typeset one clean PDF of the whole book.
# The assembler is chosen by the book's "layout" in book_meta.json (verses → assemble_verses.py, prose → assemble_prose.py).
# Each stage runs as its own process, so the OCR model's memory is freed before typesetting starts; OCR resumes where it left off.
# Usage: poetry run python pipeline/run_book.py padyavali

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import json
import subprocess
from pathlib import Path

ASSEMBLERS = {"verses": "assemble_verses.py", "prose": "assemble_prose.py"}


def main():
    book = local_env.find_book(sys.argv[1]).stem
    meta = json.loads((local_env.PIPELINE_DIR / "book_meta.json").read_text(encoding="utf-8"))
    if book not in meta:
        sys.exit(f"Add '{book}' to manual/pipeline/book_meta.json first (title, author, layout: verses or prose)")
    here = Path(__file__).parent
    for script in ["ocr_book.py", ASSEMBLERS[meta[book]["layout"]], "typeset_book.py"]:
        print(f"\n=== {script} {book} ===", flush=True)
        if subprocess.run([sys.executable, str(here / script), book]).returncode != 0:
            sys.exit(f"Stopped: {script} failed (fix the error above, then re-run — finished work is kept)")
    print("\nAll stages done.")


if __name__ == "__main__":
    main()
