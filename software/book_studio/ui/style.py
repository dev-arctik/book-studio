# software/book_studio/ui/style.py
# The window's look: the books' own brown accent and Gentium for book titles, on a calm light background,
# with large click targets for people who don't use computers much.

from PySide6.QtGui import QColor, QFontDatabase, QPalette

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
QPushButton#Alert {{ color: {BAD}; border: 1px solid {BAD}; font-weight: bold; }}
QPushButton#Alert:hover {{ background: #fbeceb; }}
QPushButton#Tool {{ border: none; padding: 10px 16px; font-size: 15px; }}
QPushButton#Tool:hover {{ background: {ACCENT_SOFT}; }}
QPushButton#Tool:disabled {{ color: #b5aca2; }}
QPushButton#Link {{ border: none; color: {ACCENT}; padding: 4px; text-decoration: underline; background: transparent; }}
QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{ background: white; border: 1px solid {LINE}; border-radius: 6px; padding: 6px; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QListWidget#Grid {{ background: {BG}; border: none; }}
#ListBody {{ background: {BG}; }}
#Row {{ background: white; border: 1px solid {LINE}; border-radius: 10px; }}
#Row:hover {{ border-color: #cdbfae; }}
#Row[current="true"] {{ background: {ACCENT_SOFT}; border: 2px solid {ACCENT}; }}
#RunCard {{ background: white; border: 1px solid {LINE}; border-radius: 12px; }}
QLabel#RunTitle {{ font-size: 17px; font-weight: bold; }}
#SelectBar {{ background: {BG}; }}
QListWidget {{ background: white; border: 1px solid {LINE}; border-radius: 6px; }}
QListWidget::item {{ padding: 5px 4px; }}
QListWidget#Grid::item {{ padding: 0; }}
QProgressBar {{ border: 1px solid {LINE}; border-radius: 6px; background: white; height: 14px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QSlider::groove:horizontal {{ height: 6px; background: {LINE}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 18px; margin: -7px 0; border-radius: 9px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid #a89a8a; border-radius: 4px; background: white; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url(CHECK_PNG); }}
QCheckBox::indicator:disabled {{ background: #f1ece5; border-color: #d6ccc0; }}
QCheckBox::indicator:checked:disabled {{ background: #c9b39a; border-color: #c9b39a; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 8px; margin-top: 14px; padding: 12px 10px 10px; background: {PANEL}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT}; font-weight: bold; }}
"""


def qss() -> str:
    """The style sheet, with the tick picture's path filled in (Qt style sheets need a file path, with forward slashes)."""
    return QSS.replace("CHECK_PNG", (paths.ASSETS_DIR / "check.png").as_posix())


def palette() -> QPalette:
    """Light colours whatever the system theme: in Mac/Windows dark mode Qt would otherwise draw black boxes and scrollbars
    inside this light design (a ticked checkbox looked the same as an empty one)."""
    p = QPalette()
    for role, colour in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, "#ffffff"), (QPalette.AlternateBase, BG),
                         (QPalette.Text, TEXT), (QPalette.Button, PANEL), (QPalette.ButtonText, TEXT), (QPalette.ToolTipBase, PANEL),
                         (QPalette.ToolTipText, TEXT), (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#ffffff"),
                         (QPalette.PlaceholderText, MUTED), (QPalette.Light, "#ffffff"), (QPalette.Midlight, LINE),
                         (QPalette.Mid, "#c9bfb2"), (QPalette.Dark, "#a89a8a"), (QPalette.Shadow, "#8a7f74")):
        p.setColor(role, QColor(colour))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#b5aca2"))
    return p


def load_fonts() -> str:
    """Registers the bundled Gentium (the books' typeface, with every diacritic); returns its family name for book titles."""
    family = "Gentium Book Plus"
    for f in paths.FONTS_DIR.glob("*.ttf"):
        ids = QFontDatabase.addApplicationFont(str(f))
        if ids >= 0:
            family = QFontDatabase.applicationFontFamilies(ids)[0]
    return family
