# software/book_studio/ui/style.py
# The window's look: the books' own brown accent and Gentium for book titles, on a calm light background,
# with large click targets for people who don't use computers much.

from PySide6.QtGui import QFontDatabase

from .. import paths

ACCENT = "#7a4a12"
ACCENT_SOFT = "#f3e9dc"
TEXT = "#2b2622"
MUTED = "#6b6158"
BG = "#faf7f2"
PANEL = "#ffffff"
LINE = "#e4dbcf"
OK = "#2f7d4f"
WARN = "#b26a00"
BAD = "#b3261e"

QSS = f"""
QWidget {{ color: {TEXT}; font-size: 14px; }}
QMainWindow, QDialog {{ background: {BG}; }}
#Toolbar {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
#Panel {{ background: {PANEL}; border-left: 1px solid {LINE}; }}
#StatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; }}
QLabel#H1 {{ font-size: 20px; color: {ACCENT}; font-style: italic; }}
QLabel#Muted, QLabel#Hint {{ color: {MUTED}; }}
QLabel#Hint {{ font-size: 12px; }}
QPushButton {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 8px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #b5aca2; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-weight: bold; }}
QPushButton#Primary:hover {{ background: #8d5718; }}
QPushButton#Primary:disabled {{ background: #c9b39a; }}
QPushButton#Tool {{ border: none; padding: 10px 16px; font-size: 15px; }}
QPushButton#Tool:hover {{ background: {ACCENT_SOFT}; }}
QPushButton#Tool:disabled {{ color: #b5aca2; }}
QPushButton#Link {{ border: none; color: {ACCENT}; padding: 4px; text-decoration: underline; background: transparent; }}
QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{ background: white; border: 1px solid {LINE}; border-radius: 6px; padding: 6px; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QListWidget#Grid {{ background: {BG}; border: none; }}
QProgressBar {{ border: 1px solid {LINE}; border-radius: 6px; background: white; height: 14px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QSlider::groove:horizontal {{ height: 6px; background: {LINE}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 18px; margin: -7px 0; border-radius: 9px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 8px; margin-top: 14px; padding: 12px 10px 10px; background: {PANEL}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT}; font-weight: bold; }}
"""


def load_fonts() -> str:
    """Registers the bundled Gentium (the books' typeface, with every diacritic); returns its family name for book titles."""
    family = "Gentium Book Plus"
    for f in paths.FONTS_DIR.glob("*.ttf"):
        ids = QFontDatabase.addApplicationFont(str(f))
        if ids >= 0:
            family = QFontDatabase.applicationFontFamilies(ids)[0]
    return family
