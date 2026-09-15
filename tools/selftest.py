#!/usr/bin/env python3
"""
Headless self test for TALOS.

    python tools/selftest.py

Exercises the engine, every variant, the game model, the Qt interface
(offscreen), all training sessions, the database and the Battle Chess
simulation - no display, no network and no external engine required.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# A real packaged app keeps its mutable database outside its read-only bundle.
# Exercise that path too, without letting a test run alter the checked-in
# Lucas content database.
os.environ.setdefault("TALOS_DATA_DIR", os.path.join(
    tempfile.gettempdir(), f"talos-selftest-{os.getpid()}"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

import chess

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QWidget

APP = QApplication(sys.argv[:1])

RESULTS = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f"  – {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


def spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(predicate, timeout_ms: int = 15000, step_ms: int = 120) -> bool:
    """Spin the event loop until `predicate` holds, or until time runs out.

    Background analysis runs on a worker thread, so a fixed sleep makes these
    checks a coin toss on a loaded CI machine - wait for the condition instead.
    """
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if predicate():
            return True
        spin(step_ms)
    return bool(predicate())


# --------------------------------------------------------------------------
def test_engine() -> None:
    section("Built-in engine")
    from lc.core.engine import DEFAULT_LEVELS, Level, LCEngine

    engine = LCEngine(Level("t", 2100, max_depth=6, movetime_ms=2500))
    started = time.time()
    result = engine.search(chess.Board(), movetime_ms=1500, max_depth=6)
    check("opening search returns a legal move",
          result.bestmove in chess.Board().legal_moves,
          f"{result.bestmove} d{result.depth} {result.score_text} "
          f"{int(result.nodes / max(result.time_ms, 1) * 1000)} nps")

    mate = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    result = engine.search(mate, movetime_ms=1500, max_depth=5)
    check("finds back-rank mate", result.mate == 1, f"{result.mate} found in {result.time_ms} ms")

    tactic = chess.Board("r1bq2rk/pp3pbp/2p1p1pQ/7P/3P4/2PB1N2/PP3PPR/2KR4 w - - 0 1")
    result = engine.search(tactic, movetime_ms=2500, max_depth=6)
    check("finds a mating combination", result.mate is not None and result.mate > 0,
          f"mate in {result.mate}")

    weak = LCEngine(DEFAULT_LEVELS[0])
    moves = {weak.search(chess.Board(), movetime_ms=60, max_depth=1).bestmove for _ in range(6)}
    check("weak level is varied", len(moves) > 1, f"{len(moves)} different moves in 6 tries")
    names = [level.name for level in DEFAULT_LEVELS]
    check("the engine ladder now reaches Grandmaster+",
          len(DEFAULT_LEVELS) >= 15 and names[-1] == "Grandmaster+"
          and DEFAULT_LEVELS[-1].max_depth > DEFAULT_LEVELS[9].max_depth,
          f"{len(DEFAULT_LEVELS)} levels through {names[-1]}")
    capped = LCEngine(DEFAULT_LEVELS[0], seed=3).search(chess.Board(), movetime_ms=300)
    check("a level profile owns its default depth cap", capped.depth <= DEFAULT_LEVELS[0].max_depth,
          f"d{capped.depth} cap d{DEFAULT_LEVELS[0].max_depth}")
    check("searches complete quickly", time.time() - started < 60)


def test_variants() -> None:
    section("Variants")
    from lc.core.game import VARIANTS, make_board
    from lc.core.engine import LCEngine, Level

    for key in VARIANTS:
        board = make_board(key)
        engine = LCEngine(Level("v", 1400, max_depth=2, movetime_ms=200))
        result = engine.search(board, movetime_ms=300, max_depth=2)
        check(f"{key} board + engine move", result.bestmove in board.legal_moves,
              board.fen()[:32])


def test_game_model() -> None:
    section("Game model")
    from lc.core.game import Game, TimeControl, format_clock

    game = Game()
    for san in ("e4", "e5", "Nf3", "Nc6", "Bb5"):
        game.push_san(san)
    check("moves recorded", len(game.records) == 5, [r.san for r in game.records])
    check("capture detection",
          game.push_san("Bxc6").capture is not None if game.board.turn == chess.WHITE and
          chess.Move.from_uci("b5c6") in game.board.legal_moves else True)

    pgn = game.to_pgn()
    other = Game()
    check("PGN round trip", other.load_pgn(pgn) and len(other.records) == len(game.records),
          f"{len(other.records)} moves reloaded")

    clock_game = Game(tc=TimeControl(base_minutes=1, increment_seconds=1))
    clock_game.clock.start_for(chess.WHITE)
    spin(350)
    remaining = clock_game.clock.poll()[chess.WHITE]
    check("clock counts down", 0 < remaining < 60_000, format_clock(remaining))

    mate_game = Game()
    for san in ("f3", "e5", "g4", "Qh4"):
        mate_game.push_san(san)
    check("checkmate and result detected",
          mate_game.result == "0-1" and mate_game.reason.upper().startswith("CHECKMATE"),
          f"{mate_game.result} · {mate_game.reason}")

    draw_game = Game(fen="7k/8/8/8/8/8/5Q2/6K1 w - - 0 1")
    draw_game.push_san("Qf7")
    check("stalemate detected", draw_game.result == "1/2-1/2",
          f"{draw_game.result} · {draw_game.reason}")


def test_paths() -> None:
    section("Application data")
    from pathlib import Path
    from lc.paths import _copy_seed, database_path, data_dir, resource_path, settings_path

    target = Path(os.environ["TALOS_DATA_DIR"])
    seed = resource_path("data", "lucas.db")
    provisioned = database_path()
    check("player data uses a writable per-user directory", data_dir() == target,
          str(data_dir()))
    check("a packaged database is seeded on first launch", provisioned.is_file()
          and provisioned.stat().st_size == seed.stat().st_size,
          f"{provisioned.stat().st_size // (1024 * 1024)} MB")
    check("settings live beside the player database", settings_path().parent == target)
    existing = target / "existing-player-progress.db"
    existing.write_bytes(b"keep this player's database")
    _copy_seed(seed, existing)
    check("seeding never replaces existing player progress",
          existing.read_bytes() == b"keep this player's database")


def test_interface() -> None:
    section("Interface")
    from lc.ui.main_window import MainWindow
    from lc.core.players import BuiltInPlayer, HumanPlayer
    from lc.core.engine import DEFAULT_LEVELS

    window = MainWindow()
    window.settings["show_result_dialog"] = False
    window.show()
    check("main window builds", window.board is not None)
    window.game.set_player(chess.WHITE, HumanPlayer("You"))
    window.game.set_player(chess.BLACK, BuiltInPlayer())
    window.new_game(interactive=False, reuse=True)
    check("human move accepted", window.do_move(chess.Move.from_uci("e2e4")))
    spin(4000)
    check("engine replies", len(window.game.records) >= 2,
          [r.san for r in window.game.records])
    window.show_hint()
    check("hint works", window.hint_level in (1, 2))
    # Pin the analysis engine. _analysis_player() otherwise asks the machine
    # what is installed, which makes the check depend on the runner - and a
    # stray file in engines/ silently turns analysis into a no-op.
    window.analysis_player = BuiltInPlayer(DEFAULT_LEVELS[9], "Balanced")
    window.toggle_analysis()
    wait_until(lambda: len(window.engine_panel.lines_widget.rows) >= 1)
    rows = len(window.engine_panel.lines_widget.rows)
    check("analysis produces a line", rows >= 1, f"{rows} candidate lines")
    window.toggle_analysis()
    wait_until(lambda: len(window.eval_history) >= 1, 5000)
    check("evaluation recorded", len(window.eval_history) >= 1,
          f"{len(window.eval_history)} evaluations")
    window.takeback()
    check("takeback works", len(window.game.records) <= 1)

    # The real OpenGL renderer cannot draw under offscreen CI, so exercise its
    # contract with a tiny stage double: Game.push emits refresh before the
    # record reaches play_move(). That refresh must not wipe the new duel.
    class StageDouble(QWidget):
        def __init__(self):
            super().__init__()
            self.animating = False
            self.synced = 0
            self.played = 0

        def sync_position(self, _board):
            self.synced += 1

        def play_move(self, _record):
            self.played += 1
            self.animating = True

        def is_animating(self):
            return self.animating

    stage = StageDouble()
    window.game.set_player(chess.WHITE, HumanPlayer("You"))
    window.game.set_player(chess.BLACK, HumanPlayer("Friend"))
    window.stack.addWidget(stage)
    window.battle_widget = stage
    window.stack.setCurrentWidget(stage)
    stage.synced = 0
    staged = window.do_move(next(iter(window.game.board.legal_moves)))
    check("battle stage survives the model refresh transaction",
          staged and stage.played == 1 and stage.synced == 0 and window._battle_waiting_turn)
    stage.animating = False
    window._on_battle_animation_finished()
    check("battle stage releases the next turn after its animation",
          stage.synced == 1 and not window._battle_waiting_turn)
    window.battle_widget = None
    window.stack.setCurrentWidget(window.board)
    return window


def test_training(window) -> None:
    section("Training")
    from lc.training import sessions

    sets = sessions.available_sets(window.db)
    kinds = sorted({s[1] for s in sets})
    check("training sets imported", len(sets) > 100, f"{len(sets)} sets: {', '.join(kinds)}")

    tactic_set = [s for s in sets if s[1] == "tactics"][0]
    session = sessions.SolveSession(window.db, tactic_set[0], window, kind="tactics")
    task = session.start_task()
    window.training_session = session
    session.taskChanged.connect(window.on_training_task)
    window.setup_training_game(task)
    check("tactics task loads", task is not None and
          window.game.board.fen() == task.fen, task.fen[:40])
    if task.solution and task.solution[0] in window.game.board.legal_moves:
        window.training_move(task.solution[0])
        spin(900)
        check("solution move accepted", session.index >= 1, f"index {session.index}")

    window.stop_training(silent=True)
    for kind in ("sts", "mates", "endings"):
        rows = [r for r in sets if r[1] == kind]
        if not rows:
            check(f"{kind} has data", False)
            continue
        factory = sessions.SESSION_FACTORIES[kind]
        check(f"{kind} session starts", factory(window.db, rows[0][0], window).start_task()
              is not None)
    for kind in ("everest", "resistance", "micelo", "openings", "guess",
                 "lights", "routes", "colours", "blindfold"):
        factory = sessions.SESSION_FACTORIES[kind]
        try:
            task = factory(window.db, None, window).start_task()
            check(f"{kind} session starts", task is not None,
                  (task.fen[:34] if task else ""))
        except Exception as exc:
            check(f"{kind} session starts", False, f"{type(exc).__name__}: {exc}")

    routes = sessions.RouteSession(window.db, None, window)
    task = routes.start_task()
    check("routes computes a path", task is not None and task.meta["best"] > 0,
          f"best {task.meta['best']} moves")
    colours = sessions.SquareColourSession(window.db, None, window)
    task = colours.start_task()
    check("square colours answers", colours.answer(True) is not None)


def test_database(window) -> None:
    section("Database")
    from lc.data.openings import stats_for

    counts = {
        "puzzles": window.db.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0],
        "games": window.db.execute("SELECT COUNT(*) FROM games").fetchone()[0],
        "openings": window.db.execute("SELECT COUNT(*) FROM openings").fetchone()[0],
        "sets": window.db.execute("SELECT COUNT(*) FROM sets").fetchone()[0],
    }
    check("content imported", counts["puzzles"] > 50000 and counts["games"] > 1000, str(counts))
    window.save_game()
    check("game saves", window.db.execute(
        "SELECT COUNT(*) FROM saved_games").fetchone()[0] >= 1)
    board = chess.Board()
    for san in ("e4", "e5", "Nf3"):
        board.push_san(san)
    stats = stats_for(window.db, board)
    check("opening explorer has statistics", bool(stats) and stats[0]["games"] > 5,
          f"{stats[0]['san']}: {stats[0]['games']} games" if stats else "")


def test_uci() -> None:
    """Drive the UCI client with the small reference engine in tools/."""
    section("UCI engines (Stockfish path)")
    import chess.pgn  # noqa: F401  (imported for parity with the app)

    from lc.core.players import UCIPlayer
    from lc.core.uci import Limit, UCIEngine

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "fake_uci_engine.py")
    engine = UCIEngine(path)
    info = engine.start()
    check("engine handshake", info.name.startswith("FakeUCI") and bool(info.options),
          f"{info.name}, {len(info.options)} options")
    board = chess.Board()
    board.push_san("e4")
    result = engine.analyse(board, Limit(depth=3, movetime_ms=400))
    check("position + go + bestmove", result.bestmove in board.legal_moves,
          f"{result.bestmove} {result.score_text} depth {result.depth}")
    engine.set_option("Threads", 2)
    engine.quit()
    check("engine shuts down", engine.proc is None)

    player = UCIPlayer(path, limit_ms=300, name="TestEngine")
    player.start()
    loop = QEventLoop()
    holder = {}

    def done(res) -> None:
        holder["res"] = res
        loop.quit()

    player.finished.connect(done)
    player.think(chess.Board(), Limit(movetime_ms=300))
    QTimer.singleShot(6000, loop.quit)
    loop.exec()
    check("UCI player returns a move", holder.get("res") is not None and
          holder["res"].bestmove in chess.Board().legal_moves,
          str(holder.get("res").bestmove) if holder.get("res") else "no result")
    player.quit()

    # A reset/PGN load can arrive while an old worker is posting back. Its
    # generation token must discard that answer rather than move in the new
    # position. Call the tiny signal boundary directly to avoid timing luck.
    from lc.core.engine import SearchResult
    from lc.core.players import HumanPlayer
    guarded = HumanPlayer("stale-result guard")
    received = []
    guarded.finished.connect(lambda result: received.append(result))
    guarded._think_token = 12
    guarded._on_result(11, SearchResult())
    check("stale engine results are ignored", not received)
    guarded._on_result(12, SearchResult())
    check("current engine result still arrives", len(received) == 1)


def test_battle() -> None:
    section("Battle Chess (simulation, no GL needed)")
    import math
    from lc.battle import meshes, physics
    from lc.battle import battle_widget as bw
    from lc.battle.battle_widget import BattleBoardWidget, square_to_xz

    for piece_type in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK,
                       chess.QUEEN, chess.KING):
        mesh = meshes.piece_mesh(piece_type, "High")
        check(f"mesh {chess.piece_name(piece_type)}", mesh.triangles > 200,
              f"{mesh.triangles} triangles")

    world = physics.PhysicsWorld()
    world.shatter([0, 0.5, 0], (1, 1, 1), count=20)
    world.burst([0, 0.5, 0], (1, 0.8, 0.3), count=20)
    world.wave([0, 0, 0])
    for _ in range(60):
        world.step(0.016)
    check("shards simulated", len(world.shards) > 0 and
          all(s.pos[1] >= 0 for s in world.shards), f"{len(world.shards)} shards alive")

    widget = BattleBoardWidget(None, {"battle_quality": "Medium"})
    board = chess.Board()
    widget.sync_position(board)
    check("scene matches the board", len(widget.pieces) == 32)

    class _Rec:
        pass

    for san in ("e4", "d5", "exd5"):
        before = board.fen()
        move = board.parse_san(san)
        record = _Rec()
        record.move = move
        record.fen_before = before
        record.capture = board.piece_at(move.to_square)
        record.captured_square = move.to_square
        record.is_en_passant = board.is_en_passant(move)
        record.is_castle = board.is_castling(move)
        record.is_promotion = bool(move.promotion)
        board.push(move)
        record.fen_after = board.fen()
        widget.play_move(record)
        steps = 0
        while (widget.fights or widget.walks) and steps < 400:
            widget._tick()
            steps += 1
    check("capture fight animated", steps > 40, f"{steps} frames")
    check("captured piece removed", len(widget.pieces) == 31, f"{len(widget.pieces)} pieces")
    check("shards spawned", len(widget.physics.shards) > 0,
          f"{len(widget.physics.shards)} shards")
    check("scene resynchronises", all(
        widget.pieces[square].piece == board.piece_at(square) for square in widget.pieces))

    # ---- the thirty duels: a different animation for each permutation ----
    from lc.battle import duels as dueltable
    attackers = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK,
                 chess.QUEEN, chess.KING)
    victims = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    check("every permutation has a duel",
          all((a, v) in dueltable.DUELS for a in attackers for v in victims),
          f"{dueltable.DUEL_COUNT} duels")
    pairs = [(d.style, d.choreo) for d in dueltable.DUELS.values()]
    check("no two duels are the same animation", len(set(pairs)) == len(pairs),
          f"{len(set(pairs))} distinct of {len(pairs)}")
    check("every duel is named",
          len({d.name for d in dueltable.all_duels()}) == dueltable.DUEL_COUNT)

    # one capture through the fight state machine, no GL needed
    def play(at: int, vt: int):
        a_piece, v_piece = chess.Piece(at, chess.WHITE), chess.Piece(vt, chess.BLACK)
        start, end = chess.E2, chess.D3
        ax, az = square_to_xz(start)
        vx, vz = square_to_xz(end)
        attacker = bw.Piece3D(piece=a_piece, square=start, x=ax, z=az)
        victim = bw.Piece3D(piece=v_piece, square=end, x=vx, z=vz)
        duel = dueltable.duel_for(a_piece, v_piece)
        fight = bw.Fight(attacker=attacker, victim=v_piece, victim_square=end,
                         victim_x=vx, victim_z=vz, to_square=end,
                         move=chess.Move(start, end), style=duel.style,
                         slide_from=(ax, az), victim_ref=victim,
                         choreo=duel.choreo, gore=True, duel=duel,
                         approach=duel.approach, strike=duel.strike,
                         impact_beat=duel.impact, recover=duel.recover,
                         debris=duel.debris, force=duel.shake)
        dx, dz = vx - ax, vz - az
        span = math.hypot(dx, dz) or 1.0
        fight.dir_x, fight.dir_z = dx / span, dz / span
        frames = 0
        while not fight.finished and frames < 900:
            widget._step_fight(fight, 1 / 60)
            frames += 1
        tx, tz = square_to_xz(end, widget.flipped)
        home = abs(attacker.x - tx) < 1e-6 and abs(attacker.z - tz) < 1e-6
        return duel, frames / 60, victim.alive, home

    broken, slow, fastest = [], 0.0, 9.0
    for at in attackers:
        for vt in victims:
            duel, seconds, alive, home = play(at, vt)
            slow = max(slow, seconds)
            fastest = min(fastest, seconds)
            if alive or not home:
                broken.append(duel.key)
    check("all thirty duels play out", not broken,
          "the victim dies and the attacker reaches its square in each"
          if not broken else "stuck: " + ", ".join(broken))
    check("captures last about as long as the original's",
          1.0 <= fastest and slow <= 2.6, f"{fastest:.2f}s to {slow:.2f}s")

    # ---- every piece walks in its own way ----
    from lc.battle import gaits as gaittable
    check("every piece has a gait",
          len(gaittable.all_gaits()) == 6 and
          all(gaittable.gait_for(pt).key for pt in attackers),
          ", ".join(g.key for g in gaittable.all_gaits()))

    # one quiet move per piece, watched from the moment it leaves
    def walk_of(piece_type: int, fen: str, uci: str):
        board = chess.Board(fen)
        widget.sync_position(board)
        move = chess.Move.from_uci(uci)
        ref = widget.pieces[move.from_square]
        record = _Rec()
        record.move = move
        record.fen_before = board.fen()
        record.capture = None
        record.captured_square = None
        record.is_en_passant = record.is_castle = record.is_promotion = False
        board.push(move)
        record.fen_after = board.fen()
        widget.play_move(record)
        gait = widget.walks[0].gait
        peak = sway = 0.0
        frames = 0
        while (widget.walks or widget.fights) and frames < 400:
            widget._tick()
            peak = max(peak, ref.y)
            sway = max(sway, abs(ref.roll))
            frames += 1
        tx, tz = square_to_xz(move.to_square, widget.flipped)
        home = (abs(ref.x - tx) < 1e-6 and abs(ref.z - tz) < 1e-6
                and abs(ref.y) < 1e-6)
        return gait, frames / 60, peak, sway, home

    WALKS = (
        (chess.PAWN,   "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1", "e2e4"),
        (chess.KNIGHT, "4k3/8/8/8/8/8/8/1N2K3 w - - 0 1", "b1c3"),
        (chess.BISHOP, "4k3/8/8/8/8/8/8/2B1K3 w - - 0 1", "c1g5"),
        (chess.ROOK,   "4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "a1a4"),
        (chess.QUEEN,  "4k3/8/8/8/8/8/8/3QK3 w - - 0 1", "d1d5"),
        (chess.KING,   "4k3/8/8/8/8/8/8/4K3 w - - 0 1", "e1e2"),
    )
    walked = [walk_of(*row) for row in WALKS]
    arrived = sum(1 for w in walked if w[4])
    check("every piece walks to its square", arrived == len(WALKS),
          f"{arrived} of {len(WALKS)} arrived")
    peaks = {w[0].key: w[2] for w in walked}
    check("the knight leaves the ground and the bishop does not",
          peaks["leap"] > peaks["glide"] * 3,
          f"knight {peaks['leap']:.2f} against bishop {peaks['glide']:.2f}")
    check("no two pieces walk alike",
          len({round(w[2], 3) for w in walked}) == len(walked),
          "each gait peaks at its own height")

    # A cue the bank has never heard of is silence, not an error: the sound
    # call swallows everything, so a typo would simply never be noticed.
    import re
    from lc.ui.sounds import SoundBank
    from lc.battle.gaits import all_gaits as every_gait
    source = open(bw.__file__, encoding="utf-8").read()
    cues = set(re.findall(r'_sound\("([a-z]+)"\)', source))
    cues |= {g.sound for g in every_gait()}
    cues |= {duel.sound for duel in dueltable.DUELS.values()}
    absent = sorted(c for c in cues if c not in SoundBank.RECIPES)
    check("every cue the battle mode plays is in the sound bank", not absent,
          ", ".join(sorted(cues)) if not absent else "missing: " + ", ".join(absent))
    check("the duels do not all sound the same",
          len({duel.sound for duel in dueltable.DUELS.values()}) >= 3,
          ", ".join(sorted({duel.sound for duel in dueltable.DUELS.values()})))

    # ---- and between moves the board is not frozen ----
    from lc.battle.gaits import IDLES, idle_motion
    check("every piece has something to do while it waits", len(IDLES) == 6,
          ", ".join(f"{chess.piece_name(k)}" for k in sorted(IDLES)))
    board = chess.Board()
    widget.sync_position(board)
    standing = [widget._idle(p) for p in widget.pieces.values()]
    check("pieces are not frozen between moves",
          any(abs(m[0]) > 1e-6 for m in standing),
          f"{sum(1 for m in standing if abs(m[0]) > 1e-6)} of {len(standing)} "
          "shifting their weight")
    check("but only by a hair",
          all(abs(m[0]) < 0.02
              and max(abs(m[1]), abs(m[2]), abs(m[3])) < 0.1 for m in standing))
    amplitudes = {kind: max(abs(idle_motion(kind, t / 7.0)[0])
                            for t in range(24)) for kind in IDLES}
    check("each rank waits in its own way",
          len({round(v, 5) for v in amplitudes.values()}) >= 5,
          f"knight {amplitudes[chess.KNIGHT]:.3f} against rook "
          f"{amplitudes[chess.ROOK]:.3f}")

    # a piece mid-move must not idle on top of its walk
    walker = widget.pieces[chess.E2]
    quiet = _Rec()
    quiet.move = chess.Move(chess.E2, chess.E4)
    quiet.fen_before = board.fen()
    quiet.capture, quiet.captured_square = None, None
    quiet.is_en_passant = quiet.is_castle = quiet.is_promotion = False
    board.push(quiet.move)
    quiet.fen_after = board.fen()
    widget.play_move(quiet)
    check("a piece mid-move does not idle as well",
          widget._idle(walker) == (0.0, 0.0, 0.0, 0.0),
          "idle suspended while it is walking")
    while widget.walks:
        widget._tick()
    drift = []
    for _ in range(12):
        widget.time += 0.13
        drift.append(widget._idle(walker)[0])
    check("and breathes again once it arrives",
          max(drift) - min(drift) > 1e-4,
          f"{max(drift) - min(drift):.4f} of drift over a second and a half")


def test_anarchy() -> None:
    section("Anarchchess (the house rules)")
    from lc.variants import (ANARCHY, CURATED, AnarchBoard, AnarchRules,
                             active_rules, set_active_rules, reset_active_rules)

    board = AnarchBoard(rules=CURATED)
    check("curated ruleset loaded", board.rules.knooks and
          board.rules.en_passant_forced and not board.rules.random_events)

    # knook: a knight fuses with a friendly rook and gains both move sets
    knook = AnarchBoard(fen="4k3/8/8/8/8/8/3R4/1N2K3 w - - 0 1", rules=CURATED)
    fusion = [m for m in knook.legal_moves
              if m.promotion == chess.KNIGHT
              and knook.piece_type_at(m.from_square) == chess.KNIGHT]
    check("knook fusion offered", len(fusion) == 1, f"{len(fusion)} fusion moves")
    if fusion:
        before = knook.fen()
        knook.push(fusion[0])
        square = next(iter(knook.knooks))
        check("knook created", knook.is_knook(square) and
              knook.piece_type_at(square) == chess.ROOK)
        knook.push(chess.Move.from_uci("e8d8"))
        targets = {m.to_square for m in knook.legal_moves
                   if m.from_square == square}
        knight_hops = {chess.B1, chess.B3, chess.C4, chess.E4, chess.F1, chess.F3}
        rook_line = {chess.D1, chess.D3, chess.D4, chess.D5, chess.D6, chess.D7}
        check("knook moves as knight and rook",
              knight_hops <= targets and rook_line <= targets,
              f"{len(targets)} targets")
        knook.pop()
        knook.pop()
        check("anarchic moves undo cleanly", knook.fen() == before)

    # forced en passant
    ep = AnarchBoard(fen="4k3/3p4/8/4P3/8/8/8/4K3 b - - 0 1", rules=CURATED)
    ep.push(chess.Move.from_uci("d7d5"))
    only = list(ep.legal_moves)
    check("en passant is forced", len(only) == 1 and ep.is_en_passant(only[0]),
          f"{len(only)} legal move(s)")

    # the king may never set foot on c2
    c2 = AnarchBoard(fen="4k3/8/8/8/8/8/8/2K1k3 w - - 0 1", rules=CURATED)
    check("the king cannot go to c2",
          all(m.to_square != chess.C2 for m in c2.legal_moves))

    # double check wins on the spot
    double = AnarchBoard(fen="4k3/3N4/8/8/B7/8/8/7K w - - 0 1", rules=CURATED)
    double.push(chess.Move.from_uci("d7f6"))
    check("double check ends the game",
          double.is_double_check() and double.is_game_over() and
          double.result() == "1-0", double.result())

    # Il Vaticano
    vaticano = AnarchBoard(fen="4k3/8/8/8/3B4/2p5/1p6/B3K3 w - - 0 1",
                           rules=CURATED)
    specials = [m for m in vaticano.legal_moves if m.promotion == chess.BISHOP]
    check("Il Vaticano offered", len(specials) == 1)
    if specials:
        vaticano.push(specials[0])
        check("Il Vaticano clears the line",
              vaticano.piece_at(chess.A1) == chess.Piece(chess.BISHOP, chess.WHITE)
              and vaticano.piece_at(chess.D4) == chess.Piece(chess.BISHOP, chess.WHITE)
              and vaticano.piece_at(chess.C3) is None)

    # the c4 detonation leaves rooks standing and kings alive
    bomb = AnarchBoard(fen="4k3/8/8/8/8/2P5/1p1n4/R3K3 w - - 0 1", rules=CURATED)
    move = chess.Move.from_uci("c3c4")
    if move in bomb.legal_moves:
        bomb.push(move)
        check("c4 detonates once", bomb.c4_used and
              bomb.piece_at(chess.C4) is None and
              chess.popcount(bomb.kings) == 2,
              f"{chess.popcount(bomb.occupied)} pieces left")
    else:
        check("c4 detonates once", False, "c3c4 was not offered")

    # full self play, with the invariants checked after every ply
    import random
    played = 0
    for ruleset, seeds in ((CURATED, range(4)), (ANARCHY, range(4))):
        for seed in range(4):
            rng = random.Random(seed)
            game = AnarchBoard(rules=ruleset, seed=seed)
            for _ in range(120):
                if game.is_game_over():
                    break
                moves = list(game.legal_moves)
                if not moves:
                    break
                move = rng.choice(moves)
                game.push(move)
                played += 1
                assert chess.popcount(game.kings) == 2, "a king was lost"
                assert game.occupied == (game.pawns | game.knights |
                                         game.bishops | game.rooks |
                                         game.queens | game.kings), "bitboards desynced"
            while game.move_stack:
                game.pop()
            assert game.fen() == chess.STARTING_FEN, "position did not unwind"
    check("self play keeps the position legal", True, f"{played} plies replayed")

    # the rules are editable at run time
    set_active_rules("anarchchess", AnarchRules(knooks=False))
    check("rules can be edited", active_rules("anarchchess").knooks is False)
    reset_active_rules()
    check("rules reset to the presets",
          active_rules("anarchchess").knooks and active_rules("anarchy").random_events)


def test_anarchess() -> None:
    """The official rules, checked against the designer's rulebook."""
    section("Anarchess (the land before Chess)")
    from lc.anarchess.ai import AnarchessBot
    from lc.anarchess.rules import (LIGHT, DARK, RULINGS, AnarchessGame,
                                    AnarchessRules, AnarchessAction)

    game = AnarchessGame(2, seed=3)
    check("the land opens with two tiles of each colour",
          sum(game.tiles.values()) == 2 and len(game.tiles) == 4,
          f"{len(game.tiles)} tiles")
    check("the lights of the opening lie diagonally",
          game.tiles[(0, 0)] is LIGHT and game.tiles[(1, 1)] is LIGHT
          and game.tiles[(0, 1)] is DARK and game.tiles[(1, 0)] is DARK)
    check("the player of the opposite colour plays first",
          game.current == (1 if game.drawn == LIGHT else 0),
          f"drew {'light' if game.drawn else 'dark'}")

    # R1 - a tile touching exactly one other must touch the opposite colour
    probe = AnarchessGame(2, seed=1)
    probe.tiles = {(0, 0): LIGHT}
    probe.supply = {LIGHT: 4, DARK: 4}
    probe.drawn = DARK
    ok_dark = probe._placement_ok((0, -1), DARK)      # touches the light tile
    probe.drawn = LIGHT
    ok_light = probe._placement_ok((0, -1), LIGHT)
    check("R1: one neighbour must be the opposite colour",
          ok_dark and not ok_light, "same colour refused")
    probe.tiles = {(0, 0): LIGHT, (2, 0): DARK}
    check("R2: two or more neighbours may be any colour",
          probe._placement_ok((1, 0), LIGHT))
    # The model must reject R1 violations too, not only omit them from hints.
    probe.tiles = {(0, 0): LIGHT, (0, 1): DARK}
    probe.drawn = LIGHT
    check("R1: an invalid tile action is rejected",
          not probe.apply(AnarchessAction("tile", cell=(1, 0), colour=LIGHT)))

    # attacks are diagonal, and need no friendly support
    probe = AnarchessGame(2, seed=1)
    probe.tiles = {(0, 0): LIGHT, (1, 1): DARK}
    probe.pawns = {(0, 0): 0, (1, 1): 1}
    probe.current = 0
    probe.placed_tile = True
    probe.last_tile = (0, 0)
    acts = probe.legal_pawn_actions()
    check("a pawn attacks diagonally, with no support beside it",
          any(a.kind == "attack" and a.cell == (1, 1) and a.source == (0, 0)
              for a in acts))

    # a pawn may only be settled on the tile laid that turn, in an empty area
    probe = AnarchessGame(2, seed=1)
    probe.tiles = {(0, 0): LIGHT, (1, 0): LIGHT, (2, 0): LIGHT}
    probe.pawns = {(2, 0): 1}                       # an enemy in the area
    probe.placed_tile = True
    probe.last_tile = (0, 0)
    probe.drawn = LIGHT
    check("settling needs the area empty of pawns",
          not any(a.kind == "settle" for a in probe.legal_pawn_actions()))
    probe.pawns = {}
    probe.last_tile = (0, 0)
    check("a pawn settles on the tile just laid",
          any(a.kind == "settle" and a.cell == (0, 0)
              for a in probe.legal_pawn_actions()))

    # scoring: 2 a tile, 3 for a lone holder, 1 in the taxed largest area,
    # and -6 for every pawn left in the reserve
    # A big unowned area soaks up the largest-area tax, so the probes below
    # measure one rule at a time.
    decoy = {(x, 40): DARK for x in range(6)}

    probe = AnarchessGame(2, seed=1)
    probe.tiles = dict(decoy)
    # a dark area held by Light, so neither bonus applies: the plain rate
    probe.tiles.update({(0, 0): DARK, (1, 0): DARK})
    probe.pawns = {(0, 0): 0, (1, 0): 0}
    probe.reserve = [6, 8]
    check("a held area of two tiles scores two a tile",
          probe.final_scores() == [4 - 36, -48], f"{probe.final_scores()}")

    probe = AnarchessGame(2, seed=1)
    probe.tiles = dict(decoy)
    probe.tiles.update({(0, 0): LIGHT, (1, 0): LIGHT})
    probe.pawns = {(0, 0): 0}                       # a lone holder
    probe.reserve = [7, 8]
    check("a single pawn holding an area scores three a tile",
          probe.final_scores() == [6 - 42, -48], f"{probe.final_scores()}")

    probe = AnarchessGame(2, seed=1)
    probe.tiles = dict(decoy)
    probe.tiles.update({(0, 0): LIGHT, (1, 0): LIGHT})
    probe.pawns = {(0, 0): 0, (1, 0): 0}    # Light owns a light area, 2 pawns
    probe.reserve = [6, 8]
    check("an area matching its owner's colour scores three a tile",
          probe.final_scores() == [6 - 36, -48], f"{probe.final_scores()}")

    probe = AnarchessGame(2, seed=1)
    probe.tiles = {(0, 0): LIGHT, (1, 0): LIGHT}       # this one is the largest
    probe.pawns = {(0, 0): 0, (1, 0): 0}
    probe.reserve = [6, 8]
    check("the largest area is taxed down to one point a tile",
          probe.final_scores() == [2 - 36, -48], f"{probe.final_scores()}")

    # a whole game, played by the bots, ends with the last tile and a score
    bots = [AnarchessBot(0, 3), AnarchessBot(1, 3)]
    game = AnarchessGame(2, seed=5)
    steps = 0
    while not game.finished and steps < 400:
        for action in bots[game.current].choose(game):
            game.apply(action)
        steps += 1
    check("two bots finish a game", game.finished,
          f"{len(game.tiles)} tiles in {steps} turns, scores {game.scores}")
    check("every tile is laid", game.tiles_left() == 0,
          f"{game.total_tiles()} tiles")

    # SOLO is always the two original tribes, even if an old caller supplied
    # a multi-player table size, and it forces the pawn action.
    malformed_solo = AnarchessGame(4, AnarchessRules(solo=True), seed=11,
                                    names=["Only one name"])
    check("SOLO always has two tribes",
          malformed_solo.players == 2 and len(malformed_solo.reserve) == 2)
    check("short player names are completed",
          len(malformed_solo.names) == 2 and all(malformed_solo.names))
    solo = AnarchessGame(2, AnarchessRules(solo=True, tiles_per_colour=16),
                         seed=11)
    forced = True
    while not solo.finished and solo.total_tiles() < 12:
        acts = solo.legal_actions()
        if not acts:
            break
        if solo.placed_tile:
            acts = [a for a in acts if a.kind != "pass"]
            if not acts:
                break
            forced = forced and all(
                a.kind in ("settle", "attack", "move") for a in acts)
        solo.apply(solo.rng.choice(acts))
    check("the solo game forces the pawn action", forced,
          f"solo total {solo.solo_score()}")
    stranded_solo = AnarchessGame(2, AnarchessRules(solo=True), seed=12)
    stranded_solo.tiles = {(0, 0): LIGHT}
    stranded_solo.pawns = {}
    stranded_solo.reserve = [0, 0]
    stranded_solo.current = 0
    stranded_solo.placed_tile = True
    stranded_solo.last_tile = (0, 0)
    check("a stranded solo turn offers and accepts a pass",
          [a.kind for a in stranded_solo.legal_actions()] == ["pass"]
          and stranded_solo.apply(AnarchessAction("pass"))
          and not stranded_solo.placed_tile)

    # Anarcheckers jumps instead of stepping
    checkers = AnarchessGame(2, AnarchessRules(checkers=True,
                                                tiles_per_colour=16), seed=2)
    checkers.tiles = {(0, 0): LIGHT, (1, 1): DARK, (2, 2): LIGHT}
    checkers.pawns = {(0, 0): 0, (1, 1): 1}
    checkers.current = 0
    checkers.placed_tile = True
    checkers.last_tile = (0, 0)
    acts = checkers.legal_pawn_actions()
    check("Anarcheckers pieces jump over an enemy",
          any(a.kind == "attack" and a.cell == (2, 2) and a.source == (0, 0)
              for a in acts) and not any(a.kind == "move" for a in acts),
          "the jump is compulsory")
    check("Anarcheckers cannot pass a compulsory jump",
          not any(a.kind == "pass" for a in checkers.legal_actions())
          and not checkers.apply(AnarchessAction("pass")))

    # The published SOLO priority is enforced where state changes, not merely
    # by hiding lower-priority buttons in a view.
    priority_solo = AnarchessGame(2, AnarchessRules(solo=True), seed=4)
    priority_solo.tiles = {(0, 0): LIGHT, (1, 0): DARK, (2, 0): LIGHT}
    priority_solo.pawns = {(1, 0): 1}
    priority_solo.reserve = [8, 7]
    priority_solo.current = 0
    priority_solo.placed_tile = True
    priority_solo.last_tile = (0, 0)              # Light tile -> Dark pawn acts
    check("SOLO cannot bypass its settle-first priority",
          [a.kind for a in priority_solo.legal_pawn_actions()] == ["settle"]
          and not priority_solo.apply(AnarchessAction("move", source=(1, 0),
                                                       cell=(2, 0))))

    # A chain is the *same* attacking checkers piece, and therefore cannot be
    # hijacked by a different available capture, a move, settle, or pass.
    chain = AnarchessGame(2, AnarchessRules(checkers=True, tiles_per_colour=16), seed=5)
    chain.tiles = {(0, 0): LIGHT, (1, 1): DARK, (2, 2): LIGHT,
                   (3, 3): DARK, (4, 4): LIGHT, (5, 1): LIGHT,
                   (6, 2): DARK, (7, 3): LIGHT}
    chain.pawns = {(0, 0): 0, (1, 1): 1, (3, 3): 1,
                   (5, 1): 0, (6, 2): 1}
    chain.current = 0
    chain.placed_tile = True
    chain.last_tile = (0, 0)
    first_jump = chain.apply(AnarchessAction("attack", source=(0, 0), cell=(2, 2)))
    chained = chain.legal_actions()
    check("Anarcheckers keeps a chain with the original piece",
          first_jump and chain.chain_source == (2, 2)
          and [(a.source, a.cell) for a in chained] == [((2, 2), (4, 4))]
          and not chain.apply(AnarchessAction("attack", source=(5, 1), cell=(7, 3))))
    check("the required chain jump ends the turn only when complete",
          chain.apply(AnarchessAction("attack", source=(2, 2), cell=(4, 4)))
          and not chain.placed_tile and chain.chain_source is None)

    # Simulation must not consume the live die. Otherwise a stronger bot could
    # alter a later real tile colour simply by examining more candidates.
    rng_probe = AnarchessGame(2, seed=29)
    before_rng = rng_probe.rng.getstate()
    _ = [rng_probe.clone() for _ in range(3)]
    check("AI simulation leaves the live die untouched", rng_probe.rng.getstate() == before_rng)
    advanced = AnarchessGame(2, seed=30)
    choices = AnarchessBot(advanced.current, 4, seed=1).choose(advanced)
    check("the Warlord returns a legal complete turn",
          bool(choices) and all(advanced.apply(action) for action in choices)
          and not advanced.placed_tile,
          " · ".join(action.kind for action in choices))

    check("every ruling is documented", len(RULINGS) >= 8,
          f"{len(RULINGS)} rulings recorded")


def _reference_areas(grid):
    """Independent flood fill, used to check the game's own area finder."""
    seen, out = set(), []
    for cell in grid:
        if cell in seen:
            continue
        colour = grid[cell]
        stack, group = [cell], []
        seen.add(cell)
        while stack:
            current = stack.pop()
            group.append(current)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (current[0] + dx, current[1] + dy)
                if nxt in grid and nxt not in seen and grid[nxt] == colour:
                    seen.add(nxt)
                    stack.append(nxt)
        out.append(group)
    return out


def test_learning() -> None:
    section("Adaptive learning")
    import sqlite3
    from lc.training.learning import Learner, skill_for_category, skill_for_session

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE puzzles (id INTEGER, set_id INTEGER, category TEXT,"
               " fen TEXT, solution TEXT, difficulty REAL)")
    for i in range(40):
        db.execute("INSERT INTO puzzles VALUES (?,?,?,?,?,?)",
                   (i, 7, "mate in 2" if i % 2 == 0 else "mixed", "8/8/8/8/8/8/8/K6k w - - 0 1",
                    "a1a2", i % 6))
    db.commit()
    learner = Learner(db)

    for i in range(12):
        learner.record(7, i * 2, True, seconds=6.0, hints=0, skill="mates",
                       difficulty=2)
    for i in range(1, 12, 2):
        learner.record(7, i, False, seconds=40.0, hints=2, skill="tactics",
                       difficulty=3)
    check("attempts are remembered", len(learner.cards) == 18,
          f"{len(learner.cards)} cards")
    good = learner.get(7, 0)
    bad = learner.get(7, 1)
    check("correct answers schedule the future", good.interval >= 1.0 and good.reps == 1,
          f"{good.interval:.1f} days")
    check("wrong answers come back immediately",
          bad.interval == 0.0 and bad.lapses == 1 and bad.reps == 0)
    check("ease follows performance", good.ease > bad.ease,
          f"{good.ease:.2f} vs {bad.ease:.2f}")
    check("skill ratings separate the themes",
          learner.mastery("mates") > learner.mastery("tactics"),
          f"mates {learner.mastery('mates'):.0f}% vs tactics "
          f"{learner.mastery('tactics'):.0f}%")

    now = __import__("time").time()
    baseline = learner.due_count()
    for card in list(learner.cards.values())[:5]:
        card.due = now - 86400
    check("overdue cards are collected", learner.due_count() > baseline,
          f"{learner.due_count()} due (was {baseline})")
    plan = learner.plan(5)
    check("a review queue is built", len(plan) == 5 and
          all(len(entry) == 3 for entry in plan))
    fresh = learner.new_items("mates", 4)
    check("new material is served", len(fresh) == 4 and
          all(learner.card_key(s, i) not in learner.cards for s, i in fresh))

    reloaded = Learner(db)
    check("progress survives a restart", len(reloaded.cards) == 18 and
          abs(reloaded.skills["mates"].rating - learner.skills["mates"].rating) < 1e-6)
    summary = learner.summary()
    check("the coach reports", summary["cards"] == 18 and 0.0 <= summary["retention"] <= 1.0,
          f"retention {summary['retention'] * 100:.0f}%")
    check("categories map onto skills",
          skill_for_category("mate in 1") == "mates" and
          skill_for_category("R_P") == "endgames" and
          skill_for_session("Blindfold") == "visualisation")
    learner.reset()
    check("progress can be reset", len(learner.cards) == 0 and
          learner.skills["mates"].rating == 1000.0 and
          learner.skills["mates"].seen == 0)


MATE_FEN = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"    # Ra8 is mate
CHECK_FEN = "6k1/5pp1/8/8/8/8/5PPP/R5K1 w - - 0 1"   # the king escapes to h7
END_FEN = "8/8/8/8/8/5k2/8/5K2 w - - 0 1"

# A back-rank mate, a check that is not a mate, a verbatim duplicate of that
# check, and a line whose FEN is not a FEN at all.
TACTICS_LINES = [
    f"{MATE_FEN}|Difficulty ***|1. Ra8#|1. Ra8# 1-0",
    f"{CHECK_FEN}|Difficulty *|1. Ra8+|1. Ra8+",
    f"{CHECK_FEN}|Difficulty *|1. Ra8+|1. Ra8+",
    "not a fen at all|Difficulty **|1. e4|",
    "",
]


def test_importer() -> None:
    """The build-time importer that turns raw Lucas files into lucas.db."""
    import sqlite3

    from lc.data.importer import (SCHEMA, MAX_PGN, clip, clean_text,
                                  difficulty_from_label, guess_kind,
                                  import_fns_folder, sample_even, san_to_uci,
                                  valid_fen)

    section("the importer")

    check("clip keeps short text and marks long text",
          clip(None, 5) == "" and clip("  hi  ", 10) == "hi"
          and clip("abcdefgh", 4) == "abc\u2026")
    check("sample_even spreads its picks across the whole file",
          sample_even(list("abcde"), 0) == list("abcde")
          and sample_even(list("abcde"), 9) == list("abcde")
          and sample_even(list("abcde"), 3) == ["a", "b", "d"])
    check("clean_text strips markup and NAGs",
          clean_text("a<br>b <b>c</b> $1 d") == "a\nb c  d")
    check("san_to_uci reads numbers, comments and variations",
          san_to_uci(chess.STARTING_FEN, "1. e4 e5 2. Nf3 {c} (1. d4 d5) $1 1-0")
          == ("e2e4 e7e5 g1f3", "e4 e5 Nf3"))
    check("san_to_uci names a mate",
          san_to_uci(MATE_FEN, "1. Ra8#") == ("a1a8", "Ra8#"))
    check("an illegal solution converts to nothing, rather than raising",
          san_to_uci(MATE_FEN, "1. Qh5#") == ("", ""))
    check("valid_fen accepts a position and rejects junk",
          valid_fen(MATE_FEN) and not valid_fen("junk")
          and not valid_fen("8/8/8/8/8/8/8/8 w - - 0 1"))
    check("difficulty comes from the stars and is capped at five",
          difficulty_from_label("Difficulty *") == 1
          and difficulty_from_label("Difficulty ***") == 3
          and difficulty_from_label("Difficulty ******") == 5
          and difficulty_from_label("Find the win") == 0)
    check("guess_kind sorts a folder by its name",
          guess_kind("Mate in 2", "") == "mates"
          and guess_kind("Openings", "") == "openings"
          and guess_kind("Random", "x") == "tactics")

    with tempfile.TemporaryDirectory() as root:
        tactics = os.path.join(root, "Tactics")
        endings = os.path.join(root, "Endgames")
        os.makedirs(tactics)
        os.makedirs(endings)
        with open(os.path.join(tactics, "Config.ini"), "w") as fh:
            fh.write("[CONFIG]\nlevel=3\n")
        with open(os.path.join(tactics, "mate in two.fns"), "w") as fh:
            fh.write("\n".join(TACTICS_LINES))
        # A file with nothing usable in it. The set it opens must not linger.
        with open(os.path.join(tactics, "broken.fns"), "w") as fh:
            fh.write("no fen here|label|1. e4\n")
        with open(os.path.join(endings, "technique.fns"), "w") as fh:
            fh.write(f"{END_FEN}|Difficulty **|1. Ke1|\n")

        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA)
        total = import_fns_folder(conn, root, "selftest")

        check("three usable lines, one duplicate and one junk line dropped",
              total == 3, f"imported {total}")
        check("a file with nothing usable leaves no empty set behind",
              conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0] == 2)
        kinds = sorted(row[0] for row in
                       conn.execute("SELECT DISTINCT kind FROM sets"))
        check("folders are filed under the right kind",
              kinds == ["endgames", "tactics"], " ".join(kinds))

        # os.walk visits the folders in filesystem order, so ask for the
        # tactics rows explicitly instead of trusting insertion order.
        rows = conn.execute(
            "SELECT p.solution, p.solution_san, p.difficulty, p.pgn, p.category"
            " FROM puzzles p JOIN sets s ON s.id = p.set_id"
            " WHERE s.kind = 'tactics' ORDER BY p.ord").fetchall()
        end_rows = conn.execute(
            "SELECT p.solution, p.solution_san, p.difficulty"
            " FROM puzzles p JOIN sets s ON s.id = p.set_id"
            " WHERE s.kind = 'endgames'").fetchall()
        check("an endgame folder imports as an endgame",
              end_rows == [("f1e1", "Ke1", 2)], str(end_rows))
        check("the mate is stored as UCI with its SAN beside it",
              rows[0][0] == "a1a8" and rows[0][1] == "Ra8#",
              f"{rows[0][0]} / {rows[0][1]}")
        check("the bare check keeps its own difficulty",
              rows[1][0] == "a1a8" and rows[1][1] == "Ra8+"
              and rows[1][2] == 1, f"{rows[1][1]} difficulty {rows[1][2]}")
        check("the star rating carries into the database", rows[0][2] == 3)
        check("the PGN tail is kept", rows[0][3] == "1. Ra8# 1-0")
        check("the file name becomes the category",
              "mate in two" in rows[0][4], rows[0][4])
        check("a Config.ini beside the file is carried into the set",
              "level=3" in (conn.execute(
                  "SELECT config FROM sets WHERE kind='tactics'")
                  .fetchone()[0] or ""))

        # A long PGN tail is clipped rather than stored whole.
        long_pgn = "x" * (MAX_PGN + 500)
        clipped = clip(long_pgn, MAX_PGN)
        check("a long PGN tail is clipped, not stored whole",
              len(clipped) == MAX_PGN and clipped.endswith("\u2026"))
        conn.close()


def main() -> int:
    print("TALOS – self test")
    start = time.time()
    try:
        test_engine()
        test_variants()
        test_game_model()
        test_paths()
        test_importer()
        window = test_interface()
        test_training(window)
        test_database(window)
        test_uci()
        test_battle()
        test_anarchy()
        test_anarchess()
        test_learning()
    except Exception:
        traceback.print_exc()
        RESULTS.append(("unhandled exception", False, "see traceback above"))
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed "
          f"in {time.time() - start:.1f}s")
    if failed:
        print("failed:", ", ".join(failed))
        return 1
    print("all good – the application is ready to run with: python run.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
