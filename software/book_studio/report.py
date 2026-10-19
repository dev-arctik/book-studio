# software/book_studio/report.py
# The text a volunteer copies to send for help: one book's full report (Check book → Copy report: report.txt with its book map,
# plus the last run's log) and a run's summary of everything worth a look (Copy report on the run card). Titles, headings and
# messages only — the pipeline's report holds no page text beyond each chapter's first words.

import platform
import re
from datetime import datetime

from . import __version__, paths, store

PROGRESS_RE = re.compile(r"^\[\d+/\d+\] pages ")  # "[40/719] pages 37-40 | 24.5s/page | ~278 min left"
# Log lines that ask for a look at the scan, or say a page or the PDF's text couldn't be used
CHECK_RE = re.compile(r"check it against the scan|can't be read|reading its pages instead|blocked", re.I)
ERROR_RE = re.compile(r"^\w+(Error|Exception)\b")


def header() -> str:
    return f"Book Studio {__version__} · {platform.system()} {platform.release()} · {datetime.now():%Y-%m-%d %H:%M}"


def last_run_log(book_id: str) -> str:
    """The book's log from its last "===== <time> — making <book> =====" heading on — what's needed to say why it failed."""
    path = paths.LOGS_DIR / f"{book_id}.log"
    if not path.exists():
        return f"No log yet for {book_id}."
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.rfind("===== ")
    return (text[start:] if start >= 0 else text).strip()


def short_log(text: str) -> str:
    """The log without the hundreds of page-progress lines in between: the first and last are enough."""
    lines = text.splitlines()
    progress = [i for i, line in enumerate(lines) if PROGRESS_RE.match(line)]
    drop = set(progress[1:-1])
    out = [line for i, line in enumerate(lines) if i not in drop]
    if drop:
        out.insert(progress[0] + 1, f"   … {len(drop)} more page-progress lines …")
    return "\n".join(out)


def report_text(b: store.Book) -> str:
    path = paths.WORK_DIR / "output" / b.id / "2-assembled" / "report.txt"
    return path.read_text(encoding="utf-8", errors="replace").rstrip() if path.exists() else ""


def status(b: store.Book) -> str:
    if b.error:
        return f"needs attention — {b.error}"
    if b.built:
        return f"made {b.built.replace('T', ' ')}" + (f" — {b.look}" if b.look else "")
    return "not made yet"


def book_report(b: store.Book) -> str:
    """Everything about one book, to tune it from: its report (with the book map) and the last run's log."""
    return "\n".join([header(), f"Book: {b.title} ({b.id}) · {b.pages} pages · {b.kind or 'not read yet'}", f"Status: {status(b)}", "",
                      "--- report ---", report_text(b) or "(no report yet — the book didn't get as far as its chapters)", "",
                      "--- log of the last run ---", short_log(last_run_log(b.id))])


def things_to_check(b: store.Book) -> list[str]:
    """The lines of a book's report and log that ask for a look: chapters not found or found another way, flagged pages,
    pictures and copyright pages to compare with the scan, and the error if it failed."""
    out, missing = [], []
    for line in report_text(b).splitlines():
        s = line.strip()
        if "but it was not found in the book" in s:
            missing.append(s)
        elif (line.startswith(("Contents check", "Sections from the outline")) or s.startswith("!")
              or (line.startswith("Pages with no text") and not s.endswith("[]"))):
            out.append(s)
        elif line.startswith("Chapters found by") and "the book's contents page" != s.split(": ", 1)[-1]:
            out.append(s)
    # A contents that didn't match lists every entry: a few say enough, the book's own report has them all
    out += missing if len(missing) <= 5 else missing[:3] + [f"! … and {len(missing) - 3} more contents entries not found"]
    log = last_run_log(b.id).splitlines()
    out += [line.strip() for line in log if CHECK_RE.search(line)]
    if b.error:
        out += [line.strip() for line in log if ERROR_RE.match(line.strip())][-1:]
    return out


def run_report(books: list[store.Book]) -> str:
    """One text for a whole run: each book's status and what's worth a look. A book's full details: Check book → Copy report."""
    lines = [header(), f"{len(books)} book{'s' if len(books) != 1 else ''}", ""]
    for b in books:
        lines.append(f"■ {b.title} ({b.id}) · {b.pages} pages — {status(b)}")
        lines += [f"    {line}" for line in things_to_check(b)] or ["    nothing flagged"]
        lines.append("")
    lines.append("For one book's full details (its book map and log): ⋯ → Check book → Copy report.")
    return "\n".join(lines)
