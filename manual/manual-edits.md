# manual/manual-edits.md

Every manual edit Devansh asks for on a finished book: what he marked, what was changed, and where it now stands. Kept in the repo (Devansh, 2026-11-10: fine on GitHub). One row per edit, newest batch at the bottom. The fuller story of each fix (what went wrong, what was done by hand, the pipeline fix it suggests) is in the library's `workspace/logs.md` (local, not in git) under the same date and book.

## How edits come in

- Devansh's Google Doc **"fixes"** (https://docs.google.com/document/d/1Bai5JqnkQMAF8RqEtYZwfIK1D5P1V4tRX9_FtQltw4k/edit): phone/Kindle screenshots with the problem highlighted in orange, each followed by his note. Read it in the Claude desktop app's built-in browser through `…/mobilebasic` (text notes) plus a screenshot of each image.
- Each screenshot is matched to its book and published page by searching the published PDFs.
- Edits are made in `book_meta.json` (per-book settings), never by editing a finished PDF by hand; a defect that will come back in other books becomes a pipeline fix as well.
- Every edited book is rebuilt, its fixed pages are looked at in the PDF and the EPUB, QA must show 0 FAIL, and only then is it republished to its batch's `pdf/` and `epub/` — after which that batch needs re-uploading to Drive.

## Status key

- **done** — fixed, checked, republished
- **settings only** — settings saved, the book still waits for its rebuild (e.g. Groups 6/7, rebuilt by the pipeline session)
- **open** — not done yet (reason given)

## Edits

| Date | Source | Book (batch) | Page (published PDF) | Devansh's note | What was changed | Status |
|---|---|---|---|---|---|---|
| 2026-11-10 | fixes doc, screenshot 1 | Ocean of Mercy (Group 1) | 6 (Preface end) | "Keep the name of the person right hand side along with his other details" | `right_lines`: "Graham M. Schweig, Ph.D. (Garuḍa Dāsa)" and the "Author-Translator of *Dance of Divine Love*… (Princeton University Press, 2005)" line; `right_lines` now keeps italics (pipeline) | done |
| 2026-11-10 | fixes doc, screenshot 2 | Ocean of Mercy (Group 1) | 8 (Foreword end) | "Keep the name of the person right hand side" | `right_lines`: "Rādhānātha Swami" | done |
| 2026-11-10 | fixes doc, screenshot 3 | Ocean of Mercy (Group 1) | 198 (Gīta-govinda verse) | "Align this highlighted verse properly in the centre; the keśava dhṛta line is not properly aligned" | The verse's third line fell on the next scan page and was read as a heading: `strip_text` removes that copy, `text_fixes` puts it back as the verse's third line — one centred three-line verse | done |
| 2026-11-10 | our own check of screenshot 3 ("fix your finding also") | Ocean of Mercy (Group 1) | 198 | — | OCR misreads of the italic script corrected against the scan: viðher ababa → vidher ahaha, bṛdaya → hṛdaya, gbātam → ghātam, jagad-tśa → jagad-īśa; ð → d added to `ocr_text.py` for every book | done |
| 2026-11-10 | our own whole-book search | Ocean of Mercy (Group 1) | 53 (scan p65) | — | "ðhottu and kurtāu" → "*dhotīs* and *kurtās*" (`text_fixes`, checked against the scan); `cover_file` path updated `group1` → `Group 1` | done |
| 2026-11-10 | fixes doc, screenshots 4–5 | Chaurasi-kosa / Vraja Maṇḍala (Group 2) | 4–5 (scan 5–6) | "The dedication page must be separate from invocation and copyright information" | Nothing yet. Plan: a `sections` marker so Invocation starts its own section; copyright page dropped (`skip_pages` 6) or kept as its own page (`keep_copyright`) — Devansh to choose | open — reported, awaiting go-ahead |
| 2026-11-10 | fixes doc, screenshots 4–5 | Chaurasi-kosa (Group 2) | 4 (scan 5) | "The words must be properly aligned" / "The invocation must be properly aligned" | Nothing yet. The centred small-caps lines are read as left-aligned headings; the dedication tidy-up leaves headings alone | open — needs a pipeline fix (pipeline session) |
| 2026-11-10 | fixes doc, screenshot 6 | Chaurasi-kosa (Group 2) | 7 (scan 7) | "The signature name must be right hand side" | Nothing yet. Plan: `right_lines` for "Rajasekhara Dasa Brahmachari / Vrindavana Dhama, Kartika, 2018." | open — reported, awaiting go-ahead |
| 2026-11-10 | fixes doc, screenshots 7–8 | Chaurasi-kosa (Group 2) | 8 (scan 10) | "The points 1,2,3, and a,b,c, should be separate, don't keep them in one paragraph" | Nothing yet. Plan: split before each bold number/letter (`regex_fixes` / `numbered_items`) | open — reported, awaiting go-ahead |
| 2026-11-10 | fixes doc, screenshots 9–12 | Chaurasi-kosa (Group 2) | 166–167, 174, 176 and more (scan 120…) | "The paragraph is breaking … there are few more breaks … you have to fix which I have also not identified" | Nothing yet. Lines wrapped beside a map start further right and are read as a separate indented block; no setting can rejoin them | open — needs a pipeline fix in `pdf_to_book.py` (pipeline session) |
| 2026-11-10 | our own check of screenshots 9–12 | Chaurasi-kosa (Group 2) | throughout (e.g. 166) | — | Nothing yet. Place headings ("X.26 SURYA-KUNDA (Bharna Khurd)") run into their paragraph; a paragraph break lost before "One day the brahmana priest…" (same wrap cause) | open — reported, awaiting go-ahead |
| 2026-11-10 | fixes doc, screenshot 13 | When the Sun Shines (Mac library) | Book One opener | "Instead of book 1, book 2 … type part one, two, three … remove the small [title], keep only the orange (big one)" | Nothing | open — Mac-era book: original, workspace and settings are not on this laptop |
| 2026-11-10 | fixes doc (heading only) | I'll Build You a Temple (Mac library) | — | (no notes yet) | Nothing | open — no notes yet; also a Mac-era book |

Republished: **Ocean of Mercy** — `Group 1/pdf` and `Group 1/epub` (2026-11-10 13:31). Re-upload Group 1 to Drive.
