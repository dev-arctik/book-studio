# pipeline/local_env.py
# Single source of truth for project paths: where books, outputs, tools, and caches live, plus the numbered output stage folders.
# Also pins every model download/cache to this project folder so nothing lands in global locations.
# Import this module FIRST in any pipeline script, before importing surya or huggingface_hub (they read env vars at import time).

import os
from pathlib import Path

# This file sits in manual/pipeline/; books, outputs, tools and caches stay at the repo root (shared, git-ignored)
PIPELINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PIPELINE_DIR.parent.parent
BOOKS_DIR = PROJECT_ROOT / "books"
OUTPUT_DIR = PROJECT_ROOT / "output"
TOOLS_DIR = PROJECT_ROOT / "tools"
FONTS_DIR = TOOLS_DIR / "fonts"
CACHE_DIR = PROJECT_ROOT / ".cache"

# Numbered so the folders sort in the order the pipeline runs them
STAGES = {
    "ocr": "1-ocr",
    "assembled": "2-assembled",
    "clean-pdf": "3-clean-pdf",
    "logs": "logs",
}


def stage_dir(book: str, stage: str) -> Path:
    """output/<book>/<numbered stage folder>, created on first use."""
    path = OUTPUT_DIR / book / STAGES[stage]
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_book(name: str) -> Path:
    """Resolve 'padyavali' or 'padyavali.pdf' to its file anywhere under books/."""
    filename = name if name.endswith(".pdf") else f"{name}.pdf"
    matches = list(BOOKS_DIR.rglob(filename))
    if not matches:
        raise FileNotFoundError(f"No book named {filename} under {BOOKS_DIR}")
    return matches[0]


# Prebuilt llama.cpp binary lives in tools/ instead of a global brew install
LLAMA_SERVER = next((TOOLS_DIR / "llama.cpp").glob("*/llama-server"), None)

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
