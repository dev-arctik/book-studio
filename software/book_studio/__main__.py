# software/book_studio/__main__.py
# Entry point: `python -m book_studio` opens the window (the launchers and Desktop icon run exactly this).

import sys

sys.dont_write_bytecode = True  # keep the program folder free of __pycache__

from .ui import run  # noqa: E402

sys.exit(run())
