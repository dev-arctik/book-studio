# software/book_studio/__main__.py
# Entry point: `python -m book_studio` opens the window (the launchers and Desktop / Start-menu icons run exactly this).
# Started windowless (pythonw.exe on Windows) there is no console: output goes nowhere on purpose, and a failure to start
# is shown in a message box and saved to logs/startup.log instead of the app vanishing silently.

import os
import sys
import traceback

sys.dont_write_bytecode = True  # keep the program folder free of __pycache__

if sys.stdout is None or sys.stderr is None:  # pythonw.exe: anything written to the missing console would end the app
    sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _report_failure(details: str) -> None:
    """Saves the reason and tells the person — in a Qt message box if Qt works, else a plain Windows one."""
    log = None
    try:
        from . import paths

        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log = paths.LOGS_DIR / "startup.log"
        log.write_text(details, encoding="utf-8")
    except Exception:  # noqa: BLE001 — reporting must never fail itself
        pass
    text = ("Book Studio could not start.\n\nPlease send this message (or the file below) to Devansh.\n\n"
            f"{details.strip().splitlines()[-1]}" + (f"\n\nDetails: {log}" if log else ""))
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 — a message box needs an application
        QMessageBox.critical(None, "Book Studio", text)
    except Exception:  # noqa: BLE001
        if os.name == "nt":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, "Book Studio", 0x10)


try:
    from .ui import run

    code = run()
except SystemExit:
    raise
except BaseException:  # noqa: BLE001 — any failure to start must reach the person, not vanish
    _report_failure(traceback.format_exc())
    code = 1
sys.exit(code)
