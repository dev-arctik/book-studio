# manual/pipeline/ocr_book.py
# Stage 1 of the scanned-book pipeline: OCRs every page of a PDF with Surya and saves one JSON per page under output/<book>/1-ocr/.
# Resumable — pages that already have a JSON are skipped, so an interrupted overnight run can simply be restarted.
# --fix re-reads single blocks the full-page OCR got wrong (crop of just that block, so nearby text can't bleed in).
# Usage: poetry run python manual/pipeline/ocr_book.py <path/to/book.pdf> --library <path/to/book-library> [first_page last_page]
#        poetry run python manual/pipeline/ocr_book.py <path/to/book.pdf> --library <path/to/book-library> --fix 169:4 261:4   (page:block, block = position in reading order)

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env  # noqa: F401  (must run before surya import to pin caches locally)

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

import pypdfium2 as pdfium

import power

from surya.inference import SuryaInferenceManager
from surya.recognition import RecognitionPredictor

RENDER_DPI = 192  # matches Surya's IMAGE_DPI_HIGHRES, the resolution its recognizer expects
CHUNK_SIZE = 4  # pages per OCR call: small enough that a crash loses little work
CROP_PADDING = 12  # px around a re-read block, so edge diacritics (dots below, macrons above) aren't clipped


def render_pages(pdf_path: Path, page_numbers: list[int]):
    """Render 1-indexed page numbers to PIL images."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    return [pdf[n - 1].render(scale=RENDER_DPI / 72).to_pil() for n in page_numbers]


@contextmanager
def ocr_predictor():
    manager = SuryaInferenceManager()
    try:
        yield RecognitionPredictor(manager)
    finally:
        # Stop the spawned llama-server so a multi-GB model doesn't stay loaded in RAM
        manager.stop()


def save_page(path: Path, data: dict) -> None:
    """All or nothing: written to page-NNN.json.tmp, then renamed — a power cut mid-write leaves no half-written page behind."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def page_done(path: Path) -> bool:
    """A saved page that opens cleanly; anything else (missing, empty, damaged by a crash) is read again."""
    try:
        return "blocks" in json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def ocr_all(pdf_path: Path, out_dir: Path, first: int, last: int, after_chunk=None):
    """after_chunk(pages) runs once each batch is saved — Book Studio uses it for progress, Pause and cool-down rests.
    Resumable: pages already saved are skipped, so after a crash or power cut at most the batch in progress is read again."""
    todo = [n for n in range(first, last + 1) if not page_done(out_dir / f"page-{n:03d}.json")]
    print(f"{pdf_path.name}: {last - first + 1} pages, {len(todo)} left to OCR", flush=True)
    if not todo:
        return
    start = time.time()
    with ocr_predictor() as predictor:
        for i in range(0, len(todo), CHUNK_SIZE):
            chunk = todo[i : i + CHUNK_SIZE]
            results = predictor(render_pages(pdf_path, chunk), full_page=True)
            for n, page in zip(chunk, results):
                save_page(out_dir / f"page-{n:03d}.json", page.model_dump())
            done = i + len(chunk)
            per_page = (time.time() - start) / done
            print(f"[{done}/{len(todo)}] pages {chunk[0]}-{chunk[-1]} | {per_page:.1f}s/page | ~{per_page * (len(todo) - done) / 60:.0f} min left", flush=True)
            if after_chunk:
                after_chunk(chunk)


def fix_blocks(pdf_path: Path, out_dir: Path, specs: list[str]):
    """Re-OCR individual blocks from a tight crop. The old text is kept as html_before_fix so every repair stays traceable."""
    targets = []
    for spec in specs:
        page_no, block_no = (int(x) for x in spec.split(":"))
        path = out_dir / f"page-{page_no:03d}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        block = sorted(data["blocks"], key=lambda b: b["reading_order"])[block_no]
        img = render_pages(pdf_path, [page_no])[0]
        scale = img.width / data["image_bbox"][2]
        x0, y0, x1, y1 = (v * scale for v in block["bbox"])
        crop = img.crop((max(0, x0 - CROP_PADDING), max(0, y0 - CROP_PADDING), min(img.width, x1 + CROP_PADDING), min(img.height, y1 + CROP_PADDING)))
        targets.append((path, data, block, crop))

    with ocr_predictor() as predictor:
        results = predictor([crop for *_, crop in targets], full_page=True)

    for (path, data, block, _), result in zip(targets, results):
        new_html = "\n".join(b.html for b in sorted(result.blocks, key=lambda b: b.reading_order) if b.html)
        block.setdefault("html_before_fix", block["html"])
        block["html"] = new_html
        save_page(path, data)
        strip = lambda h: re.sub(r"<[^>]+>", " ", h).split()
        print(f"{path.name}:\n  before: {' '.join(strip(block['html_before_fix']))[:160]}\n  after:  {' '.join(strip(new_html))[:160]}")


def main():
    pdf_path = local_env.book_path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit(local_env.USAGE)
    out_dir = local_env.stage_dir(pdf_path.stem, "ocr")
    if "--fix" in sys.argv:
        fix_blocks(pdf_path, out_dir, sys.argv[sys.argv.index("--fix") + 1 :])
        return
    total = len(pdfium.PdfDocument(str(pdf_path)))
    first, last = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1, total)
    low = lambda pct: print(f"Battery at {pct}% — paused until the charger is plugged in (or {power.RESUME_BATTERY}%)…", flush=True)  # noqa: E731
    with power.keep_awake():
        ocr_all(pdf_path, out_dir, first, last, after_chunk=lambda _: power.wait_for_power(low, lambda: print("Power back — continuing", flush=True)))


if __name__ == "__main__":
    main()
