"""
Visual design system for TALOS.

Everything the interface needs to look modern lives here:

* :data:`PALETTES`   - colour tokens for three UI themes (two dark, one light).
* :func:`style_sheet`- the complete Qt stylesheet built from those tokens.
* :func:`icon`       - crisply recolourable SVG icons (no external files, so the
                       app works completely offline and in sandboxed previews).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QApplication

# --------------------------------------------------------------------------
# colour tokens
# --------------------------------------------------------------------------

PALETTES: Dict[str, Dict[str, str]] = {
    "midnight": {
        "window":    "#0e1015",
        "surface":   "#161922",
        "raised":    "#1d212c",
        "sunken":    "#0a0c11",
        "border":    "#2a3040",
        "borderStrong": "#3a4356",
        "text":      "#e8ebf2",
        "textDim":   "#98a1b5",
        "textFaint": "#626b7d",
        "accent":    "#f0b429",
        "accentText": "#1a1305",
        "accent2":   "#4cc2ff",
        "good":      "#4ade80",
        "bad":       "#f87171",
        "warn":      "#fbbf24",
        "selection": "#2b3a55",
        "light":     "#f2ede1",
        "dark":      "#8a6a45",
    },
    "slate": {
        "window":    "#11141a",
        "surface":   "#1a1e26",
        "raised":    "#222834",
        "sunken":    "#0b0d11",
        "border":    "#2c3441",
        "borderStrong": "#3d4757",
        "text":      "#e6eaf0",
        "textDim":   "#9aa4b6",
        "textFaint": "#6a7488",
        "accent":    "#7c8cff",
        "accentText": "#0b0d1a",
        "accent2":   "#43d9ad",
        "good":      "#43d9ad",
        "bad":       "#ff6b81",
        "warn":      "#ffc857",
        "selection": "#313b57",
        "light":     "#eceff4",
        "dark":      "#6b7789",
    },
    "parchment": {
        "window":    "#efe9dc",
        "surface":   "#f8f4ea",
        "raised":    "#ffffff",
        "sunken":    "#e4dccb",
        "border":    "#d3c8b2",
        "borderStrong": "#b8ab93",
        "text":      "#2a2620",
        "textDim":   "#6a6255",
        "textFaint": "#9a9081",
        "accent":    "#b4690e",
        "accentText": "#fff8ec",
        "accent2":   "#2f6d8f",
        "good":      "#2f8f4e",
        "bad":       "#c0392b",
        "warn":      "#c98a00",
        "selection": "#d9c9a3",
        "light":     "#f6f1e4",
        "dark":      "#9c7c4f",
    },
}

PALETTE_NAMES = list(PALETTES)

# Board themes are separate from UI themes; keep the mapping small and sane.
BOARD_THEME_FOR_UI = {"midnight": "midnight", "slate": "slate", "parchment": "wood"}


def tokens(name: str = "midnight") -> Dict[str, str]:
    return PALETTES.get(name, PALETTES["midnight"])


# --------------------------------------------------------------------------
# stylesheet
# --------------------------------------------------------------------------

_QSS_TEMPLATE = """
/* ---------------------------------------------------------------- base */
QWidget {{
    color: {text};
    font-family: "Inter", "Segoe UI", "Noto Sans", "Helvetica Neue", sans-serif;
    font-size: 13px;
    selection-background-color: {selection};
    selection-color: {text};
}}
QMainWindow, QDialog {{
    background: {window};
}}
QMainWindow::separator {{
    background: {border};
    width: 1px;
}}
QSplitter::handle {{
    background: {border};
    width: 1px;
    height: 1px;
}}

/* --------------------------------------------------------------- menus */
QMenuBar {{
    background: {surface};
    border-bottom: 1px solid {border};
    padding: 2px 4px;
}}
QMenuBar::item {{ background: transparent; padding: 6px 12px; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {raised}; }}
QMenu {{
    background: {surface};
    border: 1px solid {borderStrong};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 28px;
    border-radius: 6px;
    margin: 1px 2px;
}}
QMenu::item:selected {{ background: {selection}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 5px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 8px; }}

/* ------------------------------------------------------------- toolbar */
QToolBar {{
    background: {surface};
    border: none;
    border-bottom: 1px solid {border};
    spacing: 3px;
    padding: 5px 8px;
}}
QToolBar QToolButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
    margin: 0 1px;
    color: {textDim};
}}
QToolBar QToolButton:hover {{ background: {raised}; color: {text}; }}
QToolBar QToolButton:pressed {{ background: {selection}; }}
QToolBar QToolButton:checked {{
    background: {selection};
    color: {accent};
}}
QToolBar QToolButton[toolButtonStyle="2"] {{
    /* text beside icon */
    padding-right: 12px;
}}
QToolBar::separator {{ background: {border}; width: 1px; margin: 6px 6px; }}

/* -------------------------------------------------------------- panels */
QFrame#card, QFrame[card="true"] {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 10px;
}}
QGroupBox {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    top: 0px;
    padding: 0 6px;
    color: {textDim};
    font-weight: 600;
    font-size: 11px;
    letter-spacing: .6px;
}}
QStatusBar {{
    background: {surface};
    border-top: 1px solid {border};
    color: {textDim};
}}
QStatusBar QLabel {{ color: {textDim}; }}

/* --------------------------------------------------------------- tabs */
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 10px;
    background: {surface};
    top: -1px;
}}
QTabBar {{
    qproperty-drawBase: 0;
    border: none;
}}
QTabBar::tab {{
    background: transparent;
    color: {textFaint};
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
    font-size: 12px;
}}
QTabBar::tab:hover {{ color: {text}; background: {raised}; }}
QTabBar::tab:selected {{
    color: {accent};
    background: {surface};
}}
QTabBar::tab:!selected {{ margin-top: 2px; }}

/* ------------------------------------------------------------- buttons */
QPushButton, QToolButton {{
    background: {raised};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 7px 14px;
    color: {text};
}}
QPushButton:hover {{ background: {borderStrong}; border-color: {borderStrong}; }}
QPushButton:pressed {{ background: {selection}; }}
QPushButton:disabled {{ color: {textFaint}; background: {surface}; }}
QPushButton[accent="true"], QPushButton#accent {{
    background: {accent};
    color: {accentText};
    border: none;
    font-weight: 600;
}}
QPushButton[accent="true"]:hover, QPushButton#accent:hover {{
    background: {accent2};
}}
QPushButton[danger="true"] {{
    background: transparent;
    color: {bad};
    border: 1px solid {bad};
}}
QPushButton[danger="true"]:hover {{ background: {bad}; color: {window}; }}

/* -------------------------------------------------------------- inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {sunken};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 6px 9px;
    color: {text};
    selection-background-color: {selection};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {accent};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {surface};
    border: 1px solid {borderStrong};
    border-radius: 8px;
    selection-background-color: {selection};
}}
QCheckBox, QRadioButton {{ spacing: 8px; color: {text}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {borderStrong};
    border-radius: 5px;
    background: {sunken};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}
QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 14px; margin: -5px 0; border-radius: 7px;
    background: {accent};
}}

/* --------------------------------------------------------------- views */
QTableWidget, QListWidget, QTreeWidget {{
    background: {sunken};
    alternate-background-color: {surface};
    border: 1px solid {border};
    border-radius: 8px;
    gridline-color: {border};
    outline: none;
}}
QTableWidget::item, QListWidget::item, QTreeWidget::item {{ padding: 4px 6px; }}
QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {selection};
}}
QHeaderView::section {{
    background: {surface};
    color: {textDim};
    border: none;
    border-right: 1px solid {border};
    border-bottom: 1px solid {border};
    padding: 6px 8px;
    font-weight: 600;
    font-size: 11px;
}}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {borderStrong}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {textFaint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {borderStrong}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* --------------------------------------------------------- misc pieces */
QProgressBar {{
    background: {sunken};
    border: 1px solid {border};
    border-radius: 7px;
    height: 14px;
    text-align: center;
    color: {textDim};
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 6px; }}
QLabel#dim {{ color: {textDim}; }}
QLabel#title {{
    font-size: 15px; font-weight: 700; color: {text};
}}
QLabel#accent {{ color: {accent}; font-weight: 700; }}
QLabel#bad {{ color: {bad}; }}
QLabel#good {{ color: {good}; }}
QToolTip {{
    background: {raised};
    color: {text};
    border: 1px solid {borderStrong};
    border-radius: 6px;
    padding: 5px 8px;
}}
QDialogButtonBox QPushButton {{ min-width: 84px; }}
"""


def style_sheet(name: str = "midnight") -> str:
    """Return the full application stylesheet for *name*."""
    return _QSS_TEMPLATE.format(**tokens(name))


def apply(name: str = "midnight") -> None:
    """Install the stylesheet on the running :class:`QApplication`."""
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(style_sheet(name))


# --------------------------------------------------------------------------
# icons
# --------------------------------------------------------------------------

#: Stroke-style glyphs on a 24x24 grid.  Keep the drawing simple so the icons
#: stay readable at 16px as well as 48px.
_ICONS: Dict[str, str] = {
    "play":     "M9 4a2.4 2.4 0 1 1 0 4.8A2.4 2.4 0 0 1 9 4zM6.5 10.2h5l-.8 2.6H7.3zM4 20h10l-1.4-4.2H5.4z",
    "new":      "M12 5v14M5 12h14",
    "undo":     "M9.5 14.5 4 9l5.5-5.5M4 9h10.5a5.5 5.5 0 0 1 0 11h-4",
    "redo":     "M14.5 14.5 20 9l-5.5-5.5M20 9H9.5a5.5 5.5 0 0 0 0 11h4",
    "hint":     "M9.5 18.5h5M10.5 21.5h3M12 2.5a6.5 6.5 0 0 0-3.8 11.8v1.7h7.6v-1.7A6.5 6.5 0 0 0 12 2.5z",
    "flip":     "M3.5 8.5h13a5 5 0 0 1 0 10h-3M3.5 8.5l4-4M3.5 8.5l4 4"
                "M20.5 15.5h-13a5 5 0 0 1 0-10h3M20.5 15.5l-4 4M20.5 15.5l-4-4",
    "resign":   "M5.5 21V3.5M5.5 4h12l-2.4 4.4L17.5 13h-12",
    "save":     "M5 3.5h11l3 3v14H5zM9 3.5v6h6v-6M8.5 20.5V14h7v6.5",
    "analyse":  "M3.5 3.5v17h17M7 15.5l4-5 3 2.8 5-7",
    "battle":   "M3 3 13 13M13 13 17 17M12 16 16 12M21 3 11 13M11 13 8 16M9 11 13 15",
    "train":    "M4 9.5v5M8 7v10M16 7v10M20 9.5v5M8 12h8",
    "database": "M12 6.5c4.2 0 7.5-1.3 7.5-3S16.2.5 12 .5 4.5 1.8 4.5 3.5s3.3 3 7.5 3z"
                "M4.5 3.5v17c0 1.7 3.3 3 7.5 3s7.5-1.3 7.5-3v-17"
                "M4.5 12c0 1.7 3.3 3 7.5 3s7.5-1.3 7.5-3",
    "explorer": "M12 2.8a9.2 9.2 0 1 0 0 18.4 9.2 9.2 0 0 0 0-18.4zM15.6 8.4 13 13l-4.6 2.6L10.6 11z",
    "anarchy":  "M12 2.6a9.4 9.4 0 1 0 0 18.8 9.4 9.4 0 0 0 0-18.8zM7.2 17.2 12 6.8l4.8 10.4M9.4 13.6h5.2",
    "anarchess":"M3.5 3.5h7.2v7.2H3.5zM13.3 3.5h7.2v7.2h-7.2zM3.5 13.3h7.2v7.2H3.5zM13.3 13.3h7.2v7.2h-7.2z",
    "engine":   "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
    "settings": "M4 8h16M4 16h16",
    "sound":    "M4 9.5v5h3.6L13 18.5v-13L7.6 9.5H4zM16 9a4.5 4.5 0 0 1 0 6M18.6 6.4a8 8 0 0 1 0 11.2",
    "mute":     "M4 9.5v5h3.6L13 18.5v-13L7.6 9.5H4zM16.5 9.5l5 5M21.5 9.5l-5 5",
    "open":     "M3.5 7.5A2 2 0 0 1 5.5 5.5h3.6l2 2.5h7.4a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z",
    "clock":    "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5V12l3.5 2.2",
    "target":   "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.6a4.4 4.4 0 1 0 0 8.8 4.4 4.4 0 0 0 0-8.8zM12 11.4a.6.6 0 1 0 0 1.2.6.6 0 0 0 0-1.2z",
    "book":     "M4 4.5h6a2.5 2.5 0 0 1 2 2v13a2 2 0 0 0-2-2H4z"
                "M20 4.5h-6a2.5 2.5 0 0 0-2 2v13a2 2 0 0 1 2-2h6z",
    "chart":    "M4 20V10M10 20V4M16 20v-7M22 20H2",
    "spark":    "M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8",
    "plus":     "M12 5v14M5 12h14",
    "minus":    "M5 12h14",
    "close":    "M6 6l12 12M18 6 6 18",
    "check":    "M4.5 12.5 9.5 17.5 19.5 6.5",
    "dice":     "M4.5 4.5h15v15h-15zM9 9h.01M15 9h.01M12 12h.01M9 15h.01M15 15h.01",
}


def svg(name: str, colour: str = "#e8ebf2", size: int = 24,
        width: float = 1.8) -> bytes:
    """Render one of the built-in glyphs to an SVG document (bytes)."""
    d = _ICONS.get(name, _ICONS["spark"])
    filled = name in ("play", "anarchy", "target", "dice")
    body = (f'<path d="{d}" fill="{colour}" stroke="none"/>'
            if filled else
            f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')
    if name == "settings":
        body += (f'<circle cx="9" cy="8" r="2.6" fill="{colour}"/>'
                 f'<circle cx="16" cy="16" r="2.6" fill="{colour}"/>')
    if name == "dice":
        body = body.replace('fill="none"', 'fill="none"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 24 24">{body}</svg>').encode("utf-8")


def pixmap(name: str, colour: str = "#e8ebf2", size: int = 32) -> QPixmap:
    """Rasterise :func:`svg` (Qt renders SVG from data, no files involved)."""
    from PyQt6.QtSvg import QSvgRenderer
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg(name, colour, size)))
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


def icon(name: str, colour: str = "#e8ebf2", size: int = 64) -> QIcon:
    """Return a :class:`QIcon` for *name*, tinted *colour*."""
    return QIcon(pixmap(name, colour, size))


def themed_icon(name: str, theme: str = "midnight", size: int = 64,
                role: str = "textDim") -> QIcon:
    """:func:`icon` with the colour taken from a UI theme token."""
    return icon(name, tokens(theme).get(role, "#e8ebf2"), size)


def icon_names() -> List[str]:
    return sorted(_ICONS)


def splash_pixmap(size: int = 256) -> QPixmap:
    """A small brand mark used by dialogs and the about box."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    from PyQt6.QtSvg import QSvgRenderer
    art = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 64 64">'
        '<circle cx="32" cy="32" r="30" fill="#161922" stroke="#f0b429" stroke-width="2"/>'
        '<path d="M22 46h20l-2-7H24z" fill="#f0b429"/>'
        '<path d="M25 38h14l-1.6-5H26.6z" fill="#f0b429" opacity=".75"/>'
        '<circle cx="32" cy="20" r="6" fill="#f0b429"/>'
        '<path d="M14 20 32 8l18 12" fill="none" stroke="#4cc2ff" stroke-width="2.4" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>')
    QSvgRenderer(QByteArray(art.encode())).render(QPainter(pm))
    return pm
