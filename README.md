# Education Material — Clean Book Pipeline + Book Studio

Turns scanned ISKCON books (Śrīla Prabhupāda and other ācāryas) into clean, readable PDFs for the kids at the youth forum — proper Sanskrit diacritics (ṣ ṇ ṁ ā …), one consistent book design, and the original photos and drawings kept. Each book becomes **one PDF**; chapters are cut out by hand where needed.

> **Private material.** These PDFs are supplied internally and are not released online. Everything here runs locally — nothing is uploaded. `books/` and `output/` are kept out of git and must never be pushed to GitHub or any shared drive.

## Book status

| Book | Author | Pages | Type | Status |
|---|---|---|---|---|
| Bhakti-bhāva | — | 65 / 74 | EN + HI | Translated earlier (our AI translation pipeline) — `books/final/pdf/` + `epub/` |
| Cāru Vilāsa Vol. 2 | — | 305 / 326 | EN + HI | Translated earlier (our AI translation pipeline) — `books/final/pdf/`, also as editable Word files in `books/final/word/` |
| Śrī Padyāvalī | Śrīla Rūpa Gosvāmī | 298 | Verse anthology | ✅ Done — `books/final/pdf/padyavali_en.pdf` |
| Vraja-Līlā Part Two | Deena Bandhu Dāsa | 265 | Prose + photos | ✅ Done — `books/final/pdf/vraja-lila-part2_en.pdf` |
| Tava Kathāmṛta | Śivarāma Swami | 415 | Prose: parts, endnotes, paintings | ✅ Done — `books/final/pdf/tava-kathamrita_en.pdf` |
| Sannyāsīs in Modernity | Yadunandana Swami | 419 | Academic prose: 189 footnotes, quotations, interviews | ✅ Done — `books/final/pdf/sannyasis-in-modernity_en.pdf` |
| Heart and Soul Connection | Grihastha Vision Team | 454 (digital) | Guide: cartoons, tables, verses — no OCR (`pdf_to_book.py`) | ✅ Done — `books/final/pdf/heart-and-soul-connection_en.pdf` + `epub/heart-and-soul-connection_en.epub` |
| Dancing White Elephants | Giriraj Swami | 405 | Prose: Prabhupāda's letters, 13 photo plates | ✅ Done — `books/final/pdf/dancing-white-elephants_en.pdf` + `epub/dancing-white-elephants_en.epub` |
| Śrī Dāmodara-jananī | Śivarāma Swami | 486 | Prose: 12 chapters, colour paintings, Vraja map | ✅ Done — `books/final/pdf/damodara-janani_en.pdf` + `epub/damodara-janani_en.epub` |
| When the Sun Shines | Ranchor Prime | 510 | History in 5 Books: 46 photos, disciples list and timeline tables | ✅ Done — `books/final/pdf/when-the-sun-shines_en.pdf` + `epub/when-the-sun-shines_en.epub` |
| I'll Build You a Temple | Giriraj Swami | 729 | The Juhu story: 5 chapters, letters, documents (photo plates not in the scan) | ✅ Done — `books/final/pdf/ill-build-you-a-temple_en.pdf` + `epub/ill-build-you-a-temple_en.epub` |
| Saṅkalpa-kaumudī | Śivarāma Swami | 984 | 8 Parts, 40 chapters, Part paintings, verses, footnotes | ✅ Done — `books/final/pdf/sankalpa-kaumudi_en.pdf` + `epub/sankalpa-kaumudi_en.epub` |
| Without Fear | Rūpa-vilāsa Dāsa | 594 | Glimpses of Śrīla Prabhupāda: 28 chapters, 147 photos, footnotes, captions appendix | ✅ Done — `books/final/pdf/without-fear_en.pdf` + `epub/without-fear_en.epub` |
| A Spiritual Journey | Prapujaka Das | 78 | Memoir: 21 photos, Prabhupāda's letters, facsimiles | ✅ Done — `books/final/pdf/a-spiritual-journey_en.pdf` |
| Book of Saṁskāras | Prema Rasa dāsa & Sāndīpani Muni dāsa | 323 | Ritual manual: mantras, footnotes | ✅ Done — `books/final/pdf/book-of-samskaras_en.pdf` |

## Two parts

| Folder | What it is | Status |
|---|---|---|
| `manual/` | The hand-run pipeline every finished book was made with: OCR → assemble → PDF + EPUB, driven from the terminal, one `book_meta.json` entry per book | In use — see `manual/README.md` |
| `software/` | **Book Studio**, a desktop app that runs the same pipeline on volunteers' computers (Mac, Windows, Linux): one zip, installs itself, cover shelf like Calibre, cover picker, copyright toggle, cool-down and core sliders, self-update from GitHub Releases | v0.1.0 built, tested on Mac — see `software/README.md` |

## Folder map

```
education-material/            git repo: code and docs only
├── manual/                    hand-run pipeline
│   ├── README.md              how to make a book, fix report flags, make EPUB/Word copies
│   └── pipeline/              the Python scripts, book_meta.json, book_template.typ
├── software/                  Book Studio desktop app
│   ├── README.md              how it works, running it from the repo, releasing an update
│   ├── book_studio/           the app (window, worker, setup, updater)
│   ├── launchers/ assets/ docs/   start scripts, icon + fonts, the volunteer guide
│   └── build_zip.py           → software/dist/BookStudio-<version>.zip
├── README.md · CLAUDE.md      this overview · rules and pitfalls for Claude Code
├── pyproject.toml             Python packages for the manual pipeline (Poetry)
│
│   — not in git (book content, large tools) —
├── books/
│   ├── final/                 processed books only, one folder per format: pdf/ (<book>_en.pdf, _hi.pdf), epub/, word/ (.docx)
│   └── originals/             every source scan as received (needed for rebuilds)
├── output/<book>/             work files per book: 1-ocr/ (keep — hours of OCR), 2-assembled/ (book.json + report.txt), 3-clean-pdf/, logs/
├── tools/                     llama-server (runs the OCR model) and the Gentium Book Plus font
├── .venv/   (hidden)          installed Python packages
└── .cache/  (hidden)          downloaded OCR model files, Poetry cache
```

Everything heavy (packages, AI model, caches) stays **inside this folder** — nothing is installed globally. To free the ~3–4 GB later, delete `.venv/`, `.cache/` and `tools/llama.cpp/`. Tip: in Finder, press `Cmd + Shift + .` to show hidden folders.

## Git

The repo tracks code and docs only and is published on GitHub (public), so Book Studio can update itself from GitHub Releases. `.gitignore` keeps out `books/`, `output/`, every `.pdf` / `.epub` / `.docx`, `manual/pipeline/book_meta.json` (book titles, captions and OCR-fix text fragments), the tools, the model and the environment — book content never goes to GitHub.
