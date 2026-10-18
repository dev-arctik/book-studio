# Book Studio

**Turn scanned books into clean, readable PDFs and e-books — on your own computer, with a few clicks.**

Book Studio takes a scanned book (a PDF of page photos) and makes a fresh, cleanly set **PDF** and an **EPUB** e-book from it: real text you can search and copy, correct Sanskrit diacritics (ṣ ṇ ṁ ā ī ū ṛ …), the original photos and paintings kept, the book's own chapters with a clickable contents page, and the original cover. It also takes digital PDFs that already have text and gives them the same clean design.

## Why it exists

Many devotional books — memoirs of Śrīla Prabhupāda's disciples, Vaiṣṇava poetry, histories of the early movement — exist only as scans: heavy files of page photos, hard to read on a phone, impossible to search, and useless on a Kindle. Ordinary OCR mangles diacritics ("Krsna", "Kåñëa") and loses the book's structure.

Book Studio was made for an ISKCON youth forum, to give young readers these books in a form they will actually read — and so that **volunteers who aren't technical** can do the work on their own laptops. Everything runs **offline on the volunteer's computer**: the books never leave it, and no account or paid service is needed.

## What it does

```
 scanned PDF  →  Read  →  Chapters  →  PDF  →  EPUB
                 (OCR)    (from the     (A5,     (Kindle and
                          book's own    Gentium  other
                          contents)     font)    e-readers)
```

- **Reads every page** with a local OCR model (Surya OCR via llama.cpp) that keeps diacritics, italics and bold.
- **Finds the chapters** from the book's own contents page, and keeps verses, quotations, footnotes, tables, and photos with their captions.
- **Sets a clean A5 PDF** in Gentium (a font made for full diacritic support), opening with the original cover — and keeps the book's copyright page unless you untick it.
- **Makes an EPUB** with the same chapters, pictures and a clickable contents.
- **Checks itself**: after each book, *Check book* says in plain words whether every chapter was found and which pages deserve a look, next to the scanned page.

## How to use it

### Install (once, about 10 minutes, needs internet once)

1. Download **`BookStudio-<version>.zip`** from this repository's [**Releases**](../../releases) page and unzip it somewhere it can stay (e.g. Documents).
2. Open the **BookStudio** folder and start it:
   - **Mac:** double-click `Start Book Studio.command`. The first time, right-click it → *Open* → *Open* (it isn't signed by Apple). If it opens in a text editor, right-click → *Open With* → *Terminal*.
   - **Windows:** double-click `Start Book Studio.bat`. If "Windows protected your PC" appears, click *More info* → *Run anyway*.
   - **Linux:** run `sh start-book-studio.sh` in a terminal (Ubuntu may need `sudo apt install libxcb-cursor0`).
3. Book Studio installs its own Python and parts into that folder (your computer's own Python is not used or changed), then asks for the **reading model** (1.4 GB): *Download it*, or *Load from a folder* if someone gave you a copy on a USB stick.
4. From then on, open it from the **Book Studio** icon (Applications on Mac, Start menu on Windows).

`HOW TO START.pdf` inside the zip walks through the same steps.

### Make books

1. **＋ Add books** — choose PDF files, or a whole folder of them. Each book gets a row.
2. **Tick** the books to make (*Select all* ticks every one). Click a row to check the title, author and cover, or to choose your own cover picture.
3. **▶ Make ticked books.** Each row shows where its book is — **Read → Chapters → PDF → EPUB** — with pages done and time left; the card at the top shows the whole run.
4. **Open finished books** → *PDF folder* / *EPUB folder* (choose where they go with **Output folders…**).

Reading pages is slow — a 500-page book takes several hours on a laptop. You can **Pause**, **Stop** (keeping or deleting what was done), or even close Book Studio: pages already read are kept, and *Make* continues where it stopped. By default it works 60 minutes, then **rests 15** so laptops cool down, and rests between books (change it in *Settings*). Keep a laptop **plugged in** with the lid open: Book Studio keeps the computer from sleeping while it works, and **pauses by itself below 15 % battery** until the charger is plugged in. Book details (cover, title, copyright page) can be changed while a book is being read — they are used when its PDF is made.

### Updates

Every time it opens, Book Studio first checks for a new version here; if there is one, it asks *There is an update — do you want to update now?* Your books, settings and pages already read are kept.

## Privacy

Books are processed only on the computer running Book Studio. It goes online for three things only: installing itself, downloading the reading model, and checking for updates (which sends nothing but a request for the latest version number). This repository contains code and documentation only — no books.

## For developers

| Folder | What it is |
|---|---|
| [`software/`](software/README.md) | Book Studio: the window (PySide6), the worker that runs the pipeline per book, setup, updates, launchers, the release zip builder |
| [`manual/`](manual/README.md) | The pipeline itself (OCR → chapters → Typst PDF → EPUB), also usable from the terminal, with per-book settings for books that need special handling |

Book Studio runs `manual/pipeline` unchanged, pointed at its own data folder — one pipeline, two ways to drive it. To release a new version, see [`software/README.md`](software/README.md#releasing-an-update). Rules and pitfalls for working on the code are in `CLAUDE.md`.

Built with [Surya OCR](https://github.com/datalab-to/surya) (GPL-3.0; its model has its own licence), [llama.cpp](https://github.com/ggml-org/llama.cpp), [Typst](https://typst.app), [PyMuPDF](https://pymupdf.readthedocs.io), [PySide6](https://doc.qt.io/qtforpython-6/) and the [Gentium](https://software.sil.org/gentium/) font (SIL Open Font License).
