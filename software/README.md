# software/README.md

# Book Studio — desktop app

A desktop window around the `manual/` pipeline, so volunteers can turn scanned books into the same clean PDF + EPUB on their own computer — Mac, Windows or Linux, fully offline after the first start. Handed out as **one zip**; it installs itself into its own folder and updates itself from GitHub Releases.

Status: **v0.1.0 built.** Tested on the M4 Mac: setup (page reader + model), real OCR, chapters, PDF and EPUB identical to the manual pipeline's, the window offscreen. Windows and Linux launchers are written but untested on real machines.

## How volunteers use it

```
 BookStudio-0.1.0.zip → unzip → double-click "Start Book Studio" (.command / .bat / .sh)
   first time: uv → Python + packages into BookStudio/runtime/ (~10 min, internet)
   → window: setup dialog (page reader download, reading model download or "load from folder"), Desktop icon
 every day: Desktop icon → window → + Add books → (title / cover / copyright) → ▶ Make books → Open finished books
```

`BookStudio/HOW TO START.pdf` (from `docs/how-to-start.typ`) walks through this, including the one-time "unidentified developer" / "Windows protected your PC" warnings.

## Folder layout

```
software/
├── book_studio/            the app (Python package; `python -m book_studio`)
│   ├── paths.py            program / runtime / data folders; pipeline_env() points manual/pipeline at the data folder
│   ├── store.py            settings.json + library.json; meta_for() turns a book into its book_meta.json entry
│   ├── engine.py           llama-server download per OS (Metal / Vulkan → CPU fallback), model download/copy, Desktop icon
│   ├── worker.py           one book in its own process: OCR (with pause / cool-down / stop between batches) → assemble → PDF → EPUB
│   ├── updater.py          GitHub Releases check, download, staging in runtime/update/
│   └── ui/                 main window (cover shelf, book panel, status bar), dialogs, style
├── launchers/              Start Book Studio.command / .bat, start-book-studio.sh — install with uv, apply updates, open the window
├── assets/                 icon (png/ico/icns), Gentium fonts + OFL licence
├── docs/how-to-start.typ   the volunteer guide
├── build_zip.py            → dist/BookStudio-<version>.zip
└── pyproject.toml, uv.lock exact package versions for all three systems (Linux gets CPU-only PyTorch)
```

Inside the zip, `app/` = `book_studio/` + a copy of `manual/pipeline` (code and template only) + `assets/` + `pyproject.toml` + `uv.lock`. There is one pipeline: the app runs `manual/pipeline` unchanged, pointed at its data folder through the `BOOK_STUDIO_*` variables in `local_env.py`.

## Where things live on a volunteer's computer

| | |
|---|---|
| `BookStudio/app/` | The program — replaced by updates |
| `BookStudio/runtime/` | uv, Python, packages (`venv/`), staged update |
| Data folder | Mac `~/Library/Application Support/Book Studio`, Windows `%LOCALAPPDATA%\Book Studio`, Linux `~/.local/share/book-studio`: `library.json`, `settings.json`, `covers/`, `model/` (1.4 GB), `work/` (= the pipeline's project root: `books/<id>.pdf`, `output/<id>/1-ocr…`, `tools/llama.cpp`), `logs/` |
| Output folder | `PDF/<Title>.pdf` and `EPUB/<Title>.epub` — nothing else (default `~/Documents/Book Studio`) |

Updates never touch the data folder, so books, pages already read and settings survive them.

## Book settings (the 13 finished books' fixes)

`manual/pipeline/book_meta.json` holds titles, captions and OCR-fix text from the books, so it is **not** in git and **not** in the zip (the repo and releases are public). Share it privately; volunteers load it with Settings → Advanced → *Import book settings…* (it applies to books whose file name matches, e.g. `without-fear.pdf`). Running from the repo, the app reads it directly. New books need no settings; if one comes out wrong, *Book fixes…* edits the same options per book.

## Running from the repo (development)

```
# once: the app's own environment, from uv.lock (uv lives in tools/uv, not installed globally)
UV_CACHE_DIR=.cache/uv UV_PROJECT_ENVIRONMENT=$PWD/.cache/bs-dev-venv UV_PYTHON_INSTALL_DIR=$PWD/.cache/uv-python \
  UV_PYTHON_PREFERENCE=only-managed tools/uv/uv sync --frozen --project software
# run (BOOK_STUDIO_HOME keeps test data away from the real data folder)
cd software && BOOK_STUDIO_HOME=$PWD/../.cache/bs-test ../.cache/bs-dev-venv/bin/python -m book_studio
```

Don't run `poetry` inside `software/`: Poetry treats `software/pyproject.toml` as its own project and creates a stray `software/.venv`. Poetry is for the manual pipeline at the repo root.

## Releasing an update

1. Change the code; if `manual/pipeline` changed, prove the 13 books are unchanged (`CLAUDE.md` → How to verify).
2. Bump `__version__` in `book_studio/__init__.py` (e.g. 0.1.0 → 0.1.1). Changed packages: edit `pyproject.toml`, then `tools/uv/uv lock --project software`.
3. `poetry run python software/build_zip.py` → `software/dist/BookStudio-0.1.1.zip` (it refuses to pack `book_meta.json` or any book file).
4. Publish it as a GitHub Release whose tag is the version: `gh release create v0.1.1 software/dist/BookStudio-0.1.1.zip --title "Book Studio 0.1.1" --notes "What changed"` — the notes are shown in the update prompt.

Every copy checks `UPDATE_REPO` (`book_studio/__init__.py`, now `dev-arctik/book-studio`) a few seconds after it opens; only the version number is fetched. *Update now* downloads the zip, unpacks `app/` into `runtime/update/`, closes the window and runs the launcher with `--apply-update`, which swaps `app/`, installs changed packages and reopens Book Studio. The launchers themselves are not replaced by updates — a change to them means sending the new zip by hand.

## Known limits

- Windows and Linux are untested on real machines (launchers, Vulkan detection, Desktop icons).
- Unsigned: first start shows the Mac "unidentified developer" or Windows SmartScreen warning (the guide explains it).
- A new book with an unusual layout may need *Book fixes* — each of the 13 finished books needed at least one.
- Machines without a usable graphics card read pages on the processor, roughly 5–10× slower than the M4.
- PyTorch (~540 MB) is installed because Surya imports it, though the llama.cpp OCR barely uses it; dropping it is a planned update.
- Licences: Surya's code is GPL-3.0 and its model has its own licence (free for small organisations); Gentium is OFL. Distributing the app means its source must be available — the public repo covers that.
