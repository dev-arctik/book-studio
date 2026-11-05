---
name: book-check
description: Check a finished book (PDF + EPUB) from the ISKCON book pipeline against its scan before it is called done — cover, contents with topics, centred headings, bold names and Sanskrit, signatures, verses, dedication, paragraphs, pictures, fonts, OCR scars. Use after every run, after publish_book.py, and whenever Devansh reports a defect in a published book. Also the place where each new defect type is added, so the check keeps improving.
---

<!-- book-studio/.claude/skills/book-check/SKILL.md
     The after-run check for every book, built from Devansh's reviews (logs.md, 2026-10-23 onward). Run it on each book; add every new defect type to "Lessons" at the bottom. -->

# Book check

Devansh (2026-10-23): "checking after the pipeline is run is very crucial." A run is not proof. Never call a book done on the strength of the run, `qa_book.py` alone, or a sample of one page. Look at the book against the scan.

Run from `book-studio/` with `.venv/Scripts/python.exe` (Bash) and `PYTHONUTF8=1`. The library is `../book-library/`. Book key = PDF name without `.pdf`.

## Steps

1. **Machine check first.** `publish_book.py` then `qa_book.py <batch folder> --library ../book-library` (helper: `.cache/tmp/pubqa.sh "<Group>" "<prefix>"`). Any `FAIL` is fixed before anything else; each `WARN` is looked at and either fixed or explained in the log.
2. **Look at the pages.** Render with `.cache/tmp/render_pages.py <pdf> <out.png> <pages> [scale]` into the scratchpad (count pages first; the scan page is not always the printed page) and read the PNGs. Pages to look at, always: cover, title, copyright, dedication, contents (first and last page), the first page of three different chapters (early, middle, last), one page with verses or a quotation, one page with a picture, one page near the end (back matter, index, adverts), and every page the OCR report flagged. Compare each with the scan page.
3. **Walk the checklist below**, book by book. Do not skip an item because the book "has none" — look, then say so.
4. **Fix at the right level.** A one-off goes in `book_meta.json` (`text_fixes`, `drop_headings`, `strip_text`, `right_lines`, `bold_speakers`, `cover_file`, `skip_pages`, `insert_sections` …). A defect that will come back in other books is fixed in the pipeline code, committed (no Co-Authored-By line), and described in `logs.md`.
5. **Rebuild and re-check** the fixed spots, then publish again (old version stays until the new one passes), run QA again.
6. **Report** to Devansh in plain words: what was checked, what was wrong, what was fixed, what is left as printed or left open.
7. **Log.** Append to `logs.md` (what went wrong / what I did by hand / pipeline fixes / ideas) and update `STATUS.md`. Add any NEW defect type to "Lessons" below.

## Checklist

**Cover and front**
- Page 1 is the supplied cover image (`cover_file`), full page, not a white title page. Names differ from the PDF names, so match the image by eye.
- Title page: title, subtitle, author, credits right; author comes from the scan when it is not in the file.
- Copyright page kept or dropped as intended (`keep_copyright`); no scanner watermark ("Digitized by eGangotri", "Z-Library"), no adverts.
- Dedication: its own page, centred, paragraphs whole (long lines run together, short poetic lines stay), no ornament text.

**Contents and headings**
- Contents lists every chapter with the right title and number, plus topics under each chapter (unless `no_topics`), and the page numbers land on the right pages (printed vs PDF offsets).
- No "Chapter 64" counting problem: unnumbered sections are `kind: back`, numbered titles ("3: Title") print their own number.
- Headings centred: label headings (SECTION, TRANSLATION, PURPORT, TEXT, SYNONYMS), all-caps headings, chapter titles. No duplicated "CHAPTER ONE / TITLE" blocks, no running heads left in the text, no lone "Contents" heading.
- Bookmarks and EPUB navigation match the contents.

**Names, bold and italic**
- Speaker names in dialogues are bold (`bold_speakers`; ALL-CAPS before a colon is automatic, lowercase names are listed). They must not be set as verses.
- Bold-only lines are headings; bold run-in headings are split off; bold subheadings at a page bottom are not glued to the next paragraph or inset.
- Sanskrit is italic with diacritics; in "word = meaning |" glosses the Sanskrit word is bold.
- Sanskrit names and terms keep their dots: Śrīla (not Śrila), Kṛṣṇa (not Krṣṇa — `restore_r_dot`), Prabhupāda, Bhāgavatam. Search the text for the usual OCR confusions.

**Alignment**
- Signatures and attributions ("—Radhanath Swami", "—George Harrison", names under quotations) are right-aligned (`right_lines`; "—Name" is automatic).
- Verses: centred like the original, verse number and source in the right place, translation kept with its verse, first line not cut off.
- Quotations and block quotes inset consistently; no decorative quotation glyphs ("66"/"99", empty “”) left as text.
- Centred poetry, dedications and title blocks are not broken where the scan page broke.

**Paragraphs and text**
- Paragraphs whole across page breaks; no fragments ("Sophistical, / materially conceived…"); no paragraph glued to the one before (a label ending in a colon at a page bottom); no sentence cut in two.
- No lost-ligature words (Te, Tis, afer), no look-alike letters (î â ş ţ), no Cyrillic or other stray scripts in captions, no leftover dot rows, "_____" rules or navigation lines ("Back to Contents").
- Lists and tables are real lists/tables (`ocr_tables`) and readable.

**Pictures**
- Pictures present where the scan has them, sharp (not 10-dpi thumbnails), not duplicated, no page-sized background or header banner repeated on every page, captions with the right picture.
- Sideways or fold-out pages are handled (`facsimile_pages`) or noted as open.

**Fonts and symbols**
- Only Gentium in the PDF (QA flags fallback fonts). Bullets, dingbats, danda, ℉ and private-use symbols mapped or replaced.

**Ends of the book**
- Last page is real content: no back cover blurb, ISBN, barcode, Z-Library advert; index/glossary either kept in order or left out knowingly; "About the Author" present only if the scan has it.

**Both formats**
- Open the EPUB too: cover, nav, a chapter, a verse page, a picture. Same text and order as the PDF.

## Lessons (add each new defect type here)

Format: date — book — what looked wrong — how it was found — fix (meta key or code).

- 2026-10-23 — Heart of Transcendental Book Distribution — published with its own white title page as cover while the supplied image sat unused — page 1 on a Kindle — `cover_file`; QA now fails a page 1 that is mostly white.
- 2026-10-23 — Vaiṣṇava-nindā — "SECTION 13" / "TRANSLATION" left-aligned, Sanskrit in glosses not bold — Kindle review — centred label headings and bold glosses in `typeset_book.py`.
- 2026-10-23 — Śuddha-nāma — contents had chapters only, verses off-centre — Kindle review — `sections_by_page` + topics from subheadings.
- 2026-10-24 — The Art of Teaching — speaker names (Teacher, Student, Śrīdāmā…) not bold — `bold_speakers`.
- 2026-10-26 — Conscious Reading, Spiritual Culture, Family Life, Bond of Love — dedication lines broke where the page broke; decorative quotes read as "66"/"99"; the name under the last quotation not right-aligned — `tidy_dedication`, `strip_text`, `right_lines`.
- 2026-10-26 — Spiritual Culture — "In the mode of ignorance:" glued to the paragraph before — bold labels never glue.
- 2026-10-26 — O Hare Krishna Airport — attribution names bold/left, 113 bold subheadings inset, verses and translations cut in pieces, dot rows as text — `book_tidy.py` (`"tidy": true`).
- 2026-10-27 — Following Śrīla Prabhupāda — speaker names set as verses — logged; check dialogues in every new book.
- 2026-10-27 — Radharani vol. 1 — drop cap on its own line glued to the chapter title ("PWho is…") — code fix in the digital route.
- 2026-10-31 — Lord Nrsimha — picture captions read as Cyrillic/Devanagari (QA font FAIL) — `text_fixes` after checking the scan.
- 2026-10-31 — Toward His Smiling Face — over 999 pages: page files sorted by name jumbled the order; part covers at 10 dpi; plain-titled back matter got "Chapter 64" — sort by number, `drop_pictures`, `kind: back`.
- 2026-11-05 — overview books, Balarāma, Dāmodara, My Prabhupāda, Nṛsiṁha — "CHAPTER 24" over "23: …" and "17. 1: …" in the contents — a reviewer read page 1 of a chapter and the contents — numbered titles carry no counter (`typeset_book.from_prose_book`); QA FAILs a label that disagrees with its title.
- 2026-11-05 — all OCR books — Śrila / Śri / Krṣṇa by the hundreds — search the text for them (QA WARN now) — Śrī rule in `ocr_text`, `restore_r_dot` in the meta.
- 2026-11-05 — The Veil — the supplied cover image belonged to another volume (Canto Ten on a Cantos Five and Six book) — compared the cover with the scan's page 1 — a supplied image is only right if the title and canto match the scan; otherwise use the scan's own cover.
- 2026-11-05 — Spiritual Tonic, Art of Transformation — banner and background pictures, dedication twice, every chapter twice in the contents, chapter tails under the next chapter — rendered the source page next to ours — page-sized backgrounds dropped, repeated titles dropped, section `markers` for mid-page starts.
- 2026-11-05 — Demons — Cyrillic look-alikes that Gentium can print (no fallback font) — text search for non-Latin letters — mapped in `pdf_text`, QA FAILs foreign scripts.
- 2026-11-05 — Following Śrīla Prabhupāda — a whole interview in one paragraph with bold names — read a conversation page — `book_tidy.dialogue_turns`.
- 2026-11-05 — Navadvipa — Bengali captions printed as empty boxes — removed in `ocr_text`.
- 2026-11-05 — drop caps (Navadvipa, Balarāma, Death, Kalachanji) — lone letters before text, "“T", a cap above small capitals — `settle_drop_caps`, `pdf_to_book`. A first letter lost without any block still needs a hand fix.
- Check this on every book: the section opens at the right line when a chapter starts mid-page (the previous chapter's tail must not sit under the new title).
