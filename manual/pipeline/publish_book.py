# manual/pipeline/publish_book.py
# The last step, run only after a book has been checked against its scan: copies its PDF and EPUB drafts from the workspace
# into the pdf/ and epub/ folders of the batch folder the book came from (beside its original) as <book>_en.pdf and <book>_en.epub. Nothing unchecked ever lands there.
# Usage: poetry run python manual/pipeline/publish_book.py <path/to/book.pdf> --library <path/to/book-library>

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import shutil


def publish(book: str, batch=None) -> None:
    drafts = {"PDF": local_env.stage_dir(book, "clean-pdf") / f"{book}.pdf", "EPUB": local_env.stage_dir(book, "epub") / f"{book}.epub"}
    missing = [f"{kind} ({path})" for kind, path in drafts.items() if not local_env.win_long(path).is_file()]
    if missing:
        sys.exit(f"Not ready: no draft for {', '.join(missing)} — run run_book.py first")
    for path in drafts.values():
        target = local_env.final_path(f"{book}_en{path.suffix}", batch)
        shutil.copyfile(local_env.win_long(path), local_env.win_long(target))
        print(f"{target}  ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(local_env.USAGE)
    for path in map(local_env.book_path, sys.argv[1:]):
        publish(path.stem, path.parent)  # the finished files go into pdf/ and epub/ beside the original
