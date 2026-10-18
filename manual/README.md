# manual/README.md

# Manual pipeline — making a book from the terminal

The scripts in `pipeline/` turn one scanned book into a clean PDF and EPUB. Book Studio runs these same scripts; this is the way to drive them by hand, for books that need special handling. Rules and OCR pitfalls are in the root `CLAUDE.md`.

**Every command takes two paths:** the book's PDF, and the **library** folder where its work and results go. Nothing is looked up in hidden default places, and books never live inside this repo.

```
poetry run python manual/pipeline/<script>.py  <path/to/book.pdf>  --library <path/to/book-library>
```

The book's **file name** (without `.pdf`) is its key: `without-fear.pdf` → `output/without-fear/` and the `"without-fear"` entry in `book_meta.json`. Run from the repo root.

## The library folder

Code and books live apart. The library sits outside the repo (here: `../book-library`, next to it) and holds only the books and their settings:

```
book-library/                  never in git
├── book_meta.json             per-book settings: title, author, layout, fixes (text_fixes, skip_pages…)
├── books/
│   ├── originals/             the scans as received
│   ├── final/                 finished books, one folder per format: pdf/, epub/, word/
│   └── STATUS.md              which books are done
└── output/<book>/             appears while a book is being made: 1-ocr/ (the pages read — hours of work), 2-assembled/
                               (book.json + report.txt), 3-clean-pdf/. Keep it while you may still fix the book; delete
                               it once the book is final (changing it later means reading all its pages again).
```

The book's PDF can be anywhere (e.g. `~/Downloads/new-book.pdf`); keeping the scans in `books/originals/` makes rebuilding easy. Book Studio uses the same layout inside its own data folder.

## How to make a book

1. Add the book to the library's `book_meta.json` — title, subtitle, author, credits, and `layout`: `verses` (Padyāvalī-style: Verse N → Sanskrit → word-for-word → translation → poet) or `prose` (stories, chapters from the book's own contents list).
2. Run the whole pipeline (safe to re-run — finished OCR pages are kept, so an interrupted run just continues):
   ```
   poetry run python manual/pipeline/run_book.py ../book-library/books/originals/without-fear.pdf --library ../book-library
   ```
   Keep the Mac plugged in and awake during the OCR (~15–20 s per page).
3. Read `output/<book>/2-assembled/report.txt` in the library and fix anything flagged (see below), then re-run.
4. Check the PDF in `output/<book>/3-clean-pdf/`, then move it to `books/final/pdf/<book>_en.pdf`. EPUBs and Word files go to `books/final/epub/` and `word/` by themselves.

A book that arrives as a **clean digital PDF** (real text, not a scan) skips the OCR: `pdf_to_book.py <pdf> --library <library>` writes the same `book.json` from its text (sections from the PDF's outline, pictures, tables, verses, drop caps), then `typeset_book.py` and `book_to_epub.py` work as usual.

| Step | Script | What it does | Output (in the library) |
|---|---|---|---|
| 1. OCR | `ocr_book.py` | Reads the text off every scanned page with Surya OCR, running locally. | `output/<book>/1-ocr/` |
| 2. Assemble | `assemble_verses.py` / `assemble_prose.py` | Drops headers and page numbers, re-joins text split by page breaks, and tags each part (verses: Sanskrit, word-for-word, translation, poet — prose: paragraphs, verse quotes, sources, signatures, photos). Writes `report.txt`. | `output/<book>/2-assembled/` |
| 3. Typeset | `typeset_book.py` | Builds the clean A5 PDF with Typst: cover, title page, contents, foreword/introduction, chapters. Photos and drawings are cropped from the scan by `figures.py` and placed where they appear, with captions. | `output/<book>/3-clean-pdf/` |

## Word (.docx) and e-book (.epub) copies

A book that is already a text PDF (not a scan) can be turned into an editable Word file — paragraphs, headings (Word heading styles, so the Navigation Pane lists every chapter), bold/italic and verse line breaks are kept; page numbers are dropped:
```
poetry run python manual/pipeline/pdf_to_docx.py ../book-library/books/final/pdf/charu-vilas-vol2_en.pdf --library ../book-library
```
An EPUB for Kindle and other e-readers: a clickable contents, the cover, and the Gentium font embedded so diacritics always show. Title/author come from `book_meta.json`.
- **Our processed books** (all their photos and captions, the same chapters, quotations, notes and — for Padyāvalī — verses as the PDF):
  ```
  poetry run python manual/pipeline/book_to_epub.py ../book-library/books/originals/a-spiritual-journey.pdf --library ../book-library
  ```
- **Other text PDFs** with a chapter outline (e.g. Bhakti-bhāva):
  ```
  poetry run python manual/pipeline/pdf_to_epub.py ../book-library/books/final/pdf/bhakti-bhava_en.pdf --library ../book-library
  ```
Kindle reads EPUB only through Amazon's *Send to Kindle* (which uploads the file to Amazon) — over USB it needs AZW3.

## Fixing what the report flags

`report.txt` lists chapters it could not match to the book's contents page, missing verse numbers, verses missing a part, pages with no text, and the first words of every chapter (to spot a damaged drop cap). Check each against the scan, then:

| Problem | Fix |
|---|---|
| A word misread (e.g. a decorated drop cap: "Ifter" for "After") | Add `["wrong text", "right text"]` to the book's `text_fixes` in `book_meta.json` — include enough words to match one place only. The report confirms each fix matched exactly once. |
| A photo caption the OCR missed | Add it to `figure_captions` in `book_meta.json`, by page number. |
| A chapter title wrong in the book's own contents (typo, or cut off by a wrapped row) | Add it to `title_fixes` in `book_meta.json` (old → new). |
| A whole block misread (e.g. a verse's first Sanskrit line replaced by word-for-word) | Re-read just that block from a tight crop: `ocr_book.py <pdf> --library <library> --fix 261:4` (page:block position). |
| A flag that matches the printed book (e.g. a verse with no poet in the original) | Nothing — we stay faithful to the original, typos included. |

## The design

A5 page, Gentium Book Plus (made for full diacritic coverage), brown accent colour, centred verse blocks, Sanskrit words in **bold** in word-for-word lists, indented paragraphs with extra line spacing for prose. The PDF opens with the book's original front cover (full-bleed, on a page shaped like the cover), then our title page; the book's own copyright page follows only when `keep_copyright` is set. Photos from the original's front pages (dedication portrait of Śrīla Prabhupāda, Deity photos) follow as frontispieces; colour paintings and photo plates stay in colour. The look lives in `manual/pipeline/book_template.typ`.

## This repo on this computer

```
book-studio/                   the git repo: code and docs only
├── manual/pipeline/           the scripts and book_template.typ
├── software/                  Book Studio (see software/README.md)
├── pyproject.toml             packages for the manual pipeline (Poetry; .venv/ in the repo, git-ignored)
├── tools/                     llama-server (runs the OCR model), Gentium fonts, uv (git-ignored)
└── .cache/                    the OCR model (huggingface/), Poetry, uv and Book Studio's dev environment (git-ignored)
```

Software lives with the code, books with the library. Nothing is installed globally. Tip: in Finder, press `Cmd + Shift + .` to show hidden folders.
