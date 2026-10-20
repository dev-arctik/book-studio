# manual/pipeline/power.py
# Keeps the computer awake while books are made (a laptop that sleeps stops reading pages for hours) and watches the battery,
# so reading pauses before a laptop runs flat and continues once it is plugged in. Used by run_book.py and Book Studio's worker.
# The screen may still turn off — only system sleep is held off, and only while the book is being made.

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager

LOW_BATTERY = 50  # % on battery: below this, reading pauses between page batches (raised from 15 on 2026-10-20: leaves room to plug in)
# Cool-down rests, so a laptop reading pages for hours does not run hot (the same idea as Book Studio's work/rest settings)
WORK_MINUTES = 60  # reading time before a rest
REST_MINUTES = 15  # the rest after every WORK_MINUTES of reading
BETWEEN_MINUTES = 30  # the rest after every finished book, before the next one is read


def battery() -> tuple[int, bool] | None:
    """(percent, plugged in) — None on a desktop without a battery, or when the system won't say."""
    try:
        import psutil

        b = psutil.sensors_battery()
    except Exception:  # noqa: BLE001 — no battery information is never a reason to stop
        return None
    return None if b is None else (int(b.percent), bool(b.power_plugged))


def battery_low() -> bool:
    b = battery()
    return b is not None and not b[1] and b[0] < LOW_BATTERY


def power_back() -> bool:
    b = battery()
    return b is None or b[1]  # only the charger resumes reading: a battery can't charge itself back above the limit


def wait_for_power(on_pause=lambda percent: None, on_resume=lambda: None, stop=lambda: False, poll: float = 5) -> bool:
    """Waits while a laptop is on battery below LOW_BATTERY, until the charger is plugged in.
    Returns False if stop() asked to end the wait instead."""
    if not battery_low():
        return True
    on_pause(battery()[0])
    while not power_back():
        if stop():
            return False
        time.sleep(poll)
    on_resume()
    return True


def set_state(state_file, **fields) -> None:
    """Writes what the OCR is doing now (mode working/resting, when the rest ends or the next one is due) for progress.py to show."""
    if state_file:
        state_file.write_text(json.dumps({**fields, "saved": time.time()}), encoding="utf-8")


def work_state(state_file) -> None:
    """Reading goes on: the next rest is due in WORK_MINUTES."""
    set_state(state_file, mode="working", next_rest=time.time() + WORK_MINUTES * 60)


def rest(minutes: float, why: str, state_file=None) -> None:
    """Waits (in short steps, so Ctrl+C acts at once) and says when reading goes on."""
    resume = time.time() + minutes * 60
    set_state(state_file, mode="resting", until=resume, why=why)
    print(f"[{time.strftime('%H:%M:%S')}] Resting {minutes:g} min ({why}) — reading continues at {time.strftime('%H:%M', time.localtime(resume))}", flush=True)
    while time.time() < resume:
        time.sleep(min(5, max(0.01, resume - time.time())))
    print(f"[{time.strftime('%H:%M:%S')}] Rest over — reading continues", flush=True)
    work_state(state_file)


def rest_between_books(marker, state_file=None) -> None:
    """If the last book's reading finished less than BETWEEN_MINUTES ago (the marker file's time), waits out the rest."""
    if os.environ.get("BOOK_NO_COOLDOWN") or not marker.exists():
        return
    left = BETWEEN_MINUTES * 60 - (time.time() - marker.stat().st_mtime)
    if left > 0:
        rest(left / 60, "cool-down after the last book", state_file)


def rest_if_due(work_start: float, more_to_read: bool, state_file=None) -> float:
    """After WORK_MINUTES of reading, rests REST_MINUTES (not when nothing is left to read). Returns the new start of the work time."""
    if os.environ.get("BOOK_NO_COOLDOWN") or not more_to_read or time.time() - work_start < WORK_MINUTES * 60:
        return work_start
    rest(REST_MINUTES, f"{WORK_MINUTES} min of reading", state_file)
    return time.time()


@contextmanager
def keep_awake():
    """Holds off system sleep for as long as the block runs, with each system's own mechanism; carries on if there is none."""
    helper = None
    windows = os.name == "nt"
    try:
        if sys.platform == "darwin":
            # -i: no idle sleep; -w: ends by itself when this process ends, even after a crash
            helper = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        elif windows:
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        else:
            helper = subprocess.Popen(["systemd-inhibit", "--what=idle:sleep", "--who=Book Studio", "--why=Making books",
                                       "--mode=block", "sleep", "infinity"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, AttributeError):
        helper = None
    try:
        yield
    finally:
        if helper is not None:
            helper.terminate()
        if windows:
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # back to normal
