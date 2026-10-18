# software/README.md

# Book Studio — desktop app (planned)

A downloadable app that runs the `manual/` pipeline on any volunteer's computer — no terminal, no internet once installed. Each person picks an input folder of PDFs and an output folder; the app produces the same clean PDF + EPUB as the manual pipeline. Results are shared between people by hand afterwards.

Status: **plan agreed, not built yet.** Open decisions are at the bottom.

## Tech stack

| Part | Tool | Why |
|---|---|---|
| Window | **PySide6 (Qt 6)** | Native window on Mac, Windows and Linux; same language as the pipeline, so no bridge layer |
| Logic + pipeline | **Python 3.12**, the `manual/pipeline` code reshaped into a library | Proven on 13 books (all rebuild byte-identical) — not rewritten |
| Background work | **QProcess** worker process | Window never freezes; Pause/Stop are clean; an OCR crash can't take the window down |
| Settings | JSON files in the app data folder | Readable, nothing to install |
| OCR | **llama-server** + Surya OCR 2 model (1.4 GB) | Same as manual |
| PDF / EPUB | **Typst** + Gentium + `book_template.typ`; `epub_pack` | Same approved design |
| Packaging | **PyInstaller** | One tool for all three systems (must run on each system to build for it) |

| System | Installer | OCR runs on |
|---|---|---|
| Mac (Apple chip) | `BookStudio.dmg` | Metal |
| Windows | `BookStudio-Setup.exe` (Inno Setup) | Vulkan (NVIDIA/AMD/Intel), CPU fallback |
| Linux | `BookStudio.AppImage` | Vulkan, CPU fallback |

The OCR model is downloaded on first launch, or loaded from a file (USB copy) — keeps the installer ~250 MB.

## Flow

```
 First launch:  install → "OCR model not found" → [Download] or [Load from file…]
                → pick Input folder and Output folder

 Every time:    app lists the PDFs in Input
                → per book (optional): title · subtitle · author · cover · copyright
                → [Start]

   OCR 4 pages at a time ──work N min──► rest M min ──► … (every page saved at once)
        │ all pages done
        ▼
   assemble → PDF + EPUB (seconds) → Output/<book>_en.pdf + .epub
        │
        ▼
   rest between books → next book
```

Cool-down only happens between 4-page batches; pausing, resting or closing the app loses at most the batch in progress. Changing a finished book's cover or title is a **Rebuild** (seconds, no OCR).

## Screen

```
┌─ Book Studio ─────────────────────────────────────────────────┐
│ Input  [ D:\books\in  ] [Browse]  Output [ D:\books\out ] [Browse]
├──────────────────────────┬────────────────────────────────────┤
│ BOOKS                    │ WITHOUT FEAR                       │
│ ✅ padyavali.pdf          │ Title    [Without Fear           ] │
│ ▶ without-fear.pdf       │ Subtitle [The Life and Times …   ] │
│ ⏸ new-book.pdf           │ Author   [Satsvarūpa dāsa Gosvāmī] │
│                          │ COVER  ┌──────┐ (•) Page 1 of PDF  │
│                          │        │previ.│ ( ) Own image      │
│                          │        └──────┘ [ Choose image… ]  │
│                          │ Copyright line on title page [off] │
│                          │ ▸ Book fixes (advanced)  [Rebuild] │
├──────────────────────────┴────────────────────────────────────┤
│ ████████████░░░░░░  368/594 pages · resting 11:42             │
│ [ Start ] [ Pause ]   Cool-down: work [60] rest [15] between [60]
│ ▸ Advanced: CPU cores ●─────○── 4/10 · OCR slots ●─○──── 4    │
└───────────────────────────────────────────────────────────────┘
```

| Setting | Scope | Effect |
|---|---|---|
| Title, subtitle, author | Per book | Title page |
| Cover — page 1 of PDF (default) or own image, picked one book at a time; the image is copied into the app's data | Per book | First PDF page + EPUB cover |
| Copyright line (default off) | Per book | Title page |
| Book fixes (advanced) | Per book | The `book_meta.json` options (skip pages, running heads, text fixes…) |
| Work / rest / between-books minutes | Per computer | When OCR pauses |
| CPU cores slider | Per computer | `llama-server --threads` |
| OCR slots slider (shows memory estimate) | Per computer | `SURYA_INFERENCE_PARALLEL` |

The 13 finished books' settings ship built in, so their scans give the same result as the manual pipeline.

## Where files live

| | Contents |
|---|---|
| Input folder (user's) | Source PDFs, cover photos — only read, never changed |
| Output folder (user's) | Only `<book>_en.pdf` and `<book>_en.epub` |
| App data (hidden) | Per-book OCR pages, cover copy, settings; app settings; the model. Mac `~/Library/Application Support/Book Studio`, Windows `%LOCALAPPDATA%\Book Studio`, Linux `~/.local/share/book-studio`. A **Clear working files** button frees the space after a book |

## Build order

| Phase | Result |
|---|---|
| 1 | Pipeline as a library — settings passed in, not read from the repo; regression `cmp` identical for all 13 books |
| 2 | PySide6 window: folders, queue, progress, cool-down, sliders, cover and copyright |
| 3 | Mac `.dmg`, tested on the M4 |
| 4 | Windows `.exe` and Linux `.AppImage`, tested on real machines |
| 5 | Report-flag view with scan previews + Book fixes panel |

## Known limits

- A new book with an unusual layout may still need someone to set a Book fix — the 13 finished books each needed at least one.
- Machines without a usable graphics card run OCR on CPU, roughly 5–10× slower than the M4.
- Unsigned installers show a warning (Mac "unidentified developer", Windows SmartScreen) unless certificates are bought.

## Open decisions

1. How the three builds are made: GitHub Actions (code only, never books — needs a git remote) or one machine of each system.
2. Signing: accept the warnings with a how-to-open note, or buy certificates.
