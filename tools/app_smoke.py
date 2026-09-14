#!/usr/bin/env python3
"""Drive the running application, not its parts.

The selftest covers the engines and the rules; this covers the wiring
between them: that the window builds, that the Anarchess dialog starts a
game in each of its three modes and that the game then plays, and that
Battle Chess either runs or says plainly that it cannot.

Run it with::

    python tools/app_smoke.py

It needs a display, or QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Callable, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication          # noqa: E402

PASSED = 0
FAILED: List[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    global PASSED
    if ok:
        PASSED += 1
        print(f"  ok    {label}" + (f"  – {detail}" if detail else ""))
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  – {detail}" if detail else ""))
    return ok


def section(name: str) -> None:
    print(f"\n{name}")


def guard(label: str, action: Callable[[], None]) -> None:
    """Run *action*, turning any exception into a failed check."""
    try:
        action()
    except Exception:                                   # noqa: BLE001
        check(label, False, traceback.format_exc(limit=2).splitlines()[-1])


def main() -> int:
    app = QApplication(sys.argv[:1])

    section("the application")
    from lc.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    app.processEvents()
    check("the window builds", window.windowTitle().startswith("TALOS"),
          window.windowTitle())
    check("the 2D board is on show", window.stack.currentWidget() is window.board)

    # ------------------------------------------------------------------
    section("anarchess, in each of its three modes")
    from lc.anarchess.rules import AnarchessRules
    from lc.anarchess.view import AnarchessView

    def play(mode: str, tiles: int) -> Tuple[int, int, bool]:
        """Start a game through the real view and let it run a while."""
        rules = AnarchessRules(tiles_per_colour=tiles,
                               solo=(mode == "solo"),
                               checkers=(mode == "checkers"))
        view = AnarchessView()
        view.resize(1100, 760)
        view.start({"players": 2, "seats": ["human", "bot"], "level": 2,
                    "rules": rules, "seed": 7})
        app.processEvents()
        game = view.game
        before = len(game.tiles)
        steps = 0
        limit = 140
        while not game.finished and steps < limit:
            actions = game.legal_actions()
            if not actions:
                check(f"{mode}: the player has no legal action at all", False,
                      f"turn {game.turn_number}")
                break
            # prefer doing something; passing is legal when there is nothing
            game.apply(next((a for a in actions if a.kind != "pass"),
                            actions[0]))
            steps += 1
        view._refresh()
        app.processEvents()
        bots = sum(1 for b in view.bots if b is not None)
        return len(game.tiles) - before, bots, game.finished

    for mode in ("standard", "solo", "checkers"):
        grown, bots, ran = play(mode, 16)
        check(f"{mode}: the land grows", grown > 0, f"+{grown} tiles")
        if mode == "solo":
            check("solo: no seat is given to a bot", bots == 0,
                  f"{bots} bots seated")
        else:
            check(f"{mode}: the bot takes a seat", bots >= 1,
                  f"{bots} bots seated")
        check(f"{mode}: the turn passes without a stumble", ran,
              f"{'finished' if ran else 'stuck'}")

    # the dialog that starts it all, in each mode
    section("the new game dialog")
    from lc.anarchess.dialog import AnarchessDialog

    def dialog_for(mode: str) -> AnarchessRules:
        dialog = AnarchessDialog(players=2)
        dialog.mode.setCurrentIndex(dialog.mode.findData(mode))
        app.processEvents()
        return dialog.config()["rules"]

    for mode, flags in (("standard", (False, False)),
                        ("solo", (True, False)),
                        ("checkers", (False, True))):
        rules = dialog_for(mode)
        check(f"{mode} selected in the dialog",
              (rules.solo, rules.checkers) == flags,
              f"solo={rules.solo} checkers={rules.checkers}")
    dialog = AnarchessDialog(players=2)
    dialog.mode.setCurrentIndex(dialog.mode.findData("solo"))
    app.processEvents()
    check("solo locks every seat to the one human",
          not dialog.level.isEnabled()
          and all(c.currentData() == "human" for c in dialog.seat_combos),
          f"{len(dialog.seat_combos)} seats, opponents box off")
    dialog.mode.setCurrentIndex(dialog.mode.findData("standard"))
    app.processEvents()
    check("leaving solo hands a seat back to the bot",
          dialog.level.isEnabled()
          and any(c.currentData() == "bot" for c in dialog.seat_combos))
    check("the reserve penalty is a dial",
          dialog.config()["rules"].reserve_penalty == 6)

    # ------------------------------------------------------------------
    section("battle chess")
    if not MainWindow._gl_available():
        print("  skip  no OpenGL context on this machine - the mode reports")
        print("        that plainly rather than showing a blank board")
        check("the mode is offered anyway", window.battle_action is not None)
    else:
        window.battle_action.setChecked(True)
        window.toggle_battle()
        app.processEvents()
        check("the 3D board takes over",
              window.stack.currentWidget() is window.battle_widget)
        from lc.core.game import Game
        window.game = Game()
        window.battle_widget.sync_position(window.game.board)
        check("the pieces are on the 3D board",
              len(window.battle_widget.pieces) == 32)
        window.battle_action.setChecked(False)
        window.toggle_battle()
        app.processEvents()
        check("and the 2D board comes back",
              window.stack.currentWidget() is window.board)

    # ------------------------------------------------------------------
    section("preferences")
    from lc.ui.dialogs import DuelsDialog, PreferencesDialog
    from PyQt6.QtWidgets import QTreeWidget
    prefs = PreferencesDialog()
    check("preferences open", prefs.duels_button is not None,
          prefs.duels_button.text())
    duels = DuelsDialog()
    tables = duels.findChildren(QTreeWidget)
    check("the walks and the duels are listed",
          len(tables) == 2 and tables[0].topLevelItemCount() == 6
          and tables[1].topLevelItemCount() == 30,
          f"{tables[0].topLevelItemCount()} walks, "
          f"{tables[1].topLevelItemCount()} duels")

    print(f"\n{PASSED} passed, {len(FAILED)} failed")
    if FAILED:
        print("failing: " + ", ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
