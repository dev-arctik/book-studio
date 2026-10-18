# software/build_zip.py
# Builds the file volunteers download: software/dist/BookStudio-<version>.zip (one zip for Mac, Windows and Linux).
# Contents: the launchers, "HOW TO START.pdf", and app/ = book_studio + a copy of manual/pipeline + assets + pyproject/uv.lock.
# Never packs book content: book_meta.json (titles, captions, OCR-fix text) and any PDF/EPUB other than the guide are refused.
# Usage (from the repo root): poetry run python software/build_zip.py

import re
import sys
import zipfile
from pathlib import Path

import typst

SOFTWARE = Path(__file__).resolve().parent
REPO = SOFTWARE.parent
PIPELINE = REPO / "manual" / "pipeline"
DIST = SOFTWARE / "dist"
PIPELINE_FILES = ["*.py", "book_template.typ"]  # code and the page design only — book_meta.json stays out on purpose
FORBIDDEN = re.compile(r"book_meta\.json$|\.(pdf|epub|docx|gguf)$", re.I)


def version() -> str:
    return re.search(r'__version__ = "([^"]+)"', (SOFTWARE / "book_studio" / "__init__.py").read_text()).group(1)


def entries() -> list[tuple[str, bytes, int]]:
    """(path inside the zip, content, unix mode)."""
    out = []

    def add_tree(src: Path, dest: str, patterns=("**/*",)):
        for pattern in patterns:
            for f in sorted(src.glob(pattern)):
                if f.is_file() and "__pycache__" not in f.parts and f.name != ".DS_Store":
                    out.append((f"{dest}/{f.relative_to(src).as_posix()}", f.read_bytes(), 0o644))

    add_tree(SOFTWARE / "book_studio", "BookStudio/app/book_studio", ("**/*.py",))
    add_tree(PIPELINE, "BookStudio/app/pipeline", PIPELINE_FILES)
    add_tree(SOFTWARE / "assets", "BookStudio/app/assets")
    for name in ("pyproject.toml", "uv.lock"):
        out.append((f"BookStudio/app/{name}", (SOFTWARE / name).read_bytes(), 0o644))
    for f in sorted((SOFTWARE / "launchers").iterdir()):
        data = f.read_bytes()
        if f.suffix == ".bat":  # cmd.exe needs Windows line endings
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        out.append((f"BookStudio/{f.name}", data, 0o755 if f.suffix in (".sh", ".command") else 0o644))
    guide = typst.compile(str(SOFTWARE / "docs" / "how-to-start.typ"), font_paths=[str(SOFTWARE / "assets" / "fonts")],
                          ignore_system_fonts=True)
    out.append(("BookStudio/HOW TO START.pdf", guide, 0o644))
    return out


def main():
    files = entries()
    bad = [name for name, _, _ in files if FORBIDDEN.search(name) and name != "BookStudio/HOW TO START.pdf"]
    if bad:
        sys.exit(f"Refusing to build: book content would be packed: {bad}")
    DIST.mkdir(exist_ok=True)
    target = DIST / f"BookStudio-{version()}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data, mode in files:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = (0o100000 | mode) << 16  # keeps the launchers executable when unzipped on Mac/Linux
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    print(f"{target.relative_to(REPO)}: {len(files)} files, {target.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
