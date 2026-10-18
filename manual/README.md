# manual/README.md

# Manual pipeline — making a book by hand

The scripts in `pipeline/` turn one scanned book into a clean PDF and EPUB, run from the terminal at the **repo root** (`poetry run python manual/pipeline/...`). Books, work files and tools live at the repo root (see the root `README.md`); rules and OCR pitfalls are in the root `CLAUDE.md`.

## How to make a book

1. Add the book to `manual/pipeline/book_meta.json` — title, subtitle, author, credits, and `layout`: `verses` (Padyāvalī-style: Verse N → Sanskrit → word-for-word → translation → poet) or `prose` (stories, chapters from the book's own contents list).
2. Run the whole pipeline (safe to re-run — finished OCR pages are kept, so an interrupted run just continues):
   ```
   poetry run python manual/pipeline/run_book.py <book-file-name-without-.pdf>
   ```
   Keep the Mac plugged in and awake during the OCR (~15–20 s per page).
3. Read `output/<book>/2-assembled/report.txt` and fix anything flagged (see below), then re-run.
4. Check the PDF in `output/<book>/3-clean-pdf/`, then move it to `books/final/<book>_en.pdf`. The original scan stays in `books/originals/`.

A book that arrives as a **clean digital PDF** (real text, not a scan) skips the OCR: `pdf_to_book.py <book>` writes the same `book.json` from its text (sections from the PDF's outline, pictures, tables, verses, drop caps), then `typeset_book.py` and `book_to_epub.py` work as usual.

| Step | Script | What it does | Output |
|---|---|---|---|
| 1. OCR | `ocr_book.py` | Reads the text off every scanned page with Surya OCR, running locally. | `1-ocr/` |
| 2. Assemble | `assemble_verses.py` / `assemble_prose.py` | Drops headers and page numbers, re-joins text split by page breaks, and tags each part (verses: Sanskrit, word-for-word, translation, poet — prose: paragraphs, verse quotes, sources, signatures, photos). Writes `report.txt`. | `2-assembled/` |
| 3. Typeset | `typeset_book.py` | Builds the clean A5 PDF with Typst: title page, contents, foreword/introduction, chapters. Photos and drawings are cropped from the scan by `figures.py` (framed Deity photos cut just inside their frame) and placed where they appear, with captions. | `3-clean-pdf/` |

## Word (.docx) and e-book (.epub) copies

A book that is already a text PDF (not a scan) can be turned into an editable Word file next to it — paragraphs, headings (Word heading styles, so the Navigation Pane lists every chapter), bold/italic and verse line breaks are kept; page numbers are dropped:
```
poetry run python manual/pipeline/pdf_to_docx.py charu-vilas-vol2_en charu-vilas-vol2_hi
```
An EPUB for Kindle and other e-readers: a clickable contents, the cover, and the Gentium font embedded so diacritics always show. Title/author come from `book_meta.json`.
- **Our processed books** (with all their photos and captions, the same chapters, quotations, notes and — for Padyāvalī — verses as the PDF; every finished book except Cāru Vilāsa has one in `books/final/`):
  ```
  poetry run python manual/pipeline/book_to_epub.py a-spiritual-journey
  ```
- **Other text PDFs** with a chapter outline (e.g. Bhakti-bhāva):
  ```
  poetry run python manual/pipeline/pdf_to_epub.py bhakti-bhava_en
  ```
Kindle reads EPUB only through Amazon's *Send to Kindle* (which uploads the file to Amazon) — over USB it needs AZW3.

## Fixing what the report flags

`report.txt` lists chapters it could not match to the book's contents page, missing verse numbers, verses missing a part, pages with no text, and the first words of every chapter (to spot a damaged drop cap). Check each against the scan, then:

| Problem | Fix |
|---|---|
| A word misread (e.g. a decorated drop cap: "Ifter" for "After") | Add `["wrong text", "right text"]` to the book's `text_fixes` in `book_meta.json` — include enough words to match one place only. The report confirms each fix matched exactly once. |
| A photo caption the OCR missed | Add it to `figure_captions` in `book_meta.json`, by page number. |
| A chapter title wrong in the book's own contents (typo, or cut off by a wrapped row) | Add it to `title_fixes` in `book_meta.json` (old → new). |
| A whole block misread (e.g. a verse's first Sanskrit line replaced by word-for-word) | Re-read just that block from a tight crop: `poetry run python manual/pipeline/ocr_book.py <book> --fix 261:4` (page:block position). |
| A flag that matches the printed book (e.g. a verse with no poet in the original) | Nothing — we stay faithful to the original, typos included. |

## The design

A5 page, Gentium Book Plus (made for full diacritic coverage), brown accent colour, centred verse blocks, Sanskrit words in **bold** in word-for-word lists, indented paragraphs with extra line spacing for prose. The PDF opens with the book's original front cover (full-bleed, on a page shaped like the cover), then our title page, which has no copyright line. Photos from the original's front pages (dedication portrait of Śrīla Prabhupāda, Deity photos) follow the title page as frontispieces; colour paintings and photo plates stay in colour. The look lives in `manual/pipeline/book_template.typ`.
