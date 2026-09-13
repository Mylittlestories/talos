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


def _saved_theme() -> str:
    """The interface theme the player last picked."""
    import json
    from lc.ui.theme import PALETTE_NAMES
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "settings.json")
    try:
        with open(path) as fh:
            name = json.load(fh).get("ui_theme", "midnight")
        return name if name in PALETTE_NAMES else "midnight"
    except Exception:
        return "midnight"


def main() -> int:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    _install_excepthook()

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
    theme.apply(_saved_theme())

    from lc.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
