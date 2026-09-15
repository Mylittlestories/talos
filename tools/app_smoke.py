#!/usr/bin/env python3
"""Drive the running application, not its parts.

The selftest covers the engines and the rules; this covers the wiring
between them: that the window builds, that the three named land-game dialogs
start their own games and that each game then plays, and that Battle Chess
either runs or says plainly that it cannot.

Run it with::

    python tools/app_smoke.py

It needs a display, or QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from typing import Callable, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Keep the source database pristine while running the application end to end.
os.environ.setdefault("TALOS_DATA_DIR", os.path.join(
    tempfile.gettempdir(), f"talos-app-smoke-{os.getpid()}"))

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

    # File associations on Windows/Linux must load the clicked PGN, rather
    # than simply start a second empty window. Exercise the same method used
    # by run.py before moving on to the game-mode smoke tests.
    section("opening a PGN from the operating system")
    from run import _startup_pgn
    pgn_path = os.path.join(tempfile.gettempdir(), f"talos-smoke-{os.getpid()}.pgn")
    with open(pgn_path, "w", encoding="utf-8") as fh:
        fh.write('[Event "Association smoke"]\n\n1. e4 e5 2. Nf3 *\n')
    try:
        check("a PGN argument is recognised", _startup_pgn([pgn_path]) == pgn_path)
        imported = window.open_pgn_file(pgn_path)
        check("a clicked PGN is loaded into the game",
              imported and len(window.game.records) == 3,
              f"{len(window.game.records)} moves")
    finally:
        try:
            os.unlink(pgn_path)
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------
    section("the three independent land games")
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

    # Each game has a dedicated dialog. SOLO and Anarcheckers must not be
    # hidden as a selector inside the standard Anarchess configuration.
    section("the dedicated land-game dialogs")
    from lc.anarchess.dialog import AnarchessDialog

    def dialog_for(mode: str) -> AnarchessDialog:
        dialog = AnarchessDialog(players=2, variant=mode)
        app.processEvents()
        return dialog

    for mode, flags in (("standard", (False, False)),
                        ("solo", (True, False)),
                        ("checkers", (False, True))):
        dialog = dialog_for(mode)
        rules = dialog.config()["rules"]
        check(f"{mode} has its own dialog rules",
              (rules.solo, rules.checkers) == flags,
              f"solo={rules.solo} checkers={rules.checkers}")
        check(f"{mode} dialog has no attached mode selector", not hasattr(dialog, "mode"))
    dialog = AnarchessDialog(players=4, variant="solo")
    app.processEvents()
    solo_cfg = dialog.config()
    check("solo locks every seat to the one human",
          not dialog.players.isEnabled() and not dialog.level.isEnabled()
          and all(c.currentData() == "human" for c in dialog.seat_combos),
          f"{len(dialog.seat_combos)} seats, opponents box off")
    check("solo is always a two-tribe game",
          solo_cfg["players"] == 2 and solo_cfg["seats"] == ["human", "human"],
          f"{solo_cfg['players']} tribes")
    check("the reserve penalty is a dial",
          dialog.config()["rules"].reserve_penalty == 6)

    # The menu entries retain distinct live boards; returning to Anarchess
    # must not silently replace it with the SOLO or Anarcheckers configuration.
    window.show_anarchess()
    standard_view = window.land_views["standard"]
    standard_game = standard_view.game
    window.show_anarchess_solo()
    menu_solo_view = window.land_views["solo"]
    window.show_anarcheckers()
    checkers_view = window.land_views["checkers"]
    check("desktop land entries have independent persistent pages",
          len({id(standard_view), id(menu_solo_view), id(checkers_view)}) == 3
          and not standard_view.game.rules.solo
          and menu_solo_view.game.rules.solo
          and checkers_view.game.rules.checkers)
    window.show_anarchess()
    check("returning to Anarchess keeps its original game",
          window.stack.currentWidget() is standard_view and standard_view.game is standard_game)

    # The actual canvas view must give one person the turns and the pawns of
    # both alternating tribes in SOLO; rule-only tests cannot catch this.
    section("solo controls")
    solo_view = AnarchessView()
    solo_view.start({"players": 4, "seats": ["human"] * 4,
                     "rules": AnarchessRules(solo=True), "seed": 2})
    solo_game = solo_view.game
    check("the solo view normalises a four-player request",
          solo_game.players == 2 and solo_view._my_turn(),
          f"{solo_game.players} tribes, turn {solo_game.current + 1}")
    # Make the acting tribe Dark while the turn owner is Light. The view must
    # still let the one solo player select that Dark pawn.
    from lc.anarchess.rules import DARK, LIGHT
    solo_game.tiles = {(0, 0): LIGHT, (1, 0): DARK}
    solo_game.pawns = {(0, 0): 1}
    solo_game.current = 0
    solo_game.placed_tile = True
    solo_game.last_tile = (0, 0)
    solo_view._refresh()
    solo_view._on_cell(0, 0)
    check("the solo player controls the other tribe's pawn",
          solo_view.selected_pawn == (0, 0),
          f"actor {solo_game.acting_pawn_player() + 1}")
    # With no pawn of either tribe available to move, SOLO must expose its
    # model's legal pass rather than trapping the player in phase two.
    solo_game.tiles = {(0, 0): LIGHT}
    solo_game.pawns = {}
    solo_game.reserve = [0, 0]
    solo_game.current = 0
    solo_game.drawn = LIGHT
    solo_game.placed_tile = True
    solo_game.last_tile = (0, 0)
    solo_view.selected_pawn = None
    solo_view._refresh()
    pass_was_enabled = solo_view.skip_button.isEnabled()
    before_current = solo_game.current
    solo_view._skip()
    check("a stranded solo player can pass the pawn phase",
          pass_was_enabled and not solo_game.placed_tile
          and solo_game.current == (before_current + 1) % solo_game.players)

    section("shared-table controls")
    shared_view = AnarchessView()
    shared_view.start({"players": 2, "seats": ["human", "human"],
                       "rules": AnarchessRules(), "seed": 3})
    shared_view.game.current = 0
    first_human_turn = shared_view._my_turn()
    shared_view.game.current = 1
    second_human_turn = shared_view._my_turn()
    check("each local human can take their tribe's turn",
          first_human_turn and second_human_turn)
    # A light tile touching exactly one light neighbour violates R1. It must
    # neither be hinted nor be sent as a placement when clicked.
    shared_game = shared_view.game
    shared_game.tiles = {(0, 0): LIGHT, (0, 1): DARK}
    shared_game.pawns = {}
    shared_game.supply = {LIGHT: 4, DARK: 4}
    shared_game.current = 0
    shared_game.drawn = LIGHT
    shared_game.placed_tile = False
    shared_view._refresh()
    shared_view._on_cell(1, 0)
    check("the desktop only offers legal R1 tile placements",
          (1, 0) not in shared_view.board.canvas.legal_cells
          and not shared_game.placed_tile)

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
    check("the battle switches are all there",
          prefs.battle_idle is not None and prefs.battle_animation is not None,
          "idle, animation")
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
