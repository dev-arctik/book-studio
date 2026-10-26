# manual/pipeline/book_tidy.py
# Clean-ups for the digital route (pdf_to_book.py), switched on per book with "tidy": true in book_meta.json.
# They repair what a text layer cannot say: a verse broken in two blocks, a translation cut into pieces, a bold subheading glued to the paragraph below,
# bold capital openings, "—Name" lines under a quotation and rows of dots between scenes.
import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import re
from collections import Counter

from ocr_text import ends_sentence, join_lines, plain

SOURCE_RE = re.compile(r"^\[.*\]$")
BREAK_RE = re.compile(r"^[\s.·•*]{3,}$")
BOLD_ONLY_RE = re.compile(r"^<b>([^<]+)</b>$")
RUN_IN_RE = re.compile(r"^<b>([^<]{3,70})</b>\s+(\S.*)$", re.S)
OPENING_RE = re.compile(r"^((?:<b>[^<]*</b>\s*)+)(\S.*)$", re.S)
WORD_RE = re.compile(r"[A-Za-zĀāĪīŪūṚṛṢṣṆṇŚśḤḥṂṁṬṭḌḍÑñ’'-]+")


def italic(line: str) -> bool:
    return line.lstrip().startswith("<i>")


def verses_and_translations(blocks: list) -> list:
    """A verse is one centred block: its first line may sit in a block of its own, and the translation after its [source] line (or after the
    verse, when there is none) is one paragraph, not a row of pieces."""
    out, i = [], 0
    while i < len(blocks):
        b = blocks[i]
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if b["type"] == "quote" and nxt and nxt["type"] == "centred" and nxt["lines"] and italic(nxt["lines"][0]):
            b = {"type": "centred", "lines": [f"<i>{ln}</i>" for ln in b["lines"]] + nxt["lines"]}  # the verse was cut after its first line
            i += 1
        is_verse = b["type"] == "quote" or (b["type"] == "centred" and b["lines"] and italic(b["lines"][0]))
        if not is_verse:
            out.append(b)
            i += 1
            continue
        lines = b["lines"]
        cut = next((k for k, ln in enumerate(lines) if SOURCE_RE.match(plain(ln).strip())), None)
        rest = lines[cut + 1:] if cut is not None else []
        out.append({**b, "lines": lines[:cut + 1] if cut is not None else lines})
        text, style, i = join_lines("\n".join(plain(x) for x in rest)).strip(), "p", i + 1
        while i < len(blocks):
            nb = blocks[i]
            first = not text
            if nb["type"] == "blockquote" and (first or not ends_sentence(text)):
                style = "blockquote"
                text = (text + " " + nb["text"]).strip()
            elif nb["type"] == "centred" and nb["lines"] and not italic(nb["lines"][0]) and text and not ends_sentence(text):
                text += " " + join_lines("\n".join(nb["lines"]))
            elif nb["type"] == "p" and text and not ends_sentence(text) and nb["text"][:1].islower():
                text += " " + nb["text"]
            else:
                break
            i += 1
        if text:
            out.append({"type": style, "text": text})
    return out


def centred_run_on(blocks: list) -> list:
    """A centred block whose last lines are the start of a sentence that goes on in the paragraph below ("…came to Krsna Consciousness at the age of
    seventeen" / "when he came in contact…"): the title lines stay centred, the sentence is one paragraph again."""
    out = []
    for k, b in enumerate(blocks):
        nxt = blocks[k + 1] if k + 1 < len(blocks) else None
        if b["type"] == "centred" and nxt and nxt["type"] == "p" and nxt["text"][:1].islower() and not italic(b["lines"][0]):
            at = next((j for j, ln in enumerate(b["lines"]) if len(plain(ln)) > 30), None)
            if at:
                out.append({**b, "lines": b["lines"][:at]})
                blocks[k + 1] = {**nxt, "text": join_lines("\n".join(b["lines"][at:])) + " " + nxt["text"]}
                continue
        out.append(b)
    return out


def subheadings(blocks: list) -> list:
    """A short bold line is a subheading — alone, or glued to the front of the paragraph below it (it stood at a page bottom)."""
    out = []
    for b in blocks:
        text = b.get("text") or ""
        if b["type"] in ("p", "blockquote"):
            only = BOLD_ONLY_RE.match(text.strip())
            if only and len(only.group(1)) <= 70 and not only.group(1).rstrip().endswith((":", ",")):
                out.append({"type": "h", "text": only.group(1).strip()})
                continue
            run = RUN_IN_RE.match(text)
            if run and not run.group(1).rstrip().endswith((":", ",", ".", "!", "?")) and not mostly_capitals(run.group(1)):
                out += [{"type": "h", "text": run.group(1).strip()}, {"type": "p", "text": run.group(2)}]
                continue
        out.append(b)
    return out


def mostly_capitals(text: str) -> bool:
    letters = [c for c in plain(text) if c.isalpha()]
    return len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) >= 0.7


def signatures(blocks: list) -> list:
    """"—Name" on a line of its own under a quotation: right-aligned, as a signature."""
    out = []
    for b in blocks:
        text = plain(b.get("text") or "").strip()
        if b["type"] in ("p", "h", "blockquote") and text[:1] in "—–" and 1 < len(text) <= 60:
            out.append({"type": "sign", "text": text.lstrip("—– ").strip()})
        else:
            out.append(b)
    return out


def breaks(blocks: list) -> list:
    """Rows of dots or bullets between scenes are a centred ornament."""
    return [{"type": "break"} if b["type"] in ("p", "blockquote", "centred") and BREAK_RE.match(plain(b.get("text") or " ".join(b.get("lines") or [])).strip()) else b for b in blocks]


def glue_headings(blocks: list, phrases: list) -> list:
    """A heading that is really the end of the paragraph before it (the sentence ran over a page: "…and GIVE PEACE A CHANCE.")."""
    out = []
    for b in blocks:
        if b["type"] == "h" and plain(b["text"]).strip() in phrases and out and out[-1]["type"] == "p":
            out[-1] = {**out[-1], "text": out[-1]["text"] + " " + plain(b["text"]).strip()}
        else:
            out.append(b)
    return out


def proper_words(sections: list) -> dict:
    """Words the book writes with a capital in the middle of a sentence (Krsna, O’Hare), lower-cased → as printed."""
    cased, lower = Counter(), Counter()
    for sec in sections:
        for b in sec["blocks"]:
            if b["type"] != "p":
                continue
            words = WORD_RE.findall(plain(b["text"]))
            for k, w in enumerate(words):
                if w[0].isupper() and k and not words[k - 1].endswith(".") and not mostly_capitals(w):
                    cased[w] += 1
                elif w.islower():
                    lower[w] += 1
    return {w.lower(): w for w, n in cased.items() if n >= 3 and lower[w.lower()] <= 0.2 * n}


def sentence_case(text: str, proper: dict) -> str:
    words = text.split()
    for k, w in enumerate(words):
        core = "".join(WORD_RE.findall(w))
        if core == "I" or not core or core.isdigit():
            continue
        if core.lower() in proper:
            words[k] = w.replace(core, proper[core.lower()])
        else:
            words[k] = w.lower()
        if k == 0:
            words[k] = words[k][:1].upper() + words[k][1:]
    return " ".join(words)


def capital_openings(sections: list) -> None:
    """A paragraph that opens with bold capitals (MY QUEST FOR THE TRUTH OF LIFE HIT A PEAK IN 1972 WHEN …) is set as plain running text."""
    proper = proper_words(sections)
    for sec in sections:
        for b in sec["blocks"]:
            m = OPENING_RE.match(b.get("text") or "") if b["type"] in ("p", "blockquote") else None
            if m and mostly_capitals(m.group(1)):
                b["text"] = sentence_case(plain(m.group(1)).strip(), proper) + " " + m.group(2)


def tidy_sections(sections: list, meta: dict) -> None:
    for sec in sections:
        blocks = centred_run_on(sec["blocks"])
        blocks = verses_and_translations(blocks)
        blocks = subheadings(blocks)
        blocks = glue_headings(blocks, meta.get("glue_headings", []))
        blocks = signatures(blocks)
        sec["blocks"] = breaks(blocks)
    capital_openings(sections)
