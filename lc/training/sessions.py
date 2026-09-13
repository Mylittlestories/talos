"""
Training sessions.

Every mode is a small state machine that the controller drives:

    session.start_task()      -> Task(fen, solution, label, ...)
    session.validate(move)    -> Feedback(ok, message, done, reply_move)
    session.hint()            -> Hint(arrows, markers, squares, text)
    session.finish(result)    -> records progress in the database

The Lucas Chess training philosophy is kept: every task has a goal, help is
available in several grades, mistakes cost points and progress persists.
"""

from __future__ import annotations

import random
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import chess

from PyQt6.QtCore import QObject, pyqtSignal

from ..core.game import Game
from ..ui.board_view import Arrow, Marker
from .learning import skill_for_category, skill_for_session


# --------------------------------------------------------------------------
# data objects
# --------------------------------------------------------------------------

@dataclass
class Task:
    fen: str
    solution: List[chess.Move] = field(default_factory=list)
    label: str = ""
    item_id: int = 0
    kind: str = "solve"
    meta: Dict = field(default_factory=dict)
    side: chess.Color = chess.WHITE


@dataclass
class Feedback:
    ok: bool
    message: str = ""
    done: bool = False
    reply: Optional[chess.Move] = None
    points: int = 0
    solved: bool = False


@dataclass
class Hint:
    arrows: List[Arrow] = field(default_factory=list)
    markers: List[Marker] = field(default_factory=list)
    squares: List[chess.Square] = field(default_factory=list)
    text: str = ""


# --------------------------------------------------------------------------
# base
# --------------------------------------------------------------------------

class Session(QObject):
    taskChanged = pyqtSignal(object)
    message = pyqtSignal(str)
    finished = pyqtSignal(object)        # dict summary
    progressChanged = pyqtSignal(int, int)

    name = "Training"
    help_levels = ("Show the piece to move", "Show the target square", "Show the move")

    def __init__(self, db: sqlite3.Connection, set_id: Optional[int] = None,
                 parent=None, rng_seed: Optional[int] = None):
        super().__init__(parent)
        self.db = db
        self.set_id = set_id
        self.rng = random.Random(rng_seed)
        self.task: Optional[Task] = None
        self.index = 0
        self.points = 0
        self.solved = 0
        self.failed = 0
        self.streak = 0
        self.history: List[int] = []
        self.hints_used = 0
        self.task_hints = 0
        self.task_started = time.time()
        self._last_task = None
        self.learner = None          # set by the main window
        self.started_at = time.time()

    # -- persistence ------------------------------------------------------
    def begin_task(self) -> None:
        """Start the clock for the task that is about to be shown."""
        self.task_hints = 0
        self.task_started = time.time()

    def skill_and_difficulty(self, item_id: int):
        """Which theme does this drill belong to, and how hard is it?"""
        if self.set_id:
            try:
                row = self.db.execute(
                    "SELECT category, difficulty FROM puzzles"
                    " WHERE id=? AND set_id=?", (item_id, self.set_id)).fetchone()
                if row is not None:
                    return skill_for_category(row[0]), float(row[1] or 2.0)
            except Exception:
                pass
        meta = getattr(self.task, "meta", None) or {}
        return skill_for_session(self.name), float(meta.get("difficulty", 2.0) or 2.0)

    def record(self, item_id: int, solved: bool, points: int = 0) -> None:
        try:
            self.db.execute(
                "INSERT INTO progress(set_id, item_id, seen, solved, failed, points, last_ms)"
                " VALUES(?,?,1,?,?,?,?)"
                " ON CONFLICT(set_id, item_id) DO UPDATE SET"
                " seen=seen+1, solved=solved+excluded.solved,"
                " failed=failed+excluded.failed, points=points+excluded.points,"
                " last_ms=excluded.last_ms",
                (self.set_id or 0, item_id, 1 if solved else 0, 0 if solved else 1,
                 points, int(time.time() * 1000)))
            self.db.commit()
        except Exception:
            pass
        # ---- the adaptive layer -----------------------------------------
        learner = getattr(self, "learner", None)
        if learner is None:
            return
        try:
            skill, difficulty = self.skill_and_difficulty(item_id)
            seconds = max(0.0, time.time() - self.task_started)
            learner.record(self.set_id or 0, item_id, solved, seconds=seconds,
                           hints=self.task_hints, skill=skill,
                           difficulty=difficulty)
        except Exception:
            pass

    # -- to implement ------------------------------------------------------
    def start_task(self) -> Optional[Task]:
        self.begin_task()
        raise NotImplementedError

    def validate(self, board: chess.Board, move: chess.Move) -> Feedback:
        raise NotImplementedError

    def hint(self, board: chess.Board) -> Hint:
        return Hint()

    def summary(self) -> Dict:
        return {"mode": self.name, "points": self.points, "solved": self.solved,
                "failed": self.failed, "hints": self.hints_used,
                "seconds": int(time.time() - self.started_at)}

    def finish(self) -> Dict:
        out = self.summary()
        self.finished.emit(out)
        return out


# --------------------------------------------------------------------------
# solve-the-line sessions
# --------------------------------------------------------------------------

class SolveSession(Session):
    """Play the solution line: tactics, mates, STS, guess-the-move, endings."""

    name = "Tactics"
    PTS = 10

    def __init__(self, db, set_id=None, parent=None, kind: str = "tactics",
                 limit: int = 100, rng_seed=None, shuffle: bool = True):
        super().__init__(db, set_id, parent, rng_seed)
        self.kind = kind
        rows = db.execute(
            "SELECT id, fen, solution, solution_san, label, difficulty FROM puzzles"
            " WHERE set_id=? AND solution<>'' ORDER BY ord", (set_id,)).fetchall()
        self.rows = [r for r in rows if r[2]]
        if shuffle:
            self.rng.shuffle(self.rows)
        self.rows = self.rows[:limit or len(self.rows)]
        self.queue: List[sqlite3.Row] = list(self.rows)
        self.cursor = 0
        self.attempts = 0
        self._counted_failure = False

    # -- tasks -------------------------------------------------------------
    def _next_row(self):
        if not self.queue:
            return None
        row = self.queue.pop(0)
        self.cursor += 1
        return row

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        row = self._next_row()
        if row is None:
            self.task = None
            return None
        item_id, fen, solution, san, label, difficulty = row
        moves = [chess.Move.from_uci(u) for u in solution.split() if u]
        task = Task(fen=fen, solution=moves, label=label or "", item_id=item_id,
                    kind=self.kind, meta={"san": san or "", "difficulty": difficulty or 0})
        self.task = task
        self.index = 0
        self.attempts = 0
        self._counted_failure = False
        self.taskChanged.emit(task)
        return task

    def validate(self, board: chess.Board, move: chess.Move) -> Feedback:
        task = self.task
        if task is None:
            return Feedback(False, "No active task")
        expected = task.solution[self.index] if self.index < len(task.solution) else None
        if expected is None:
            return Feedback(True, "Done", done=True, solved=True)
        if move != expected:
            self.attempts += 1
            self.failed += 1
            self.streak = 0
            if not self._counted_failure:
                # tell the learning model once, so the card comes back soon
                self._counted_failure = True
                self.task_hints = max(self.task_hints, 1)
                self.record(task.item_id, False, 0)
            message = "That is not the move."
            if self.attempts >= 2:
                message += f"  Solution: {task.meta.get('san', '')}"
            return Feedback(False, message, done=False, points=-2)
        # correct
        self.index += 1
        if self.index >= len(task.solution):
            gained = max(2, self.PTS - self.attempts * 3 - self.hints_used * 2)
            self.points += gained
            self.solved += 1
            self.streak += 1
            self.record(task.item_id, True, gained)
            return Feedback(True, f"Correct!  +{gained} points", done=True,
                            points=gained, solved=True)
        # the opponent answers with the next move of the line
        reply = task.solution[self.index]
        self.index += 1
        return Feedback(True, "Good move, continue.", done=False, reply=reply)

    def hint(self, board: chess.Board) -> Hint:
        task = self.task
        if task is None or self.index >= len(task.solution):
            return Hint()
        move = task.solution[self.index]
        self.hints_used += 1
        self.task_hints += 1
        level = min(2, self.hints_used - 1)
        if level == 0:
            return Hint(markers=[Marker(move.from_square, "circle", "#f6f06a")],
                        text="This piece has to move.")
        if level == 1:
            return Hint(markers=[Marker(move.from_square, "circle", "#f6f06a"),
                                 Marker(move.to_square, "square", "#4aa3ff")],
                        text="This is the destination square.")
        return Hint(arrows=[Arrow(move.from_square, move.to_square, "#f6f06a")],
                    squares=[move.from_square, move.to_square],
                    text=f"Play {board.san(move)}.")


class STSSession(SolveSession):
    """Strategic Test Suite: every candidate move scores points."""

    name = "STS"
    PTS = 10

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        task = super().start_task()
        if task is not None:
            task.kind = "sts"
        return task

    def _parse_candidates(self, label: str) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for chunk in label.split(":")[-1].split(","):
            if "=" in chunk:
                mv, _, pts = chunk.partition("=")
                try:
                    out[mv.strip()] = int(pts.strip())
                except Exception:
                    pass
        return out

    def validate(self, board: chess.Board, move: chess.Move) -> Feedback:
        task = self.task
        if task is None:
            return Feedback(False, "")
        cands = self._parse_candidates(task.label)
        best = task.solution[0] if task.solution else None
        gained = cands.get(move.uci(), 0)
        if best is not None and move == best:
            gained = max(gained, self.PTS)
        self.points += gained
        if gained >= self.PTS:
            self.solved += 1
            self.streak += 1
            txt = f"Best move: +{gained} points"
        elif gained > 0:
            self.streak = 0
            self.solved += 1
            txt = f"Good: +{gained} points"
        else:
            self.failed += 1
            self.streak = 0
            txt = "0 points"
        self.record(task.item_id, gained > 0, gained)
        best_san = board.san(best) if best and best in board.legal_moves else ""
        return Feedback(gained > 0, txt + (f" (best: {best_san})" if best_san else ""),
                        done=True, points=gained, solved=gained > 0)


# --------------------------------------------------------------------------
# free play sessions (endgames, everest, resistance, elo)
# --------------------------------------------------------------------------

class PlaySession(Session):
    """Play a position out against the engine; the goal decides success."""

    name = "Endgame play"
    LEVELS = ["Club", "Club+", "Expert", "Expert+", "Master"]

    def __init__(self, db, set_id=None, parent=None, goal: str = "win",
                 fen: Optional[str] = None, side: Optional[chess.Color] = None,
                 rows: Optional[List] = None, rng_seed=None):
        super().__init__(db, set_id, parent, rng_seed)
        self.goal = goal                  # win | draw | survive
        self.fen = fen
        self.side = side
        self.rows = list(rows or [])
        self.level_index = 0
        self.moves_played = 0
        self.losses: List[int] = []
        self.rating_estimate: Optional[int] = None

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        fen = self.fen
        if fen is None:
            while self.rows:
                row = self.rows.pop(0)
                candidate = row if isinstance(row, str) else (row[0] if row else "")
                try:
                    chess.Board(candidate)
                except Exception:
                    continue
                fen = candidate
                break
        if fen is None:
            return None
        try:
            board = chess.Board(fen)
        except Exception:
            return None
        self.side = self.side if self.side is not None else board.turn
        task = Task(fen=fen, solution=[], label=self.label_for(board), kind="play",
                    side=self.side,
                    meta={"goal": self.goal, "level": self.LEVELS[self.level_index]})
        self.task = task
        self.moves_played = 0
        self.taskChanged.emit(task)
        return task

    def label_for(self, board: chess.Board) -> str:
        return f"Play this position - goal: {self.goal}."

    def validate(self, board: chess.Board, move: chess.Move) -> Feedback:
        self.moves_played += 1
        return Feedback(True, "", done=False)

    def evaluate_result(self, game) -> Tuple[bool, str]:
        """Called when the game ends: did the user reach the goal?"""
        if game.result is None:
            return False, ""
        user_is_white = self.side == chess.WHITE
        won = (game.result == "1-0" and user_is_white) or (game.result == "0-1" and not user_is_white)
        drew = game.result == "1/2-1/2"
        if self.goal == "win":
            ok = won
        elif self.goal == "draw":
            ok = won or drew
        else:
            ok = not (not won and not drew) or True     # survive = always continue
        msg = "Well done!" if ok else "Not this time."
        if ok:
            self.solved += 1
            self.points += 25
        else:
            self.failed += 1
        return ok, msg

    def bump_level(self) -> str:
        self.level_index = min(len(self.LEVELS) - 1, self.level_index + 1)
        return self.LEVELS[self.level_index]


class EndgameSession(PlaySession):
    name = "Endings"

    def __init__(self, db, set_id=None, parent=None, limit: int = 40, rng_seed=None):
        rows = db.execute("SELECT fen FROM puzzles WHERE set_id=? ORDER BY ord",
                          (set_id,)).fetchall()
        rows = [r[0] for r in rows]
        random.Random(rng_seed).shuffle(rows)
        super().__init__(db, set_id, parent, goal="win", rows=rows[:limit], rng_seed=rng_seed)

    def label_for(self, board: chess.Board) -> str:
        material = "".join(sorted(p.symbol() for p in board.piece_map().values()))
        return f"Endgame drill ({material}) - try to win it."

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        task = super().start_task()
        if task is not None:
            board = chess.Board(task.fen)
            # the side with more material is usually the one who must win
            w = sum(v for p in board.pieces(chess.QUEEN, chess.WHITE) for v in [9]) + \
                sum(5 for _ in board.pieces(chess.ROOK, chess.WHITE)) + \
                sum(3 for _ in board.pieces(chess.BISHOP, chess.WHITE)) + \
                sum(3 for _ in board.pieces(chess.KNIGHT, chess.WHITE)) + \
                sum(1 for _ in board.pieces(chess.PAWN, chess.WHITE))
            b = sum(9 for _ in board.pieces(chess.QUEEN, chess.BLACK)) + \
                sum(5 for _ in board.pieces(chess.ROOK, chess.BLACK)) + \
                sum(3 for _ in board.pieces(chess.BISHOP, chess.BLACK)) + \
                sum(3 for _ in board.pieces(chess.KNIGHT, chess.BLACK)) + \
                sum(1 for _ in board.pieces(chess.PAWN, chess.BLACK))
            self.side = chess.WHITE if w >= b else chess.BLACK
            task.side = self.side
            task.label = self.label_for(board)
            task.meta["goal"] = "win"
        return task


class EverestSession(PlaySession):
    """Climb a ladder of positions taken from real games, each rung harder."""

    name = "Everest"

    def __init__(self, db, parent=None, rng_seed=None):
        rows = db.execute(
            "SELECT fen, moves, white, black, event, result, white_elo, black_elo"
            " FROM games WHERE ply>24"
            " ORDER BY (white_elo+black_elo)/2 DESC LIMIT 400").fetchall()
        if not rows:
            rows = db.execute(
                "SELECT fen, moves, white, black, event, result, white_elo, black_elo"
                " FROM games WHERE ply>16 LIMIT 400").fetchall()
        super().__init__(db, None, parent, goal="win", rows=[], rng_seed=rng_seed)
        self.game_rows = list(rows)
        self.rng.shuffle(self.game_rows)
        self.rung = 0

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        if not self.game_rows:
            return None
        row = self.game_rows.pop(0)
        moves = row[1].split()
        ply = self.rng.randint(8, max(10, min(len(moves) - 2, 24)))
        board = chess.Board()
        for u in moves[:ply]:
            try:
                board.push(chess.Move.from_uci(u))
            except Exception:
                break
        self.rung += 1
        self.side = board.turn
        task = Task(fen=board.fen(), label=f"Rung {self.rung} - win the position "
                                           f"({row[2] or '?'} vs {row[3] or '?'}, {row[4] or ''})",
                    kind="play", side=self.side, meta={"goal": "win", "rung": self.rung})
        self.task = task
        self.taskChanged.emit(task)
        return task

    def evaluate_result(self, game) -> Tuple[bool, str]:
        ok, msg = super().evaluate_result(game)
        if ok:
            self.points += 50 + self.rung * 10
            msg = f"Rung {self.rung} cleared!  ({self.points} points)"
        else:
            msg = f"You fell at rung {self.rung}. Final score: {self.points}"
        return ok, msg


class ResistanceSession(PlaySession):
    """Survive: the engine gets stronger every few moves."""

    name = "Resistance"

    def __init__(self, db, set_id=None, parent=None, rng_seed=None):
        super().__init__(db, set_id, parent, goal="survive", fen=chess.STARTING_FEN,
                         rng_seed=rng_seed)
        self.round = 0

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        self.round += 1
        self.side = chess.WHITE if self.round % 2 else chess.BLACK
        task = Task(fen=chess.STARTING_FEN,
                    label=f"Round {self.round}: resist as long as you can "
                          f"(engine: {self.LEVELS[self.level_index]})",
                    kind="play", side=self.side,
                    meta={"goal": "survive", "level": self.LEVELS[self.level_index]})
        self.task = task
        self.taskChanged.emit(task)
        return task

    def evaluate_result(self, game) -> Tuple[bool, str]:
        self.round += 0
        survived = self.moves_played // 2
        if game.result and game.result != "1/2-1/2":
            user_lost = ((game.result == "0-1") == (self.side == chess.WHITE))
            if user_lost:
                self.failed += 1
                return False, (f"You survived {survived} moves against "
                               f"{self.LEVELS[self.level_index]}.")
        self.solved += 1
        self.points += 30 + survived * 2
        if self.moves_played >= 20:
            self.bump_level()
        return True, f"Round survived: {survived} moves, level now {self.LEVELS[self.level_index]}."


class MicEloSession(PlaySession):
    """Estimate your Elo from the average centipawn loss of your moves."""

    name = "Your Elo"

    def __init__(self, db, set_id=None, parent=None, rng_seed=None):
        super().__init__(db, set_id, parent, goal="survive", fen=chess.STARTING_FEN,
                         rng_seed=rng_seed)
        self.losses = []
        self.rating_estimate = None
        self.games_played = 0

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        self.side = chess.WHITE if self.games_played % 2 == 0 else chess.BLACK
        task = Task(fen=chess.STARTING_FEN,
                    label="Play a game: your rating will be estimated from the "
                          "quality of your moves (engine: Expert).",
                    kind="play", side=self.side, meta={"goal": "survive",
                                                       "level": "Expert"})
        self.task = task
        self.taskChanged.emit(task)
        return task

    def add_loss(self, centipawns: int) -> None:
        self.losses.append(max(0, centipawns))

    def estimate(self) -> int:
        if not self.losses:
            return 1500
        acl = sum(self.losses) / len(self.losses)
        # empirical mapping from average centipawn loss to playing strength
        table = [(0, 2700), (10, 2400), (20, 2200), (35, 2000), (55, 1850),
                 (80, 1700), (120, 1550), (180, 1400), (260, 1250), (400, 1050),
                 (700, 800)]
        for (loss, elo) in table:
            if acl <= loss:
                return elo
        return 800

    def evaluate_result(self, game) -> Tuple[bool, str]:
        self.games_played += 1
        rating = self.estimate()
        self.rating_estimate = rating
        self.points = rating
        return True, (f"Estimated strength: about {rating} Elo "
                      f"({len(self.losses)} moves analysed, "
                      f"average loss {sum(self.losses) / max(1, len(self.losses)):.0f} cp).")


class BlindfoldSession(PlaySession):
    name = "Blindfold"

    def __init__(self, db, set_id=None, parent=None, level: int = 3, rng_seed=None):
        super().__init__(db, None, parent, goal="win", fen=chess.STARTING_FEN,
                         rng_seed=rng_seed)
        self.level = level      # number of moves the board stays visible

    def label_for(self, board: chess.Board) -> str:
        return (f"Blindfold: the board is hidden after {self.level} of your moves. "
                f"Keep the position in your head.")

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        self.side = chess.WHITE
        task = Task(fen=chess.STARTING_FEN, label=self.label_for(chess.Board()),
                    kind="play", side=chess.WHITE,
                    meta={"goal": "win", "level": "Club", "blindfold": self.level})
        self.task = task
        self.taskChanged.emit(task)
        return task


# --------------------------------------------------------------------------
# book / guess sessions
# --------------------------------------------------------------------------

class OpeningSession(Session):
    """Opening trainer: play the moves that master practice knows."""

    name = "Openings"

    def __init__(self, db, set_id=None, parent=None, rng_seed=None,
                 eco: Optional[str] = None):
        super().__init__(db, set_id, parent, rng_seed)
        sql = "SELECT moves FROM games WHERE ply>16"
        args: Tuple = ()
        if eco:
            sql += " AND eco=?"
            args = (eco,)
        sql += " LIMIT 4000"
        rows = db.execute(sql, args).fetchall()
        self.book: Dict[str, Dict[str, int]] = {}
        self._positions: Dict[str, str] = {}
        for (moves,) in rows:
            board = chess.Board()
            for u in moves.split():
                try:
                    mv = chess.Move.from_uci(u)
                except Exception:
                    break
                if mv not in board.legal_moves:
                    break
                key = str(board._transposition_key())
                self.book.setdefault(key, {}).setdefault(u, 0)
                self.book[key][u] += 1
                self._positions[key] = board.fen()
                board.push(mv)
                if board.fullmove_number > 14:
                    break
        self.keys = [k for k in self.book if sum(self.book[k].values()) >= 2]
        self.rng.shuffle(self.keys)

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        board = chess.Board()
        while self.keys:
            key = self.keys.pop()
            fen = self._positions.get(key)
            if fen is None:
                continue
            try:
                board = chess.Board(fen)
            except Exception:
                continue
            if board.is_game_over():
                continue
            task = Task(fen=board.fen(),
                        label="Play a strong opening move (the panel tells you how "
                              "often each move is played in master practice).",
                        kind="opening", side=board.turn,
                        meta={"book": self._book_for(board)})
            self.task = task
            self.taskChanged.emit(task)
            return task
        return None

    def _find_position(self, key: str) -> Optional[chess.Board]:
        fen = self._positions.get(key)
        if fen is None:
            return None
        try:
            return chess.Board(fen)
        except Exception:
            return None

    def _book_for(self, board: chess.Board) -> Dict[str, int]:
        key = str(board._transposition_key())
        return self.book.get(key, {})

    def validate(self, board: chess.Board, move: chess.Move) -> Feedback:
        book = self._book_for(board)
        total = sum(book.values()) or 1
        played = book.get(move.uci(), 0)
        if not book:
            self.points += 5
            return Feedback(True, "Out of book - free play from here.", done=True,
                            points=5, solved=True)
        pct = played / total * 100
        top = max(book.items(), key=lambda kv: kv[1])
        try:
            top_move = chess.Move.from_uci(top[0])
            top_san = board.san(top_move) if top_move in board.legal_moves else top[0]
        except Exception:
            top_san = top[0]
        if played:
            gained = max(2, int(10 * pct / 100) + 2)
            self.points += gained
            self.solved += 1
            return Feedback(True, f"{top_san} is the main move; your move appears in "
                                  f"{pct:.0f}% of the games.  +{gained}",
                            done=True, points=gained, solved=True)
        self.failed += 1
        return Feedback(False, f"Not in the book.  Most played: {top_san}.", done=True,
                        solved=False)

    def hint(self, board: chess.Board) -> Hint:
        book = self._book_for(board)
        if not book:
            return Hint()
        top = max(book.items(), key=lambda kv: kv[1])
        try:
            mv = chess.Move.from_uci(top[0])
        except Exception:
            return Hint()
        return Hint(arrows=[Arrow(mv.from_square, mv.to_square, "#4aa3ff")],
                    text=f"Main line: {board.san(mv)}")


class GuessSession(SolveSession):
    """Guess the move that was played in a real game (Lucas' BMT / albums)."""

    name = "Guess the move"
    PTS = 10

    def __init__(self, db, set_id=None, parent=None, rng_seed=None, elo_min: int = 2200):
        rows = db.execute(
            "SELECT moves, white, black, event, white_elo, black_elo, eco FROM games"
            " WHERE ply>24 ORDER BY RANDOM() LIMIT 500").fetchall()
        self.games = [r for r in rows]
        super().__init__(db, None, parent, kind="guess", rng_seed=rng_seed, shuffle=False)
        self.rows = []
        self.queue = []
        self.rng.shuffle(self.games)

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        while self.games:
            row = self.games.pop()
            moves = row[0].split()
            ply = self.rng.randint(10, max(12, min(len(moves) - 2, 30)))
            board = chess.Board()
            ok = True
            for u in moves[:ply]:
                try:
                    board.push(chess.Move.from_uci(u))
                except Exception:
                    ok = False
                    break
            if not ok:
                continue
            try:
                continuations = [chess.Move.from_uci(u) for u in moves[ply:ply + 3]]
            except Exception:
                continue
            if not continuations:
                continue
            label = f"{row[3] or 'Game'}: {row[1] or '?'} vs {row[2] or '?'}, move {ply // 2 + 1}"
            task = Task(fen=board.fen(), solution=continuations[:1], label=label,
                        kind="guess", meta={"next": [m.uci() for m in continuations[:3]]})
            self.task = task
            self.index = 0
            self.attempts = 0
            self.taskChanged.emit(task)
            return task
        return None


# --------------------------------------------------------------------------
# click based sessions (squares, routes, memory)
# --------------------------------------------------------------------------

class SquaresSession(Session):
    """Memorise a set of squares and click them back."""

    name = "Turn on the lights"

    def __init__(self, db, set_id=None, parent=None, count: int = 5, rng_seed=None):
        super().__init__(db, None, parent, rng_seed)
        self.count = count
        self.target: List[chess.Square] = []
        self.clicked: List[chess.Square] = []
        self.phase = "show"

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        self.target = self.rng.sample(list(chess.SQUARES), self.count)
        self.clicked = []
        self.phase = "show"
        task = Task(fen=chess.STARTING_FEN, label=f"Memorise the {self.count} highlighted "
                                                  f"squares, then click them.",
                    kind="squares", meta={"squares": list(self.target), "phase": "show"})
        self.task = task
        self.taskChanged.emit(task)
        return task

    def squares_to_show(self) -> List[chess.Square]:
        return self.target if self.phase == "show" else []

    def hide(self) -> None:
        self.phase = "guess"
        if self.task:
            self.task.meta["phase"] = "guess"

    def click(self, square: chess.Square) -> Feedback:
        if self.phase != "guess":
            return Feedback(False, "Wait until the squares are hidden.")
        if square in self.clicked:
            return Feedback(False, "Already clicked.")
        if square == self.target[len(self.clicked)]:
            self.clicked.append(square)
            if len(self.clicked) == len(self.target):
                self.points += 10
                self.solved += 1
                self.record(0, True, 10)
                return Feedback(True, "Perfect!", done=True, points=10, solved=True)
            return Feedback(True, f"{len(self.clicked)}/{len(self.target)}")
        self.failed += 1
        self.streak = 0
        expected = chess.square_name(self.target[len(self.clicked)])
        return Feedback(False, f"No - the next square was {expected}.", done=True)

    def hint(self, board=None) -> Hint:
        if self.phase != "guess" or len(self.clicked) >= len(self.target):
            return Hint()
        return Hint(markers=[Marker(self.target[len(self.clicked)], "circle", "#f6f06a")],
                    text=chess.square_name(self.target[len(self.clicked)]))


class RouteSession(Session):
    """Guide a piece from one square to another across the board."""

    name = "Routes"

    PIECES = {chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook",
              chess.QUEEN: "queen", chess.KING: "king"}

    def __init__(self, db, set_id=None, parent=None, piece: int = chess.KNIGHT,
                 rng_seed=None):
        super().__init__(db, None, parent, rng_seed)
        self.piece = piece
        self.start: Optional[chess.Square] = None
        self.goal: Optional[chess.Square] = None
        self.current: Optional[chess.Square] = None
        self.steps = 0
        self.best = 0

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        squares = list(chess.SQUARES)
        self.start = self.rng.choice(squares)
        self.goal = self.rng.choice([s for s in squares if s != self.start])
        self.current = self.start
        self.steps = 0
        self.best = self._distance(self.start, self.goal)
        board = chess.Board(None)
        board.set_piece_at(self.start, chess.Piece(self.piece, chess.WHITE))
        board.set_piece_at(self.goal, chess.Piece(chess.PAWN, chess.BLACK))
        board.turn = chess.WHITE
        task = Task(fen=board.fen(), kind="routes",
                    label=f"Move the {self.PIECES[self.piece]} from "
                          f"{chess.square_name(self.start)} to {chess.square_name(self.goal)} "
                          f"in as few moves as you can (best: {self.best}).",
                    meta={"start": self.start, "goal": self.goal, "piece": self.piece,
                          "current": self.start, "steps": 0, "best": self.best})
        self.task = task
        self.taskChanged.emit(task)
        return task

    def _distance(self, a: chess.Square, b: chess.Square) -> int:
        """Breadth first search: how many moves does the piece need?"""
        import collections
        probe = chess.Board(None)
        probe.turn = chess.WHITE

        def moves_from(square: chess.Square):
            probe.clear()
            probe.set_piece_at(square, chess.Piece(self.piece, chess.WHITE))
            return list(probe.attacks(square))

        seen = {a: 0}
        queue = collections.deque([a])
        while queue:
            sq = queue.popleft()
            if sq == b:
                return seen[sq]
            for target in moves_from(sq):
                if target not in seen:
                    seen[target] = seen[sq] + 1
                    queue.append(target)
        return 0

    def validate(self, board: chess.Board, move: chess.Move) -> Feedback:
        if move.from_square != self.current:
            return Feedback(False, "Move the highlighted piece.")
        self.current = move.to_square
        self.steps += 1
        if self.task:
            self.task.meta["current"] = self.current
            self.task.meta["steps"] = self.steps
        if self.current == self.goal:
            extra = self.steps - self.best
            gained = max(2, 20 - extra * 3)
            self.points += gained
            self.solved += 1
            return Feedback(True, f"Arrived in {self.steps} moves (best {self.best}) "
                                  f"+{gained}", done=True, points=gained, solved=True)
        return Feedback(True, f"{self.steps} moves so far…")

    def hint(self, board=None) -> Hint:
        if self.current is None or self.goal is None:
            return Hint()
        return Hint(markers=[Marker(self.current, "circle", "#f6f06a"),
                             Marker(self.goal, "square", "#4aa3ff")],
                    text=f"From {chess.square_name(self.current)} to "
                         f"{chess.square_name(self.goal)}")


class SquareColourSession(Session):
    """Name the colour of a square as fast as you can."""

    name = "Square colours"

    def __init__(self, db, set_id=None, parent=None, rng_seed=None):
        super().__init__(db, set_id, parent, rng_seed)
        self.square: Optional[chess.Square] = None

    def start_task(self) -> Optional[Task]:
        self.begin_task()
        self.square = self.rng.choice(list(chess.SQUARES))
        name = chess.square_name(self.square)
        task = Task(fen=chess.STARTING_FEN, kind="colour",
                    label=f"Is {name} a light square or a dark square?",
                    meta={"square": self.square})
        self.task = task
        self.taskChanged.emit(task)
        return task

    def answer(self, light: bool) -> Feedback:
        if self.square is None:
            return Feedback(False, "")
        is_light = (chess.square_file(self.square) + chess.square_rank(self.square)) % 2 == 1
        ok = is_light == light
        if ok:
            self.points += 5
            self.solved += 1
            return Feedback(True, "Correct! +5", done=True, points=5, solved=True)
        self.failed += 1
        return Feedback(False, f"No - {chess.square_name(self.square)} is "
                               f"{'light' if is_light else 'dark'}.", done=True)

    def hint(self, board=None) -> Hint:
        if self.square is None:
            return Hint()
        is_light = (chess.square_file(self.square) + chess.square_rank(self.square)) % 2 == 1
        return Hint(markers=[Marker(self.square, "circle",
                                    "#f6f06a" if is_light else "#4aa3ff")],
                    text="light" if is_light else "dark")


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

def available_sets(db: sqlite3.Connection) -> List[Tuple[int, str, str, str, int]]:
    """(set_id, kind, name, source, count) for all imported sets."""
    rows = db.execute(
        "SELECT s.id, s.kind, s.name, s.source, (SELECT COUNT(*) FROM puzzles p"
        " WHERE p.set_id=s.id) FROM sets s"
        " WHERE EXISTS(SELECT 1 FROM puzzles p WHERE p.set_id=s.id)").fetchall()
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]


SESSION_FACTORIES: Dict[str, Callable] = {
    "tactics": lambda db, set_id, parent: SolveSession(db, set_id, parent, kind="tactics"),
    "mates": lambda db, set_id, parent: SolveSession(db, set_id, parent, kind="mates"),
    "sts": lambda db, set_id, parent: STSSession(db, set_id, parent),
    "endings": lambda db, set_id, parent: EndgameSession(db, set_id, parent),
    "positional": lambda db, set_id, parent: SolveSession(db, set_id, parent, kind="positional"),
    "guess": lambda db, set_id, parent: GuessSession(db, set_id, parent),
    "everest": lambda db, set_id, parent: EverestSession(db, parent),
    "resistance": lambda db, set_id, parent: ResistanceSession(db, parent),
    "micelo": lambda db, set_id, parent: MicEloSession(db, parent),
    "openings": lambda db, set_id, parent: OpeningSession(db, parent),
    "lights": lambda db, set_id, parent: SquaresSession(db, parent),
    "routes": lambda db, set_id, parent: RouteSession(db, parent),
    "colours": lambda db, set_id, parent: SquareColourSession(db, parent),
    "blindfold": lambda db, set_id, parent: BlindfoldSession(db, parent, level=3),
}


# --------------------------------------------------------------------------
# spaced repetition
# --------------------------------------------------------------------------

class ReviewSession(SolveSession):
    """Replay exactly the drills the learner says are due."""

    name = "Review"

    def __init__(self, db, set_id=None, parent=None, items: Sequence = (),
                 rng_seed=None):
        super().__init__(db, set_id, parent, kind="review", shuffle=False,
                         rng_seed=rng_seed)
        rows = []
        for entry in items:
            # plan() hands back (set, item, reason); a plain pair also works
            item_set, item_id = int(entry[0]), int(entry[1])
            try:
                row = db.execute(
                    "SELECT id, fen, solution, solution_san, label, difficulty"
                    " FROM puzzles WHERE set_id=? AND id=?",
                    (int(item_set), int(item_id))).fetchone()
            except Exception:
                row = None
            if row is not None and row[2]:
                rows.append(row)
        self.rows = rows
        self.queue = list(rows)
        self.planned = len(rows)
