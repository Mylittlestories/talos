#!/usr/bin/env python3
"""
TALOS - The Living Chess Studio.

    python run.py

A modern chess playing, training and analysis suite inspired by Lucas Chess,
with a Battle Chess style 3D combat renderer, the Anarchess land-building game
and the Anarchchess ruleset.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _install_excepthook() -> None:
    """Keep a Qt slot exception from aborting the whole program."""
    import traceback

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        traceback.print_exception(exc_type, exc, tb)
        try:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                None, "Unexpected error",
                "".join(traceback.format_exception(exc_type, exc, tb))[-3000:])
        except Exception:
            pass

    sys.excepthook = hook


def _app_icon():
    """The TALOS mark, for the window title bar and the taskbar.

    PyInstaller stamps the icon into the Windows and macOS bundles, but the
    running window only shows it if the application is told about it - and on
    Linux the bundle carries no icon at all, so the window used to come up
    with Qt's default.
    """
    from PyQt6.QtGui import QIcon

    # ``resource_root`` is PyInstaller's _MEIPASS in a frozen bundle and the
    # repository root while developing. It keeps the taskbar icon available on
    # Windows, Linux and macOS without treating player data as an app resource.
    from lc.paths import resource_root
    root = os.path.dirname(os.path.abspath(__file__))
    bases = [str(resource_root()), root]
    icon = QIcon()
    for name in ("assets/talos-16.png", "assets/talos-32.png",
                 "assets/talos-48.png", "assets/talos-128.png",
                 "assets/talos-256.png", "assets/favicon.ico"):
        for base in bases:
            path = os.path.join(base, name)
            if os.path.exists(path):
                icon.addFile(path)
                break
    return icon


def _saved_theme() -> str:
    """The interface theme the player last picked."""
    import json
    from lc.paths import settings_path
    from lc.ui.theme import PALETTE_NAMES
    path = settings_path()
    try:
        with open(path) as fh:
            name = json.load(fh).get("ui_theme", "midnight")
        return name if name in PALETTE_NAMES else "midnight"
    except Exception:
        return "midnight"


def _startup_pgn(arguments: list[str]) -> Optional[str]:
    """Return the first existing PGN passed by a file association, if any."""
    for argument in arguments:
        # A desktop launcher may add switches in the future. Only treat a real
        # PGN file as a document, so an arbitrary command-line argument cannot
        # unexpectedly become an import attempt.
        path = os.path.abspath(os.path.expanduser(argument))
        if path.lower().endswith(".pgn") and os.path.isfile(path):
            return path
    return None


def main() -> int:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    _install_excepthook()
    startup_pgn = _startup_pgn(sys.argv[1:])

    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)

    from lc import APP_NAME, APP_VERSION
    from lc.ui import theme

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("TALOS")
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setWindowIcon(_app_icon())
    theme.apply(_saved_theme())

    from lc.ui.main_window import MainWindow

    window = MainWindow()
    if startup_pgn:
        window.open_pgn_file(startup_pgn)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
