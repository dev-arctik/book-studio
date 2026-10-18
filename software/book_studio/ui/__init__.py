# software/book_studio/ui/__init__.py
# The Qt window: run() sets up the data folder and the pipeline environment, then shows the main window.

import os
import sys


def run() -> int:
    from .. import paths

    paths.ensure_dirs()
    # Before anything imports the pipeline: point it at this computer's data folder (see manual/pipeline/local_env.py)
    os.environ.update(paths.pipeline_env())

    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow
    from .style import QSS, load_fonts

    app = QApplication(sys.argv)
    app.setApplicationName("Book Studio")
    app.setStyle("Fusion")  # the same look on Mac, Windows and Linux
    app.setStyleSheet(QSS)
    window = MainWindow(load_fonts())
    window.show()
    return app.exec()
