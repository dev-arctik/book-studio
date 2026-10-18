# software/book_studio/paths.py
# Where Book Studio's pieces live: the program folder (replaced by updates), the runtime (uv, Python, packages, made by the
# launcher) and the per-computer data folder (books, OCR work, settings, model) that updates never touch.

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent  # BookStudio/app in the zip; software/ in the repo
BUNDLE_DIR = APP_DIR.parent
RUNTIME_DIR = BUNDLE_DIR / "runtime"
IS_INSTALLED = RUNTIME_DIR.is_dir()  # started from an unzipped BookStudio folder, not from the repo
ASSETS_DIR = APP_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
# The shared pipeline: copied into the zip as app/pipeline; in the repo it is manual/pipeline
PIPELINE_DIR = next(p for p in (APP_DIR / "pipeline", BUNDLE_DIR / "manual" / "pipeline") if (p / "local_env.py").exists())


def _data_dir() -> Path:
    if os.environ.get("BOOK_STUDIO_HOME"):  # tests and portable use
        return Path(os.environ["BOOK_STUDIO_HOME"])
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Book Studio"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Book Studio"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "book-studio"


DATA_DIR = _data_dir()
WORK_DIR = DATA_DIR / "work"  # the pipeline's project root: books/<id>.pdf, output/<id>/1-ocr…, tools/llama.cpp
MODEL_DIR = DATA_DIR / "model"
COVERS_DIR = DATA_DIR / "covers"
THUMBS_DIR = DATA_DIR / "thumbs"
LOGS_DIR = DATA_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "settings.json"
LIBRARY_FILE = DATA_DIR / "library.json"
BUILTIN_META_FILE = DATA_DIR / "builtin_meta.json"  # imported book settings (the 13 finished books' fixes)
MERGED_META_FILE = DATA_DIR / "book_meta.json"  # what the pipeline reads: built-in settings + the user's edits
CONTROL_FILE = DATA_DIR / "control.json"  # window → worker: pause / stop / skip rest

MODEL_FILES = ("surya-2.gguf", "surya-2-mmproj.gguf")


def ensure_dirs() -> None:
    for d in (WORK_DIR / "books", MODEL_DIR, COVERS_DIR, THUMBS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def pipeline_env() -> dict:
    """Environment that points the shared pipeline at this computer's data folder instead of the repo."""
    return {
        "BOOK_STUDIO_DATA": str(WORK_DIR),
        "BOOK_STUDIO_FONTS": str(FONTS_DIR),
        "BOOK_META_FILE": str(MERGED_META_FILE),
        "BOOK_STUDIO_FINAL": str(WORK_DIR / "final"),
        "SURYA_GGUF_LOCAL_MODEL_PATH": str(MODEL_DIR / MODEL_FILES[0]),
        "SURYA_GGUF_LOCAL_MMPROJ_PATH": str(MODEL_DIR / MODEL_FILES[1]),
    }
