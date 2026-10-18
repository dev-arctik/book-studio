# manual/pipeline/power.py
# Keeps the computer awake while books are made (a laptop that sleeps stops reading pages for hours) and watches the battery,
# so reading pauses before a laptop runs flat and continues once it is plugged in. Used by run_book.py and Book Studio's worker.
# The screen may still turn off — only system sleep is held off, and only while the book is being made.

import os
import subprocess
import sys
import time
from contextlib import contextmanager

LOW_BATTERY = 15  # % on battery: below this, reading pauses between page batches
RESUME_BATTERY = 20  # % on battery at which it goes on by itself (or as soon as the charger is plugged in)


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
    return b is None or b[1] or b[0] >= RESUME_BATTERY


def wait_for_power(on_pause=lambda percent: None, on_resume=lambda: None, stop=lambda: False, poll: float = 5) -> bool:
    """Waits while a laptop is on battery below LOW_BATTERY, until it is plugged in or back at RESUME_BATTERY.
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
