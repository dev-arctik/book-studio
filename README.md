# Education Material — Clean Book Pipeline + Book Studio

Turns scanned ISKCON books (Śrīla Prabhupāda and other ācāryas) into clean, readable PDFs for the kids at the youth forum — proper Sanskrit diacritics (ṣ ṇ ṁ ā …), one consistent book design, and the original photos and drawings kept. Each book becomes **one PDF**; chapters are cut out by hand where needed.

> **Private material.** These PDFs are supplied internally and are not released online. Everything here runs locally — nothing is uploaded. `books/` and `output/` are kept out of git and must never be pushed to GitHub or any shared drive.

## Book status

| Book | Author | Pages | Type | Status |
|---|---|---|---|---|
| Bhakti-bhāva | — | 65 / 74 | EN + HI | Translated earlier (our AI translation pipeline) — `books/final/` |
| Cāru Vilāsa Vol. 2 | — | 305 / 326 | EN + HI | Translated earlier (our AI translation pipeline) — `books/final/`, also as editable Word files (`charu-vilas-vol2_en.docx`, `_hi.docx`) |
| Śrī Padyāvalī | Śrīla Rūpa Gosvāmī | 298 | Verse anthology | ✅ Done — `books/final/padyavali_en.pdf` |
| Vraja-Līlā Part Two | Deena Bandhu Dāsa | 265 | Prose + photos | ✅ Done — `books/final/vraja-lila-part2_en.pdf` |
| Tava Kathāmṛta | Śivarāma Swami | 415 | Prose: parts, endnotes, paintings | ✅ Done — `books/final/tava-kathamrita_en.pdf` |
| Sannyāsīs in Modernity | Yadunandana Swami | 419 | Academic prose: 189 footnotes, quotations, interviews | ✅ Done — `books/final/sannyasis-in-modernity_en.pdf` |
| Heart and Soul Connection | Grihastha Vision Team | 454 (digital) | Guide: cartoons, tables, verses — no OCR (`pdf_to_book.py`) | ✅ Done — `books/final/heart-and-soul-connection_en.pdf` + `.epub` |
| Dancing White Elephants | Giriraj Swami | 405 | Prose: Prabhupāda's letters, 13 photo plates | ✅ Done — `books/final/dancing-white-elephants_en.pdf` + `.epub` |
| Śrī Dāmodara-jananī | Śivarāma Swami | 486 | Prose: 12 chapters, colour paintings, Vraja map | ✅ Done — `books/final/damodara-janani_en.pdf` + `.epub` |
| When the Sun Shines | Ranchor Prime | 510 | History in 5 Books: 46 photos, disciples list and timeline tables | ✅ Done — `books/final/when-the-sun-shines_en.pdf` + `.epub` |
| I'll Build You a Temple | Giriraj Swami | 729 | The Juhu story: 5 chapters, letters, documents (photo plates not in the scan) | ✅ Done — `books/final/ill-build-you-a-temple_en.pdf` + `.epub` |
| Saṅkalpa-kaumudī | Śivarāma Swami | 984 | 8 Parts, 40 chapters, Part paintings, verses, footnotes | ✅ Done — `books/final/sankalpa-kaumudi_en.pdf` + `.epub` |
| Without Fear | Rūpa-vilāsa Dāsa | 594 | Glimpses of Śrīla Prabhupāda: 28 chapters, 147 photos, footnotes, captions appendix | ✅ Done — `books/final/without-fear_en.pdf` + `.epub` |
| A Spiritual Journey | Prapujaka Das | 78 | Memoir: 21 photos, Prabhupāda's letters, facsimiles | ✅ Done — `books/final/a-spiritual-journey_en.pdf` |
| Book of Saṁskāras | Prema Rasa dāsa & Sāndīpani Muni dāsa | 323 | Ritual manual: mantras, footnotes | ✅ Done — `books/final/book-of-samskaras_en.pdf` |

## Two parts

| Folder | What it is | Status |
|---|---|---|
| `manual/` | The hand-run pipeline every finished book was made with: OCR → assemble → PDF + EPUB, driven from the terminal, one `book_meta.json` entry per book | In use — see `manual/README.md` |
| `software/` | **Book Studio**, a desktop app (`.dmg` / `.exe` / `.AppImage`) that wraps the same pipeline so volunteers can run it on their own computers: input and output folders, cover picker, copyright toggle, cool-down and core sliders | Planned — see `software/README.md` |

## Folder map

```
education-material/            git repo: code and docs only
├── manual/                    hand-run pipeline
│   ├── README.md              how to make a book, fix report flags, make EPUB/Word copies
│   └── pipeline/              the Python scripts, book_meta.json, book_template.typ
├── software/                  Book Studio desktop app (planned)
│   └── README.md              the agreed plan: tech stack, flow, screens
├── README.md · CLAUDE.md      this overview · rules and pitfalls for Claude Code
├── pyproject.toml             Python packages for the manual pipeline (Poetry)
│
│   — not in git (book content, large tools) —
├── books/
│   ├── final/                 processed books only: <book>_en.pdf / _hi.pdf (and .docx / .epub)
│   └── originals/             every source scan as received (needed for rebuilds)
├── output/<book>/             work files per book: 1-ocr/ (keep — hours of OCR), 2-assembled/ (book.json + report.txt), 3-clean-pdf/, logs/
├── tools/                     llama-server (runs the OCR model) and the Gentium Book Plus font
├── .venv/   (hidden)          installed Python packages
└── .cache/  (hidden)          downloaded OCR model files, Poetry cache
```

Everything heavy (packages, AI model, caches) stays **inside this folder** — nothing is installed globally. To free the ~3–4 GB later, delete `.venv/`, `.cache/` and `tools/llama.cpp/`. Tip: in Finder, press `Cmd + Shift + .` to show hidden folders.

## Git

The repo tracks code and docs only. `.gitignore` keeps out `books/`, `output/`, every `.pdf` / `.epub` / `.docx`, the tools, the model and the environment — book content never goes into git. There is no remote: nothing is pushed anywhere unless that is decided explicitly.
