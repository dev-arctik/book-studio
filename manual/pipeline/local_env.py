# manual/pipeline/local_env.py
# Single source of truth for project paths: where books, outputs, tools, and caches live, plus the numbered output stage folders.
# Also pins every model download/cache to the library folder so nothing lands in global locations.
# Book Studio (software/) runs this same code against its own data folder by setting the BOOK_STUDIO_* variables below.
# Run by hand, every script needs the library folder (--library PATH, or BOOK_LIBRARY) and the book as a path to its PDF.
# Import this module FIRST in any pipeline script, before importing surya or huggingface_hub (they read env vars at import time).

import os
import sys
from pathlib import Path

USAGE = "Usage: poetry run python manual/pipeline/<script>.py <path/to/book.pdf> --library <path/to/book-library>"


def _take_option(flag: str) -> str | None:
    """Removes '--library PATH' from the command line, so each script's own arguments stay as they were."""
    if flag not in sys.argv:
        return None
    i = sys.argv.index(flag)
    if i + 1 >= len(sys.argv):
        sys.exit(f"{flag} needs a folder.\n{USAGE}")
    value = sys.argv[i + 1]
    del sys.argv[i : i + 2]
    return value


# Code and books live apart: this file sits in <repo>/manual/pipeline/; books, OCR work, tools and the model live in a library
# folder outside the public repo, given explicitly. Book Studio uses its own per-computer data folder (BOOK_STUDIO_DATA).
# Inside: book_meta.json, workspace/ (the working area: <book>/ stages, logs.md, STATUS.md) and the finished books in pdf/ and epub/.
# The scans stay wherever the user keeps them — every run is given the path of the book's file.
PIPELINE_DIR = Path(__file__).resolve().parent
_library = os.environ.get("BOOK_STUDIO_DATA") or _take_option("--library") or os.environ.get("BOOK_LIBRARY")
if not _library:
    sys.exit(f"Which library folder? Give it with --library (the folder with books/ and book_meta.json).\n{USAGE}")
PROJECT_ROOT = Path(_library).expanduser().resolve()
if not PROJECT_ROOT.is_dir():
    sys.exit(f"The library folder doesn't exist: {PROJECT_ROOT}")
BOOKS_DIR = PROJECT_ROOT / "books"  # only Book Studio's data folder has one; run by hand the books are given by path
# The working area: each book's stage folders, logs.md (what had to be fixed by hand, for improving the pipeline) and STATUS.md.
# Book Studio's data folder keeps its own name for it.
WORKSPACE_DIR = PROJECT_ROOT / ("output" if os.environ.get("BOOK_STUDIO_DATA") else "workspace")
# Software (llama-server, fonts, the OCR model) is not a book: run by hand it lives with the code in the repo (git-ignored);
# Book Studio keeps its own copy in its data folder
SOFTWARE_ROOT = Path(os.environ["BOOK_STUDIO_DATA"]) if os.environ.get("BOOK_STUDIO_DATA") else PIPELINE_DIR.parent.parent
TOOLS_DIR = SOFTWARE_ROOT / "tools"
FONTS_DIR = Path(os.environ.get("BOOK_STUDIO_FONTS") or TOOLS_DIR / "fonts")
CACHE_DIR = SOFTWARE_ROOT / ".cache"
# Per-book settings; Book Studio writes its own merged copy (built-in settings + what the user edited in the app)
META_FILE = Path(os.environ.get("BOOK_META_FILE") or PROJECT_ROOT / "book_meta.json")
FINAL_DIR = Path(os.environ.get("BOOK_STUDIO_FINAL") or PROJECT_ROOT)
# Each format in its own folder, so PDFs, e-books and Word files are easy to find and hand out separately
FINAL_KINDS = {".pdf": "pdf", ".epub": "epub", ".docx": "word"}

# Numbered so the folders sort in the order the pipeline runs them
STAGES = {
    "ocr": "1-ocr",
    "assembled": "2-assembled",
    "clean-pdf": "3-clean-pdf",
    "epub": "4-epub",
    "logs": "logs",
}


def stage_dir(book: str, stage: str) -> Path:
    """workspace/<book>/<numbered stage folder>, created on first use."""
    path = WORKSPACE_DIR / book.rstrip(". ") / STAGES[stage]  # (Windows drops a trailing dot from a folder name: "…Mitali C." is "…Mitali C")
    path.mkdir(parents=True, exist_ok=True)
    return path


def win_long(path) -> Path:
    """A path over about 250 characters (a long book name appears in the folder and again in the file name) needs Windows' long-path prefix for Python to open it."""
    path = Path(path)
    full = str(path.resolve())
    prefix = chr(92) * 2 + "?" + chr(92)  # two backslashes, a question mark, one backslash
    _unused ="\\?\\"
    return Path(prefix + full) if os.name == "nt" and len(full) > 250 and not full.startswith(prefix) else path


def final_path(filename: str, batch: Path | None = None) -> Path:
    """<pdf|epub|word>/<filename> — where a finished, checked file goes, by its format. In the batch folder the book came from
    (group1/pdf, group1/epub — Devansh's layout, 2026-10-20) when 'batch' is given and Book Studio's own folder is not set; else in the library."""
    folder = (batch if batch and not os.environ.get("BOOK_STUDIO_FINAL") else FINAL_DIR) / FINAL_KINDS[Path(filename).suffix.lower()]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / filename


_given: dict[str, Path] = {}  # books given by path in this run, by name — later stages and helpers ask for them by name


def book_path(arg: str) -> Path:
    """The book named on the command line: must be a path to its PDF. Its file name (without .pdf) is the book's key in
    output/ and book_meta.json."""
    path = Path(arg).expanduser()
    if path.suffix.lower() != ".pdf" or not path.is_file():
        sys.exit(f"Not a PDF file: {arg}\nGive the path of the book's PDF.\n{USAGE}")
    path = path.resolve()
    _given[path.stem] = path
    return path


def find_book(name: str) -> Path:
    """A book's PDF by its key: the path given on the command line in this run, else books/<name>.pdf in the library."""
    if Path(name).suffix.lower() == ".pdf" and Path(name).is_file():
        return book_path(name)
    key = name[:-4] if name.endswith(".pdf") else name
    if key in _given:
        return _given[key]
    matches = list(BOOKS_DIR.rglob(f"{key}.pdf"))
    if not matches:
        raise FileNotFoundError(f"No book named {key}.pdf under {BOOKS_DIR}")
    return matches[0]


def find_llama_server(tools_dir: Path = TOOLS_DIR) -> Path | None:
    """The prebuilt llama-server under tools/llama.cpp (Mac/Linux archives unpack into a folder, Windows zips don't)."""
    return next(iter(sorted((tools_dir / "llama.cpp").rglob("llama-server.exe" if os.name == "nt" else "llama-server"))), None)


# Prebuilt llama.cpp binary lives in tools/ instead of a global brew install
LLAMA_SERVER = find_llama_server()

# setdefault so a caller can still override from the shell if needed
os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))
os.environ.setdefault("MODEL_CACHE_DIR", str(CACHE_DIR / "models"))
os.environ.setdefault("TORCH_HOME", str(CACHE_DIR / "torch"))
os.environ.setdefault("SURYA_INFERENCE_BACKEND", "llamacpp")
# 4 parallel slots, not Surya's 8: ocr_book.py sends 4 pages per call, and each slot reserves its own KV-cache memory —
# with 8 the OCR server held ~11 GB of this 16 GB Mac and forced heavy swapping
os.environ.setdefault("SURYA_INFERENCE_PARALLEL", "4")
# No prompt cache: llama-server keeps up to 8 GB of past requests in RAM in case they repeat, but every OCR request is a
# different page — the cache never hits and only grew the server to ~10 GB
os.environ.setdefault("LLAMA_CPP_EXTRA_ARGS", "--cache-ram 0")
if LLAMA_SERVER:
    os.environ.setdefault("LLAMA_CPP_BINARY", str(LLAMA_SERVER))
# The OCR model as two plain files in .cache/models-gguf (the pinned download, as Book Studio fetched it): used instead of the
# Hugging Face cache when present, so the laptop needs no Hugging Face login or cache layout
_GGUF_DIR = CACHE_DIR / "models-gguf"
if (_GGUF_DIR / "surya-2.gguf").exists() and (_GGUF_DIR / "surya-2-mmproj.gguf").exists():
    os.environ.setdefault("SURYA_GGUF_LOCAL_MODEL_PATH", str(_GGUF_DIR / "surya-2.gguf"))
    os.environ.setdefault("SURYA_GGUF_LOCAL_MMPROJ_PATH", str(_GGUF_DIR / "surya-2-mmproj.gguf"))
