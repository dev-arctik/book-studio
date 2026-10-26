# manual/README.md

# Manual pipeline — making a book from the terminal

The scripts in `pipeline/` turn one scanned book into a clean PDF and EPUB. Book Studio runs these same scripts; this is the way to drive them by hand, for books that need special handling. Rules and OCR pitfalls are in the root `CLAUDE.md`.

**Every command takes two paths:** the book's PDF, and the **library** folder where its work and results go. Nothing is looked up in hidden default places, and books never live inside this repo.

```
poetry run python manual/pipeline/<script>.py  <path/to/book.pdf>  --library <path/to/book-library>
```

The book's **file name** (without `.pdf`) is its key: `without-fear.pdf` → `workspace/without-fear/` and the `"without-fear"` entry in `book_meta.json`. Run from the repo root.

## The library folder

Code and books live apart. The library sits outside the repo (here: `../book-library`, next to it) and holds the settings, the working area and the finished books. **The scans are not in it**: they stay wherever you keep them, and each run is given the path of the book's file.

```
book-library/                  never in git
├── book_meta.json             per-book settings: title, author, layout, cover_file, fixes (text_fixes, skip_pages…)
├── workspace/                 the working area — drafts and everything needed to tweak and rebuild a book
│   ├── <book>/                1-ocr/ (the pages read — hours of work), 2-assembled/ (book.json + report.txt),
│   │                          3-clean-pdf/ (the PDF draft), 4-epub/ (the EPUB draft)
│   ├── logs.md                one log for ALL runs: every manual fix the pipeline couldn't do, to improve it later
│   └── STATUS.md              which books are done and how far each is
└── <batch>/                   not part of the library proper: the folder Devansh hands over each run (group1/, Group 2/ …) —
    ├── the originals + cover images     they stay here, only read
    ├── pdf/                              finished, checked books: <book>_en.pdf (publish_book.py puts them here)
    └── epub/                             finished, checked books: <book>_en.epub
```

Keep a book's `workspace/<book>/` while you may still fix it; changing it later means reading all its pages again. Book Studio keeps its own data folder with the same stages (its working folder is called `output/`).

## How to make a book

1. Put the book's file (a scan PDF, a digital PDF) and any cover images in one input folder. They are only read, never moved or copied.
2. Add the book to the library's `book_meta.json` — title, subtitle, author, `credits` (a list, may be empty) and `layout`: `verses` (Padyāvalī-style: Verse N → Sanskrit → word-for-word → translation → poet) or `prose` (stories, chapters from the book's own contents list). The file must be UTF-8 without a BOM.
3. Run the whole pipeline (safe to re-run — finished OCR pages are kept, so an interrupted run just continues):
   ```
   poetry run python manual/pipeline/run_book.py <input-folder>/without-fear.pdf --library ../book-library
   ```
   Keep the laptop plugged in during the OCR (about 15–30 s per page on the ASUS laptop). **Important — the rests protect the laptop:** hours of OCR keep the CPU and GPU at full load, and a hot laptop slows down and wears out faster. So the OCR **rests 15 minutes after every hour of reading and 30 minutes after every finished book** (`power.WORK_MINUTES` / `REST_MINUTES` / `BETWEEN_MINUTES`; the `.last-ocr-finished` file in the workspace remembers when the last book ended). Use the rest to check and fix the book that just finished. Don't switch the rests off for a real run (`BOOK_NO_COOLDOWN=1` exists only for tests). It builds the PDF and EPUB drafts in `workspace/<book>/`. To watch a batch, run `.venv/Scripts/python.exe manual/pipeline/progress.py --library ../book-library --inputs <input-folder> --watch` in a second terminal (it refreshes every 2 minutes; `--watch 30` for every 30 seconds): a **MODE** line (WORKING with the time to the next rest, or RESTING with a countdown to when reading continues), a **TEMPS** line (CPU via Windows' ACPI thermal zone, GPU via `nvidia-smi`, with a warning when the GPU slows itself down for heat), then every book's stage, pages read, speed and time left (it only reads, it changes nothing).
4. Read `workspace/<book>/2-assembled/report.txt` and fix anything flagged (see below), then re-run. Whenever the pipeline couldn't handle something and you fixed it by hand, add an entry to `workspace/logs.md`.
5. Check the PDF in `3-clean-pdf/` and the EPUB in `4-epub/` against the scan, then publish them:
   ```
   poetry run python manual/pipeline/publish_book.py <input-folder>/without-fear.pdf --library ../book-library
   ```
   This copies them to `pdf/without-fear_en.pdf` and `epub/without-fear_en.epub` **inside the input folder** (beside the original, so each batch keeps its finished books together). Only checked books go there.

A book that arrives as a **clean digital PDF** (real text, not a scan) skips the OCR: `pdf_to_book.py <pdf> --library <library>` writes the same `book.json` from its text (sections from the PDF's outline, pictures, tables, verses, drop caps), then `typeset_book.py` and `book_to_epub.py` work as usual. **Check the text layer before any OCR** (2026-10-20: three digital books were nearly read by OCR for hours): open the PDF with PyMuPDF and look at characters per page (a scan has none, or a few hundred of OCR junk), whether a page-sized image lies under the text, and whether the letters are stand-ins or private-use codes. A PDF without an outline takes its chapters from `"sections": [["1: Title", first PDF page], …]` in `book_meta.json` (find the pages by searching for "CHAPTER N" and read the printed contents). Digital-route settings in `book_meta.json`: `sections` (a third item names the line a section begins with, for sections that share a page; `sections_replace` uses the list even when the PDF has an outline), `drop_sections`, `front_sections`, `skip_pages`, `first_indent_max` (a Word book indents 35 pt), `heading_extra` (subheadings only slightly bigger than the body), `normalise_sizes` (chapters with their own body size), `no_title_block` (chapters start straight with their first story), `chapter_subtitles`, `drop_lines` (regexes for running heads or navigation lines inside the text), `text_fixes` / `word_fixes` / `regex_fixes` (each printed with its number of matches), `bullet_fonts`, `page_number_band`, `numbered_items`, `balaram_fonts`, `heal_hyphens` (English words broken at line ends), `drop_fonts`, `bullet_min_size`, `skip_pictures`, `tidy` (true: `book_tidy.py` repairs verses cut in two blocks, translations in pieces, bold subheadings glued to the next paragraph, "—Name" lines (right-aligned), rows of dots (centred break) and bold capital openings (set as plain sentence case); `glue_headings` lists heading texts that end the paragraph before them), `trim_pictures` ({"page": lowest y in points} — a heading drawn over a picture's bottom edge), `picture_pages` (charts, forms, full-page art), `mirrored_pages` (true, or a number: the largest margin shift to align; Prabandhāvalī needs 40), `deep_first_lines` (a quotation whose first line is one step deeper than the rest is one block), `line_pages` ([first, last] pages of a list of names, one line per item), `bold_headings` (a bold centred line at body size is a subheading), `centred_title_block` (chapter label and title are centred line objects), a meta section named "Part One: Subtitle" becomes a part title page, `drop_pictures` (scan route: pages whose picture is decoration), `bold_paragraph_pages`, `no_topics` (typeset: list no subheadings in the contents — for screenplay cues and labels). Ligature letters the text layer lost ("Te" for "The", "afer" for "after") are repaired with `word_fixes`; combining overlines are joined into macron letters automatically. A very long file name works (workspace paths over 250 characters use Windows' long-path prefix). No rests are needed — nothing heavy runs.

| Step | Script | What it does | Output (in the library) |
|---|---|---|---|
| 1. OCR | `ocr_book.py` | Reads the text off every scanned page with Surya OCR, running locally. | `workspace/<book>/1-ocr/` |
| 2. Assemble | `assemble_verses.py` / `assemble_prose.py` | Drops headers and page numbers, re-joins text split by page breaks, and tags each part (verses: Sanskrit, word-for-word, translation, poet — prose: paragraphs, verse quotes, sources, signatures, photos). Writes `report.txt`. | `workspace/<book>/2-assembled/` |
| 3. Typeset | `typeset_book.py` | Builds the clean A5 PDF with Typst: cover, title page, contents, foreword/introduction, chapters. Photos and drawings are cropped from the scan by `figures.py` and placed where they appear, with captions. | `workspace/<book>/3-clean-pdf/` |
| 4. EPUB | `book_to_epub.py` | The same chapters, pictures and cover as an e-book, with a clickable contents. | `workspace/<book>/4-epub/` |
| 5. Publish | `publish_book.py` | After checking: copies the PDF and EPUB to `pdf/` and `epub/` in the batch (input) folder. | `<batch>/pdf/`, `<batch>/epub/` |

## Word (.docx) and e-book (.epub) copies

A book that is already a text PDF (not a scan) can be turned into an editable Word file — paragraphs, headings (Word heading styles, so the Navigation Pane lists every chapter), bold/italic and verse line breaks are kept; page numbers are dropped:
```
poetry run python manual/pipeline/pdf_to_docx.py ../book-library/pdf/charu-vilas-vol2_en.pdf --library ../book-library
```
An EPUB for Kindle and other e-readers: a clickable contents, the cover, and the Gentium font embedded so diacritics always show. Title/author come from `book_meta.json`.
- **Our processed books** (all their photos and captions, the same chapters, quotations, notes and — for Padyāvalī — verses as the PDF):
  ```
  poetry run python manual/pipeline/book_to_epub.py <input-folder>/a-spiritual-journey.pdf --library ../book-library
  ```
- **Other text PDFs** with a chapter outline (e.g. Bhakti-bhāva):
  ```
  poetry run python manual/pipeline/pdf_to_epub.py ../book-library/pdf/bhakti-bhava_en.pdf --library ../book-library
  ```
Kindle reads EPUB only through Amazon's *Send to Kindle* (which uploads the file to Amazon) — over USB it needs AZW3.

## Settings for scans (the prose route) added with the Group 2 books

`strip_text` (regexes removed from every block and from the copyright page — a scanner's watermark line), `drop_headings` (a lone heading left behind, e.g. "Contents"), `part_sections` (`{"contents title": "Part One"}` — rows of the contents that are really parts), `sections_by_page` (true: every section comes from `insert_sections` by scan page — for scans whose headings the reader cannot read), `right_lines` (texts set right-aligned like a source — the name under a quotation), `bold_speakers` (names of speakers in dialogues set bold), `copyright_page`, plus the older `contents_pages`, `chapter_subentries`, `insert_sections`, `drop_sections`, `subtitle_fixes`, `frontispiece_skip`. A book name ending in a dot or space is stored in the workspace without it (Windows drops it).

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
