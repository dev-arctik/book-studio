# software/book_studio/ui/__init__.py
# The Qt window: run() sets up the data folder and the pipeline environment, then shows the main window.

import ctypes
import ctypes.util
import os
import sys


def run() -> int:
    from .. import paths

    paths.ensure_dirs()
    # Before anything imports the pipeline: point it at this computer's data folder (see manual/pipeline/local_env.py)
    os.environ.update(paths.pipeline_env())

    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow
    from .style import load_fonts, palette, qss

    _mac_app_name("Book Studio")
    app = QApplication(sys.argv)
    app.setApplicationName("Book Studio")
    # Dock / taskbar icon: started from the launcher the process is plain Python, which would show Python's rocket
    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon(str(paths.ASSETS_DIR / "icon.png")))
    app.setStyle("Fusion")  # the same look on Mac, Windows and Linux
    app.setPalette(palette())  # light colours even in dark mode
    app.setStyleSheet(qss())
    window = MainWindow(load_fonts())
    window.show()
    return app.exec()


def _mac_app_name(name: str) -> None:
    """Mac menu bar: show 'Book Studio' instead of 'python'. macOS takes the name from the running program's bundle info,
    which for the launcher is Python's — so it is replaced in memory before Qt builds the menu bar. Cosmetic: skipped on failure."""
    if sys.platform != "darwin":
        return
    try:
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.objc_getClass.restype = objc.sel_registerName.restype = objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send = objc.objc_msgSend

        def call(target, selector, *args):
            send.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_void_p] * len(args)
            return send(target, objc.sel_registerName(selector), *args)

        def nsstring(text):
            send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
            return send(objc.objc_getClass(b"NSString"), objc.sel_registerName(b"stringWithUTF8String:"), text.encode())

        info = call(call(objc.objc_getClass(b"NSBundle"), b"mainBundle"), b"infoDictionary")
        if info:
            call(info, b"setObject:forKey:", nsstring(name), nsstring("CFBundleName"))
    except Exception:  # noqa: BLE001
        pass
