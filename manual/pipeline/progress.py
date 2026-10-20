# manual/pipeline/progress.py
# A read-only progress view of the whole batch: for every book its stage (read, assembled, drafts built, published), the pages read
# with speed and time left while the OCR runs, and whether the page reader is working. It changes nothing; --watch refreshes it (every 120 s unless a number of seconds follows).
# Usage: poetry run python manual/pipeline/progress.py --library <path/to/book-library> --inputs <folder with the scans> [--watch [seconds]]

import sys; sys.dont_write_bytecode = True  # keep pipeline/ free of __pycache__ clutter
import local_env

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium

import power

RECENT = 12  # newest page files used to estimate the reading speed
STALE_MIN = 10  # minutes without a new page before reading counts as stopped
WATCH_SECONDS = 120  # --watch refreshes this often unless told otherwise


def option(flag: str) -> str | None:
    """The value after a command-line flag, or None."""
    if flag in sys.argv:
        i = sys.argv.index(flag)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    return None


def reader_running() -> bool:
    """True while a llama-server (the page reader) process exists."""
    try:
        import psutil

        return any("llama-server" in (p.info["name"] or "").lower() for p in psutil.process_iter(["name"]))
    except Exception:  # noqa: BLE001 — no process list is never a reason to stop
        return False


def clock(seconds: float) -> str:
    """Seconds as m:ss, or h:mm:ss from an hour up."""
    s = max(0, int(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def cooldown_mode(working: bool) -> tuple[str, float | None]:
    """(text for the header, seconds of rest left or None). WORKING with the time to the next rest, RESTING with a countdown, or idle.
    The OCR writes .reading-state in the workspace; the rest after a finished book is also read from .last-ocr-finished."""
    now, state = time.time(), None
    state_file = local_env.WORKSPACE_DIR / ".reading-state"
    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = None
    at = lambda t: time.strftime("%H:%M", time.localtime(t))  # noqa: E731
    if state and state.get("mode") == "resting" and state["until"] > now:
        left = state["until"] - now
        return f"RESTING — {clock(left)} left, reading continues at {at(state['until'])} ({state.get('why', 'cool-down')})", left
    if state and state.get("mode") == "working" and working:
        return f"WORKING — next rest in {clock(state['next_rest'] - now)} (at {at(state['next_rest'])})", None
    marker = local_env.WORKSPACE_DIR / ".last-ocr-finished"
    if marker.is_file() and not working:  # no OCR is running: the cool-down after the last finished book may still be due
        left = power.BETWEEN_MINUTES * 60 - (now - marker.stat().st_mtime)
        if left > 0:
            return f"RESTING — {clock(left)} left, the next book is read after it (cool-down after the last book)", left
    if working:
        return "WORKING (this run started before the rest rule: no rest timer)", None
    return "idle", None


def heat(celsius: float) -> str:
    return "HOT" if celsius >= 85 else "warm" if celsius >= 75 else "ok"


def cpu_temperature() -> float | None:
    """Windows' ACPI thermal zone in °C — the nearest thing to a CPU temperature a laptop gives without admin rights or extra tools."""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", r"(Get-Counter '\Thermal Zone Information(*)\Temperature').CounterSamples | ForEach-Object { $_.CookedValue }"],
                             capture_output=True, text=True, timeout=15).stdout.split()
        kelvin = [float(x) for x in out if x.replace(".", "", 1).isdigit()]
        return max(kelvin) - 273.15 if kelvin else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def gpu_status() -> dict | None:
    """NVIDIA GPU temperature, load, power and whether it is slowing itself down (nvidia-smi); None without an NVIDIA GPU."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,power.draw,clocks_throttle_reasons.active",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.strip().split(",")
        temp, load, watts, reasons = (x.strip() for x in out[:4])
        return {"temp": float(temp), "load": float(load), "watts": float(watts), "thermal": bool(int(reasons, 16) & (0x08 | 0x20 | 0x40))}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def temperatures() -> str:
    """One line: CPU and GPU temperature with a word for how hot, GPU load and power, and a warning when the GPU is throttling."""
    cpu, gpu = cpu_temperature(), gpu_status()
    parts = [f"CPU {cpu:.0f} °C ({heat(cpu)})" if cpu is not None else "CPU n/a"]
    if gpu:
        parts.append(f"GPU {gpu['temp']:.0f} °C ({heat(gpu['temp'])}), {gpu['load']:.0f}% load, {gpu['watts']:.0f} W"
                     + (" — GPU IS SLOWING ITSELF DOWN (too hot)" if gpu["thermal"] else ""))
    else:
        parts.append("GPU n/a")
    return "   |   ".join(parts)


def pdf_pages(path: Path) -> int:
    doc = pdfium.PdfDocument(str(path))
    try:
        return len(doc)
    finally:
        doc.close()


def final_exists(key: str) -> bool:
    return all((local_env.FINAL_DIR / local_env.FINAL_KINDS[ext] / f"{key}_en{ext}").is_file() for ext in (".pdf", ".epub"))


def speed(pages: list[Path]) -> float | None:
    """Seconds per page from the newest page files' save times."""
    newest = sorted(pages, key=lambda p: p.stat().st_mtime)[-RECENT:]
    if len(newest) < 3:
        return None
    span = newest[-1].stat().st_mtime - newest[0].stat().st_mtime
    return span / (len(newest) - 1) if span > 0 else None


def minutes(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def book_line(key: str, total: int | None, working: bool, rest_left: float | None = None) -> tuple[str, int]:
    """(status text, pages read) for one book."""
    ws = local_env.WORKSPACE_DIR / key
    ocr = ws / local_env.STAGES["ocr"]
    pages = list(ocr.glob("page-*.json")) if ocr.is_dir() else []
    done = len(pages)
    has = lambda stage, name: (ws / local_env.STAGES[stage] / name).is_file()  # noqa: E731
    if final_exists(key):
        return "DONE — published in pdf/ and epub/", total or done
    if has("clean-pdf", f"{key}.pdf") and has("epub", f"{key}.epub"):
        return "built — waiting for its check, then publish", total or done
    if has("assembled", "book.json"):
        return "assembled — typesetting / fixing the chapters", total or done
    if total and done >= total:
        return "all pages read — assemble next", done
    if done:
        last = max(p.stat().st_mtime for p in pages)
        ago = (time.time() - last) / 60
        rate = speed(pages)
        left = f", about {minutes((total - done) * rate)} left" if rate and total else ""
        state = (f"resting, {clock(rest_left)} left" if rest_left else
                 f"{rate:.0f} s/page{left}" if working and ago < STALE_MIN and rate else f"stopped — last page saved {minutes(ago * 60)} ago")
        return f"reading {done}/{total or '?'} ({100 * done // total if total else 0}%) — {state}", done
    return "queued", 0


def render() -> str:
    meta = json.loads(local_env.META_FILE.read_text(encoding="utf-8")) if local_env.META_FILE.is_file() else {}
    inputs = Path(option("--inputs")).expanduser().resolve() if option("--inputs") else None
    scans = {p.stem: p for p in sorted(inputs.glob("*.pdf"))} if inputs and inputs.is_dir() else {}
    totals = {key: pdf_pages(path) for key, path in scans.items()}
    keys = sorted(set(meta) | set(scans), key=lambda k: (totals.get(k) is None, totals.get(k) or 0, k))  # smallest first
    working = reader_running()
    mode, rest_left = cooldown_mode(working)
    battery = power.battery()
    power_text = "no battery info" if battery is None else f"{battery[0]}% {'plugged in' if battery[1] else 'ON BATTERY'}"
    rows, read, all_pages, published = [], 0, 0, 0
    for n, key in enumerate(keys, 1):
        status, got = book_line(key, totals.get(key), working, rest_left)
        published += status.startswith("DONE")
        read += got
        all_pages += totals.get(key) or 0
        rows.append(f"{n:>2}  {key[:44]:<44} {totals.get(key, '?'):>4}  {status}")
    bar = "█" * (20 * published // max(len(keys), 1)) + "░" * (20 - 20 * published // max(len(keys), 1))
    head = [f"Book progress — {datetime.now():%Y-%m-%d %H:%M:%S}   |   power: {power_text}",
            f"MODE: {mode}",
            f"TEMPS: {temperatures()}",
            f"Published {published} of {len(keys)} books  [{bar}]   pages covered {read} of {all_pages}", "",
            f"{'#':>2}  {'book':<44} {'pages':>4}  status", "-" * 110]
    return "\n".join(head + rows)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # book names carry diacritics; the Windows console is not UTF-8 by default
    watch = option("--watch")
    if watch is None:
        print(render())
        return
    wait = int(watch) if watch.isdigit() else WATCH_SECONDS
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print(render())
            print(f"\n(refreshes every {wait} s — Ctrl+C to leave)")
            time.sleep(wait)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
