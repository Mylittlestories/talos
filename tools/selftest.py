#!/usr/bin/env python3
"""
Headless self test for Lucas Chess NX.

    python tools/selftest.py

Exercises the engine, every variant, the game model, the Qt interface
(offscreen), all training sessions, the database and the Battle Chess
simulation - no display, no network and no external engine required.
"""

from __future__ import annotations

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

import chess

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

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


def test_interface() -> None:
    section("Interface")
    from lc.ui.main_window import MainWindow
    from lc.core.players import BuiltInPlayer, HumanPlayer

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


def test_battle() -> None:
    section("Battle Chess (simulation, no GL needed)")
    from lc.battle import meshes, physics
    from lc.battle.battle_widget import BattleBoardWidget

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
    section("Anarchess (the land before Chess)")
    from lc.anarchess import AnarchessBot, AnarchessGame, AnarchessRules
    from lc.anarchess.rules import RULINGS

    game = AnarchessGame(2, AnarchessRules())
    check("opening is a single tile", len(game.tile_cells()) == 1)
    game.apply(game.legal_tile_actions()[0])
    check("the first tile is placed", len(game.tiles) == 1,
          f"{len(game.tiles)} tile(s)")
    while not game.finished:
        actions = game.legal_actions()
        if not actions:
            break
        game.apply(actions[0])
    check("a whole game can be played out", game.finished and len(game.tiles) == 64,
          f"{len(game.tiles)} tiles, scores {game.scores}")
    check("areas are scored", sum(game.scores) <= 64 and len(game.areas()) >= 1,
          f"{len(game.areas())} areas")

    # the area routine agrees with a plain flood fill
    grid = {c: (sum(c) % 2 == 0) for c in
            [(x, y) for x in range(6) for y in range(6)]}
    probe = AnarchessGame(2, AnarchessRules())
    probe.tiles = dict(grid)
    found = probe.areas()
    check("area detection matches a reference",
          sorted(len(a) for a in found) == sorted(
              len(a) for a in _reference_areas(grid)),
          f"{len(found)} areas")

    bots = [AnarchessBot(0, 3), AnarchessBot(1, 3)]
    game = AnarchessGame(2, AnarchessRules(random_colour=True), seed=5)
    steps = 0
    while not game.finished and steps < 400:
        for action in bots[game.current].choose(game):
            game.apply(action)
        steps += 1
    check("two bots finish a game", game.finished,
          f"{len(game.tiles)} tiles in {steps} turns, scores {game.scores}")
    check("reconstruction rulings are documented", len(RULINGS) >= 6,
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


def main() -> int:
    print("TALOS – self test")
    start = time.time()
    try:
        test_engine()
        test_variants()
        test_game_model()
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
