#!/usr/bin/env python3
"""Render screenshots of the running application (needs a display or Xvfb).

    DISPLAY=:99 python tools/capture_preview.py [output_dir]
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

import chess
from PIL import Image
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

OUT = sys.argv[1] if len(sys.argv) > 1 else "preview"
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv[:1])


def spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


from lc.ui.main_window import MainWindow           # noqa: E402

window = MainWindow()
window.settings["show_result_dialog"] = False
window.resize(1280, 860)
window.show()
spin(600)

# ---------------------------------------------------------------- 1. playing
from lc.core.game import TimeControl                # noqa: E402
from lc.core.players import BuiltInPlayer, HumanPlayer  # noqa: E402

window.game.set_player(chess.WHITE, HumanPlayer("You"))
window.game.set_player(chess.BLACK, BuiltInPlayer())
window.new_game(interactive=False, reuse=True)
for san in ("e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6"):
    move = window.game.board.parse_san(san)
    window.do_move(move)
    spin(120)
window.toggle_analysis()
spin(3500)
window.grab().save(os.path.join(OUT, "01-playing.png"))
print("01-playing.png")

# ---------------------------------------------------------------- 2. training
from lc.training import sessions                    # noqa: E402

rows = [r for r in sessions.available_sets(window.db) if r[1] == "tactics"]
session = sessions.SolveSession(window.db, rows[0][0], window, kind="tactics")
task = session.start_task()
window.training_session = session
session.taskChanged.connect(window.on_training_task)
window.setup_training_game(task)
spin(400)
window.tabs.setCurrentWidget(window.training_panel)
if task.solution and task.solution[0] in window.game.board.legal_moves:
    window.training_move(task.solution[0])
spin(1200)
window.show_hint()
window.grab().save(os.path.join(OUT, "02-training.png"))
print("02-training.png")
window.stop_training(silent=True)

# ------------------------------------------------------------- 3. battle 3D
window.battle_action.setChecked(True)
window.toggle_battle()
battle = window.battle_widget
if battle is not None:
    spin(900)
    board = chess.Board("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 6 5")
    battle.sync_position(board)

    class _Rec:
        pass

    def make_record(b: chess.Board, san: str):
        fen_before = b.fen()
        move = b.parse_san(san)
        rec = _Rec()
        rec.move = move
        rec.fen_before = fen_before
        rec.capture = b.piece_at(move.to_square)
        rec.captured_square = move.to_square
        rec.is_en_passant = b.is_en_passant(move)
        rec.is_castle = b.is_castling(move)
        rec.is_promotion = bool(move.promotion)
        b.push(move)
        rec.fen_after = b.fen()
        return rec

    board.push_san("Nxe5")                      # set the position after a capture
    battle.sync_position(board)
    spin(700)
    window.grab().save(os.path.join(OUT, "03-battle-board.png"))
    print("03-battle-board.png")

    # capture with a fight, recorded as an animated gif
    before = chess.Board("r1bqk2r/pppp1ppp/2n2n2/2b1N3/4P3/2N5/PPPP1PPP/R1BQK2R b KQkq - 0 6")
    battle.sync_position(before)
    battle.play_move(make_record(before, "Nxe5"))
    frames = []
    for _ in range(70):
        battle._tick()
        app.processEvents()
        if not frames or len(frames) < 60:
            path = f"/tmp/_bframe_{len(frames):03d}.png"
            battle.grab().save(path)
            frames.append(path)
        if not battle.fights and len(frames) > 30:
            break
    if frames:
        images = [Image.open(p).convert("RGB").resize((620, int(620 * Image.open(p).height /
                                                               Image.open(p).width)))
                  for p in frames]
        gif_path = os.path.join(OUT, "04-battle-fight.gif")
        images[0].save(gif_path, save_all=True, append_images=images[1:],
                       duration=90, loop=0, optimize=True)
        print(f"04-battle-fight.gif ({len(images)} frames)")
    window.grab().save(os.path.join(OUT, "05-battle-after.png"))
    print("05-battle-after.png")
    window.battle_action.setChecked(False)
    window.toggle_battle()

# ------------------------------------------------------------ 6. crazyhouse
cfg = dict(window.game_cfg)
cfg["variant"] = "crazyhouse"
cfg["white"] = dict(cfg["white"], type="human", name="You")
cfg["black"] = dict(cfg["black"], type="builtin", level="Wood", limit_ms=300, depth=2)
cfg["tc"] = TimeControl(unlimited=True)
window.game_cfg = cfg
window.new_game(interactive=False, reuse=True)
for san in ("e4", "d5", "exd5", "Qxd5", "Nc3", "Qd8"):
    move = window.game.board.parse_san(san) if True else None
    try:
        move = window.game.board.parse_san(san)
    except Exception:
        continue
    if move in window.game.board.legal_moves:
        window.do_move(move)
spin(400)
window.grab().save(os.path.join(OUT, "06-crazyhouse.png"))
print("06-crazyhouse.png")

# ------------------------------------------------------- 7. opening explorer
cfg["variant"] = "standard"
window.game_cfg = cfg
window.new_game(interactive=False, reuse=True)
for san in ("e4", "e5", "Nf3", "Nc6", "Bb5"):
    window.do_move(window.game.board.parse_san(san))
from lc.data.openings import OpeningExplorerDialog  # noqa: E402

dialog = OpeningExplorerDialog(window.db, window.game.board, window)
dialog.show()
spin(500)
dialog.grab().save(os.path.join(OUT, "07-explorer.png"))
print("07-explorer.png")
dialog.close()

print("screenshots written to", os.path.abspath(OUT))
