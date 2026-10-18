# CLAUDE.md

Scanned ISKCON books → clean, diacritic-correct PDFs for kids at a charity youth forum. Two parts: `manual/` (the hand-run pipeline every finished book was made with — run steps in `manual/README.md`) and `software/` (Book Studio, a planned desktop app wrapping that pipeline — plan in `software/README.md`). The root `README.md` has the folder map and book status; this file holds the rules, preferences and pitfalls.

## Hard rules

- **Book content never leaves our own computers.** The PDFs are internal ISKCON material, not released online. No uploads, no artifacts/publishing, no cloud OCR or LLM APIs on book text, no book content on GitHub. The repo goes to a **public GitHub repo** (approved 2026-10-18, so Book Studio can self-update from GitHub Releases) — code and docs only: `.gitignore` keeps out `books/`, `output/`, every .pdf/.epub/.docx and `manual/pipeline/book_meta.json` (it holds titles, captions and OCR-fix text fragments); release zips leave it out too. Never force-add book files; creating the repo, pushing and publishing releases are confirmed with Devansh first. The OCR (Surya via a local `llama-server` on 127.0.0.1) and typesetting (Typst) are fully local — keep it that way.
- **Nothing installed globally** (Mac is low on disk). Poetry venv and cache, HF model cache (`HF_HOME`), Surya `MODEL_CACHE_DIR`, the `llama-server` binary and fonts all live inside the project. `manual/pipeline/local_env.py` pins these (`PIPELINE_DIR` = the scripts, `PROJECT_ROOT` = the repo root where books, output, tools and caches live) — every pipeline script imports it first.
- **Faithful to the original.** Fix OCR errors (checked against the scan); never "correct" the printed book's own typos or spellings.
- **Never touch the user's personal files** (e.g. in ~/Downloads); only files explicitly named as books.

## User preferences

- **One PDF per book.** No chapter-wise PDFs, no duplicate copies of book content. The user cuts chapters by hand.
- **Clean folder.** Temporary files (crops, Typst data, previews) are deleted after use; no `__pycache__` (scripts set `sys.dont_write_bytecode`); scratch renders go in `.cache/tmp/` and are removed.
- **Finished book** → `books/final/<book>_en.pdf` (or `_hi`, `.docx`). `books/final/` holds **only processed books** — the original scan stays in `books/originals/<book>.pdf` (keep that name; `find_book` searches all of `books/` for rebuilds). Never name it `_clean`.
- **Design is approved — don't change it unasked:** A5, Gentium Book Plus, brown accent `#7a4a12`, centred verse blocks, bold Sanskrit words in word-for-word, no copyright line on the title page. Every PDF opens with the original front cover (page 1 of the scan, colour, its own page shape) — the user asked for it on 2026-10-16; the EPUB uses the same cover.
- Ask before starting a multi-hour OCR run; the user may want to control when the Mac is busy.

## Pipeline

Scripts live in `manual/pipeline/`; run them from the repo root (`poetry run python manual/pipeline/run_book.py <book>`). `run_book.py <book>` = `ocr_book.py` → `assemble_verses.py` | `assemble_prose.py` (chosen by `layout` in `book_meta.json`) → `typeset_book.py`.

| File | Role |
|---|---|
| `local_env.py` | Paths, numbered output stages (`1-ocr`, `2-assembled`, `3-clean-pdf`, `logs`), `find_book()` (searches all of `books/`), local cache env vars |
| `ocr_book.py` | Surya OCR, 4 pages per call, resumable (skips existing `page-NNN.json`); `--fix page:block` re-OCRs one block from a tight crop |
| `ocr_text.py` | Shared helpers: HTML clean-up, non-IAST look-alike fixes (`î→ī`, `ş→ṣ`, `○→O`…), line joining, paragraph gluing across page breaks, title matching, back-cover removal, `text_fixes` |
| `assemble_verses.py` | Verse anthologies (Padyāvalī): chapters from "title + (English title)" headings, verses by "Verse N", word-for-word/translation/poet state machine, title reconciliation against the contents page |
| `assemble_prose.py` | Prose books (Vraja-līlā): sections matched **in order** against the book's own contents list; blocks = p / epigraph / quote / cite / sign / h / figure |
| `figures.py` | Crops illustrations: mid-tone region + dark border lines on all 4 sides = framed photo (crop inside frame); else trim margins. Skips ornaments (<5% of page, or top 6% of page). Keeps colour when ≥5% of the crop is clearly saturated (paintings, photo plates); grey scans stay greyscale |
| `typeset_book.py` | Converts either layout into one template format; crops figures into `3-clean-pdf/.build/` and deletes it after compiling. Photos on the skipped front pages (page 2 → contents page: dedication portrait, Deity photo) become frontispiece pages after the title page — it prints each one; check against the scan and list line-art ornaments in `frontispiece_skip` |
| `book_template.typ` | The page design (Typst). Reads JSON via `sys.inputs.data` — never escape book text into Typst code |
| `book_meta.json` | Per book: title, subtitle, author, credits, `layout`, `academic` (page footnotes + indented quotations, geometry-based), `unnumbered_sections`, `text_fixes`, `figure_captions` |
| `pdf_to_book.py` | Stage 2 for clean digital PDFs (no OCR): outline → sections, paragraphs by first-line indent (opt-in `margin`/`indent` rules in pdf_text), drop caps rejoined, check-mark-icon list items, tables rebuilt from small print using drawn cell edges (zebra rows defeat `find_tables`), centred lists, verses/translations/[sources] → same `book.json` |
| `pdf_text.py` | Shared reader for text PDFs (used by the two below): lines → paragraphs by line gap, headings by size, bold/italic, verse breaks; decodes old **Balaram**-font diacritics ("Kåñëa" → Kṛṣṇa) |
| `pdf_to_epub.py` | Text PDF with an outline → `.epub` beside it: chapters from the outline, cover from page 1, copyright and printed-contents pages left out |
| `book_to_epub.py` | Processed book (`book.json`) → `books/final/<book>_en.epub` with all figures; reuses `typeset_book.build_typst_data` (same crops as the PDF). Verse anthologies too (verse no., centred Sanskrit, bold-word gloss, translation, poet) |
| `epub_pack.py` | Shared EPUB packaging: XHTML template, CSS matching the PDF design, clickable nav + toc.ncx, cover, Gentium embedded |
| `pdf_to_docx.py` | Text PDF → editable `.docx` beside it (PyMuPDF lines → paragraphs by line gap, headings by size). Not `pdf2docx`: it works per character and corrupts Devanagari at line joins ("बड़ाायोगदान") |

Run Python with `poetry run python` (Python 3.12 from Homebrew; system 3.9 is too old for Surya).

## Book Studio (software/)

The desktop app runs `manual/pipeline` **unchanged**, pointed at its own data folder by `BOOK_STUDIO_DATA` / `BOOK_STUDIO_FONTS` / `BOOK_META_FILE` / `BOOK_STUDIO_FINAL` (read in `local_env.py`; unset = the repo layout). So every pipeline change ships to volunteers in the next release — run the regression check first. Pipeline hooks the app relies on: `ocr_all(..., after_chunk=)` (progress, pause, cool-down, stop), `book_cover()` + `cover_file` (chosen cover, PDF and EPUB), `copyright` in the meta (opt-in title-page line), `find_llama_server()`.

- Its environment comes from `software/uv.lock` via uv (`tools/uv/uv`, project-local): dev env in `.cache/bs-dev-venv`, test data in `BOOK_STUDIO_HOME=.cache/bs-test`. Never run `poetry` inside `software/` (it makes a stray `software/.venv`).
- Releases: bump `__version__`, `poetry run python software/build_zip.py`, `gh release create v<version> <zip>` — publishing is outward-facing, ask Devansh first. `build_zip.py` refuses to pack `book_meta.json` or book files.
- Surya starts llama-server detached and kills it from an atexit hook, so the worker stops via the control file (never a hard kill); after a forced kill, `engine.stop_stray_server()` uses Surya's sentinel in `~/.cache/datalab/surya/`.
- A test that presses the general *Make books* queues **every** unfinished book in the test library — real OCR for hours. In tests, pass the book: `make_books(["id"])`.
- Windows/Linux paths (launchers, Vulkan detection, Desktop icons) are untested on real machines.

## How to verify (do this every time)

- **`report.txt` is the source of truth for completeness.** Verse books: verse numbers continuous, every contents entry found. Prose books: every contents entry found in order, first words of each chapter sane, no unexplained blank pages. Check every flag against the scan (render with `pdftoppm` into `.cache/tmp/`, view, delete).
- **After changing shared code, prove finished books didn't change:** rebuild them and `cmp`/`diff` `book.json` and `pdftotext` output against the version in `books/final/`. Then delete the rebuild.
- Render a few pages of the new PDF and look at them before calling a book done; `pdffonts` should list only Gentium (a fallback font means a character Gentium lacks).
- **Bold and italic must survive** (the user checks this): italic Sanskrit terms and book titles, bold names, bold Sanskrit words in word-for-word glosses. Compare `<i>`/`<b>` span counts in `1-ocr/` with those in `2-assembled/book.json` per chapter (a chapter that loses them all means emphasis was stripped), and compare rendered pages with the scan side by side.

## OCR pitfalls already seen (and handled)

- Script-font headings misread: "Terse 45", "Verse .90", "Verse 28.3" → tolerant `VERSE_RE`.
- A heading labelled `PageHeader` ("Verse 80" at page top) → kept if it matches a verse heading.
- Chapter title + English title arriving as one block, two-line titles, or brackets dropped → three title shapes in `assemble_verses.py`; poet lines and "(Note: …)" footnotes must never count as titles.
- First Sanskrit line replaced by the first word-for-word line → re-OCR the block with `--fix`.
- `p` read as `ṭ` in titles ("Goṭī") → reconciled with the contents-page reading by word frequency, letter-level only.
- Contents page returned as one big picture (`<img/>`) → report's blank-page and contents checks catch it.
- Decorated drop caps: first letter misread ("Ifter") or second line damaged ("lego", "lobeisances") → `text_fixes`.
- Captions inside a picture's box are never OCR'd → `figure_captions`.
- Contents as "Chapter 1" (no page) + first place row + more place rows (A Spiritual Journey): the place rows are subheadings; closing sections after the last chapter must be listed in `unnumbered_sections`.
- Facsimiles (a newspaper clipping, a letter of Prabhupāda) get OCR'd as text — list their pages in `facsimile_pages` so the page becomes one picture + its caption.
- Italic letters with line breaks look like verses — books without verses set `italic_prose` (multi-line italic English is not separable from Tava's italic verse translations by any measure).
- Section headings that differ from the contents title ("Srila Prabhupada" printed as "His Divine Grace A.C. Bhaktivedanta Swami Prabhupada") → `heading_aliases` in `book_meta.json`. Indented letters without footnote handling → `inset_quotes` (`academic` = inset quotes + page footnotes).
- A font whose ṛ dot sits too low: the OCR reads "Krṣṇa" for the printed Kṛṣṇa (Dāmodara-jananī, 1,640 words) → `restore_r_dot` (vocabulary = the book's own correctly read ṛ words). Contents with dotted leaders, chapter labels as headings and paragraph entries → `contents_rows`. An index not in the contents plus endpapers → `last_page`.
- Scans with pages out of order (swapped pairs, duplicates, pages re-scanned and added at the end — When the Sun Shines): check printed page numbers, then `skip_pages` + `page_moves` [[page, after]]. Sections the contents doesn't list (a photo gallery, a Part whose title page has no heading) → `insert_sections` (kind, subtitle, `gallery` attaches text captions). OCR'd tables → `ocr_tables` (opt-in: Saṁskāras and Dancing White Elephants have Table blocks that were checked as text).
- A contents page set as plain text lines ("Foreword by Radhanath Swami ix") → `contents_pages` (read for the contents only, never for headings — its lines would match their own titles) + `chapter_subentries` (lines under a chapter are its subheadings).
- Labels glued to titles by the OCR ("CHAPTER EIGHTQUESTIONING…", "PART ONEASPECTS…") → `NUMBERED_LABEL_RE` strips number-word labels before matching; "Appendix 1: …" contents rows match their page heading without the prefix. Italic multi-line "headings" are verses. Part pages with a painting under the title (not a full-page cover) show it via the template's part-page.
- Running heads the OCR tags as headings ("Chapter Three : Bhaktivedānta!" on every page — Without Fear) → `running_heads` patterns, dropped only in a page's top 8% (the same words lower down are real labels). Contents with the page number first ("17 WITHOUT FEAR") and all-caps titles → handled in `contents_pages` mode + `smart_title`. Ņ/ņ (cedilla N) is never IAST → mapped to Ṇ/ṇ in `ocr_text.py` (ü is not: real in Müller, Krüger).
- Back cover (blurb, ISBN, barcode) leaking into the last chapter → `drop_back_cover`; a back cover without an ISBN (Saṁskāras) = the unnumbered last scan page with a picture covering ≥30% of it (a text-only closing page like Vraja's stays).
- Front-page photos need their own test: a faint swirl and Prabhupāda's pencil portrait look alike to any pixel measure, hence `frontispiece_skip` per book.
- Running headers returned as headings ("Yavat Part One" on every page) → dropped when they repeat the current section title.
- The contents page's own lines matching the titles they list → excluded from heading detection.

- Prose-book structure varies: contents as "Title – page" lines (Vraja), table rows (Tava, Saṁskāras), Parts with full-page paintings (Tava), Roman chapters whose numbered sub-sections are subheadings (Saṁskāras), front sections printed before the contents page, contents titles longer than the page heading → handled in `assemble_prose.py` (row-based contents, look-ahead matching, prefix/colon/bracket title matching).
- Endnotes under "NOTES" and page-bottom `Footnote` blocks → small-print Notes at the section end; `<sup>` markers kept.
- Scanner debris: text strips in the outer 8% side margin, blank versos detected as full-page "pictures" (kept only as Part paintings).
- A lowercase paragraph continues an earlier one — glued across pictures/verses, but never onto a paragraph that ended with . ! ?
- Characters Gentium lacks (♦ ► ▪ ➤ □ ⇒ ′ …) are mapped in `ocr_text.py`; `pdffonts` must show only Gentium.

## Typst gotchas

- Don't name a variable `v` — it shadows the `v()` spacing function.
- `block()` without `width: 100%` shrinks to its content, so "centred" text hugs the left margin.
- Gentium lacks `✦` (falls back to a math font) — the ornament is drawn with shapes.
- Typst only reads files under the project root, hence the temporary `.build/` folder.

## Remaining books (in `books/originals/`, which also keeps the scans of finished books)

- `transcendental-diary.pdf` — digital ebook (no OCR needed). A Hindi translation was declined pending the author's (Hari-śauri dāsa) permission; do not translate it in full without that.
