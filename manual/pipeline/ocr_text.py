# pipeline/ocr_text.py
# Shared helpers for turning Surya OCR output into clean text — used by both assemblers (assemble_verses.py, assemble_prose.py).
# Covers HTML clean-up, OCR look-alike letter fixes, line re-joining, paragraphs split by page breaks, title matching and back-cover removal.

import difflib
import html as htmllib
import json
import re
import unicodedata

import local_env

# Look-alike letters that never occur in IAST transliteration, so they are always OCR confusions (seen: "nîcair", "Nişkramati",
# "○ debauchee" for the vocative O, "VIṢŅU" with a cedilla N). Not ü: it is real in names (Müller, Krüger).
NON_IAST_FIXES = str.maketrans({"î": "ī", "â": "ā", "û": "ū", "Î": "Ī", "Â": "Ā", "Û": "Ū", "ş": "ṣ", "Ş": "Ṣ", "ţ": "ṭ", "Ţ": "Ṭ", "○": "O",
                                "ņ": "ṇ", "Ņ": "Ṇ"})
# Characters the book font lacks: decorative list bullets (♦ ► ▪ ➤ □ …) become the standard bullet •
BULLET_FIXES = str.maketrans({**{c: "•" for c in "♦►▪➤●■◆▸▶➢✓✔□⇒"}, "′": "'", "ˇ": ""})  # also: prime → apostrophe, stray caron speck removed
TERMINAL_PUNCT = tuple('.!?"”’\')')
WORD_RE = re.compile(r"\w+")  # \w covers diacritic letters (ā ṣ ṇ …) in Python 3
PICTURE_LABELS = {"Picture", "Figure"}


INLINE_TAGS = r"(?:i|b|sup)"  # emphasis and footnote markers survive; every other tag becomes plain text


def clean_inline(html: str) -> str:
    """Keep only <i>/<b>/<sup> and line breaks; list items and table rows end their line; everything else becomes plain text."""
    html = html.translate(NON_IAST_FIXES).translate(BULLET_FIXES)
    html = re.sub(r"<br\s*/?>\s*|</li>|</tr>|</p>\s*(?=<p)", "\n", html, flags=re.I)  # several <p> in one block = separate lines
    html = re.sub(rf"</?(?!{INLINE_TAGS}>)[a-z0-9]+[^>]*>", "", html, flags=re.I)
    html = re.sub(rf"<(/?)({INLINE_TAGS})\s[^>]*>", r"<\1\2>", html)
    text = htmllib.unescape(html)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def plain(text: str) -> str:
    """Text without inline tags; footnote markers are dropped entirely so titles and sentences compare cleanly."""
    return re.sub(r"</?[ib]>", "", re.sub(r"<sup>.*?</sup>", "", text)).strip()


def is_all_italic(text: str) -> bool:
    """Sanskrit verses are printed fully in italics — the whole block is one <i>…</i>."""
    return bool(re.fullmatch(r"<i>.*</i>", text.strip(), re.S)) and "</i>" not in text.strip()[3:-4]


def join_lines(text: str) -> str:
    """Undo the printed line wrapping in prose so it can reflow; a line ending in an em dash ("acaraṇam—") joins without a space."""
    return re.sub(r"(—)?\n", lambda m: "—" if m.group(1) else " ", text)


def ends_sentence(text: str) -> bool:
    return plain(text).endswith(TERMINAL_PUNCT)


def add_paragraph(paragraphs: list, text: str) -> None:
    """Append a paragraph; one cut by a page break doesn't end in sentence punctuation, so the next piece is glued onto it."""
    text = join_lines(text)
    if paragraphs and not ends_sentence(paragraphs[-1]):
        paragraphs[-1] = paragraphs[-1].rstrip("-") + ("" if paragraphs[-1].endswith("-") else " ") + text
    else:
        paragraphs.append(text)


def ocr_pages(book: str):
    """Yield (page number, blocks in reading order) for every OCR'd page of a book."""
    for path in sorted(local_env.stage_dir(book, "ocr").glob("page-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for b in data["blocks"]:
            b["image_bbox"] = data["image_bbox"]  # page size in the OCR render's pixels — needed to crop pictures later
        yield int(path.stem.split("-")[1]), sorted(data["blocks"], key=lambda b: b["reading_order"])


def ascii_key(title: str) -> str:
    """Comparison key for titles: plain ASCII letters/digits only, so diacritics, spacing and punctuation differences don't matter."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", ascii_title)


def best_match(title: str, candidates: list[str]) -> tuple[str, float]:
    scored = [(c, difflib.SequenceMatcher(None, title.lower(), c.lower()).ratio()) for c in candidates]
    return max(scored, key=lambda s: s[1], default=("", 0.0))


def drop_back_cover(blocks, last_content_page: int, content_pages: set):
    """The last pages are the back cover (blurb, publisher, ISBN, barcode) — not part of the book's text.
    That's the page with the ISBN plus any cover pages just before it that hold no book content."""
    # An ISBN on the copyright page near the front doesn't count — only one after the book's last content
    back = [b["page"] for b in blocks if re.search(r"\bISBN\b", plain(b["text"])) and b["page"] > last_content_page]
    if not back:
        return blocks
    start = min(back)
    while start - 1 > last_content_page and (start - 1) not in content_pages:
        start -= 1
    return [b for b in blocks if b["page"] < start]


def apply_text_fixes(blocks, fixes: list[list[str]]) -> list[str]:
    """Apply hand-checked [wrong, right] corrections from book_meta.json; report each so no change is silent.
    A fix should match exactly once — zero means the OCR text changed, more means its context is too short."""
    report = []
    for wrong, right in fixes:
        hits = 0
        for b in blocks:
            if wrong in b["text"]:
                hits += b["text"].count(wrong)
                b["text"] = b["text"].replace(wrong, right)
        flag = "" if hits == 1 else "  ! expected exactly 1 match"
        report.append(f"      fix: '{wrong}' → '{right}' ({hits} match{'es' if hits != 1 else ''}){flag}")
    return report


def blank_pages(blocks, first_page: int) -> list[int]:
    """Pages with no text at all — illustrations, or an OCR that failed and silently lost a page's content."""
    text_pages = {b["page"] for b in blocks}
    last_page = max(text_pages, default=first_page)
    return [n for n in range(first_page, last_page + 1) if n not in text_pages]
