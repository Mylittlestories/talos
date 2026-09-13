"""
Game model: board + clocks + history + variants, with Qt signals so the
whole UI (2D board, 3D battle board, panels, training managers) stays in sync.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import chess
import chess.variant

from ..variants import ANARCHY, CURATED, AnarchBoard, active_rules

from PyQt6.QtCore import QObject, pyqtSignal

from .. import APP_PGN_EVENT, APP_PGN_SITE
from .players import Player, HumanPlayer, BuiltInPlayer


# --------------------------------------------------------------------------
# variants
# --------------------------------------------------------------------------

VARIANTS: Dict[str, Dict] = {
    "standard":       dict(label="Standard chess", cls=chess.Board, standard=True,
                           desc="The classic game. Castling, en passant, promotion."),
    "chess960":       dict(label="Chess960 (Fischer Random)", cls=None, standard=True,
                           desc="Randomised back rank, 960 starting positions."),
    "crazyhouse":     dict(label="Crazyhouse", cls=chess.variant.CrazyhouseBoard,
                           desc="Captured pieces go to your hand and can be dropped back."),
    "atomic":         dict(label="Atomic chess", cls=chess.variant.AtomicBoard,
                           desc="Every capture explodes: all neighbours die. Kings may be adjacent."),
    "kingofthehill":  dict(label="King of the Hill", cls=chess.variant.KingOfTheHillBoard,
                           desc="Bring your king to the centre four squares to win."),
    "3check":         dict(label="Three-check chess", cls=chess.variant.ThreeCheckBoard,
                           desc="Give three checks and you win."),
    "horde":          dict(label="Horde chess", cls=chess.variant.HordeBoard,
                           desc="White has 36 pawns against a full black army."),
    "racingkings":    dict(label="Racing Kings", cls=chess.variant.RacingKingsBoard,
                           desc="Race your king to the eighth rank. No checks allowed."),
    "antichess":      dict(label="Antichess (Losing chess)", cls=chess.variant.AntichessBoard,
                           desc="Captures are forced. Lose all your pieces (or get stalemated) to win."),
    "giveaway":       dict(label="Giveaway", cls=chess.variant.GiveawayBoard,
                           desc="Like antichess, but stalemate is a draw."),
    "suicide":        dict(label="Suicide chess", cls=chess.variant.SuicideBoard,
                           desc="Old FICS rules for losing chess."),

    # ---- TALOS originals -------------------------------------------------
    "anarchchess":    dict(label="Anarchchess (curated)", cls=None,
                           factory=lambda fen: AnarchBoard(
                               fen=fen, rules=active_rules("anarchchess")),
                           desc="The famous house rules: forced en passant, knooks, "
                                "the c4 bomb, double check wins, Il Vaticano, the "
                                "Siberian Swipe, vertical castling and more."),
    "anarchy":        dict(label="Full anarchy", cls=None,
                           factory=lambda fen: AnarchBoard(
                               fen=fen, rules=active_rules("anarchy")),
                           desc="Every anarchic rule at once, plus promotion "
                                "roulette, the omnipotent pawn, the Bongcloud "
                                "instant win and random events each turn."),
}

VARIANT_KEYS = list(VARIANTS)

#: Variants this app adds on top of python-chess (as opposed to FICS variants).
TALOS_VARIANTS = ("anarchchess", "anarchy")


def make_board(variant: str = "standard", fen: Optional[str] = None,
               chess960_pos: Optional[int] = None) -> chess.Board:
    variant = variant or "standard"
    if variant == "chess960":
        pos = chess960_pos
        if pos is None:
            import random
            pos = random.randrange(960)
        board = chess.Board.from_chess960_pos(pos)
        return board
    spec = VARIANTS.get(variant)
    if spec is None:
        return chess.Board(fen) if fen else chess.Board()
    factory = spec.get("factory")
    if factory is not None:
        return factory(fen)
    cls = spec.get("cls")
    if cls is None:
        return chess.Board(fen) if fen else chess.Board()
    return cls(fen) if fen else cls()


# --------------------------------------------------------------------------
# clocks
# --------------------------------------------------------------------------

@dataclass
class TimeControl:
    base_minutes: float = 5.0
    increment_seconds: float = 3.0
    movestogo: int = 0
    per_move_seconds: float = 0.0        # >0: fixed time per move
    unlimited: bool = False

    def label(self) -> str:
        if self.unlimited:
            return "Unlimited"
        if self.per_move_seconds:
            return f"{self.per_move_seconds:g} s/move"
        base = f"{self.base_minutes:g}"
        if self.base_minutes % 1:
            base = f"{int(self.base_minutes)}:{int(round((self.base_minutes % 1) * 60)):02d}"
        s = f"{base}+{self.increment_seconds:g}"
        if self.movestogo:
            s += f" ({self.movestogo} moves)"
        return s

    def initial_ms(self) -> int:
        if self.unlimited or self.per_move_seconds:
            return 0
        return int(self.base_minutes * 60_000)


class Clock(QObject):
    tick = pyqtSignal(dict)

    def __init__(self, tc: TimeControl, parent=None):
        super().__init__(parent)
        self.tc = tc
        self.remaining = {chess.WHITE: tc.initial_ms(), chess.BLACK: tc.initial_ms()}
        self._running_for: Optional[chess.Color] = None
        self._started_at = 0.0
        self._per_move_deadline: Optional[float] = None

    def reset(self) -> None:
        self.remaining = {chess.WHITE: self.tc.initial_ms(), chess.BLACK: self.tc.initial_ms()}
        self._running_for = None
        self._per_move_deadline = None

    def start_for(self, color: chess.Color) -> None:
        self._running_for = color
        self._started_at = time.time()
        if self.tc.per_move_seconds:
            self._per_move_deadline = self._started_at + self.tc.per_move_seconds

    def stop(self, color: chess.Color) -> None:
        if self._running_for == color:
            elapsed = (time.time() - self._started_at) * 1000
            if not self.tc.unlimited:
                if self.tc.per_move_seconds:
                    self.remaining[color] = 0
                else:
                    self.remaining[color] = max(0, self.remaining[color] - int(elapsed))
                    inc = int(self.tc.increment_seconds * 1000)
                    if inc and not self.tc.per_move_seconds:
                        self.remaining[color] += inc
            self._running_for = None

    def poll(self) -> Dict[chess.Color, int]:
        """Current remaining time including the running slice."""
        out = dict(self.remaining)
        if self._running_for is not None and not self.tc.unlimited:
            elapsed = (time.time() - self._started_at) * 1000
            if self.tc.per_move_seconds:
                out[self._running_for] = max(0, int((self._per_move_deadline - time.time()) * 1000))
            else:
                out[self._running_for] = max(0, out[self._running_for] - int(elapsed))
        return out

    def flagged(self, color: chess.Color) -> bool:
        if self.tc.unlimited:
            return False
        return self.poll()[color] <= 0


def format_clock(ms: int) -> str:
    if ms is None:
        return "--:--"
    ms = max(0, ms)
    total = ms // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    if ms < 20_000:
        return f"{m}:{s:02d}.{ms // 100 % 10}"
    return f"{m:02d}:{s:02d}"


# --------------------------------------------------------------------------
# game
# --------------------------------------------------------------------------

@dataclass
class MoveRecord:
    move: chess.Move
    san: str
    fen_before: str
    fen_after: str
    capture: Optional[chess.Piece] = None
    captured_square: Optional[chess.Square] = None
    is_castle: bool = False
    is_promotion: bool = False
    is_en_passant: bool = False
    check: bool = False
    mate: bool = False
    comment: str = ""
    nags: List[int] = field(default_factory=list)
    clock_ms: Optional[int] = None
    battle: bool = True          # whether battle mode should animate it


class Game(QObject):
    positionChanged = pyqtSignal()
    moveMade = pyqtSignal(object)        # MoveRecord
    gameOver = pyqtSignal(str, str)      # result, reason
    clocksChanged = pyqtSignal(dict)

    def __init__(self, variant: str = "standard", fen: Optional[str] = None,
                 tc: Optional[TimeControl] = None, parent=None,
                 chess960_pos: Optional[int] = None):
        super().__init__(parent)
        self.variant = variant
        self.start_fen = fen
        self.board = make_board(variant, fen, chess960_pos)
        self.start_fen = self.board.fen()
        self.tc = tc or TimeControl(unlimited=True)
        self.clock = Clock(self.tc, self)
        self.players: Dict[chess.Color, Player] = {
            chess.WHITE: HumanPlayer("White"),
            chess.BLACK: HumanPlayer("Black"),
        }
        self.records: List[MoveRecord] = []
        self.tags: Dict[str, str] = {}
        self.result: Optional[str] = None
        self.reason: str = ""
        self.analysis: Dict[int, str] = {}     # ply -> comment

    # -- setup ------------------------------------------------------------
    def set_player(self, color: chess.Color, player: Player) -> None:
        self.players[color] = player

    def set_time_control(self, tc: TimeControl) -> None:
        self.tc = tc
        self.clock = Clock(tc, self)
        self.clock.reset()

    def reset(self, fen: Optional[str] = None, variant: Optional[str] = None,
              chess960_pos: Optional[int] = None) -> None:
        if variant:
            self.variant = variant
        self.board = make_board(self.variant, fen, chess960_pos)
        self.start_fen = self.board.fen()
        self.records.clear()
        self.result = None
        self.reason = ""
        self.clock.reset()
        self.positionChanged.emit()

    # -- moves ------------------------------------------------------------
    def legal_moves(self, square: Optional[chess.Square] = None) -> List[chess.Move]:
        if square is None:
            return list(self.board.legal_moves)
        return [m for m in self.board.legal_moves if m.from_square == square]

    def is_legal(self, move: chess.Move) -> bool:
        return move in self.board.legal_moves

    def push(self, move: chess.Move, comment: str = "") -> Optional[MoveRecord]:
        if move not in self.board.legal_moves:
            return None
        color = self.board.turn
        fen_before = self.board.fen()
        board_before = self.board.copy(stack=False)
        san = self.board.san(move)
        piece = self.board.piece_at(move.from_square)
        capture = self.board.piece_at(move.to_square)
        cap_sq: Optional[chess.Square] = move.to_square
        is_ep = bool(piece and piece.piece_type == chess.PAWN and
                     self.board.is_en_passant(move))
        if is_ep:
            cap_sq = move.to_square + (-8 if color == chess.WHITE else 8)
            capture = self.board.piece_at(cap_sq)
        is_castle = bool(piece and piece.piece_type == chess.KING and
                         abs(chess.square_file(move.from_square) - chess.square_file(move.to_square)) > 1)
        self.board.push(move)
        rec = MoveRecord(
            move=move, san=san, fen_before=fen_before, fen_after=self.board.fen(),
            capture=capture, captured_square=cap_sq, is_castle=is_castle,
            is_promotion=bool(move.promotion), is_en_passant=is_ep,
            check=self.board.is_check(), mate=self.board.is_checkmate(),
            comment=comment,
        )
        self.records.append(rec)
        self.clock.stop(color)
        self.clock.start_for(self.board.turn)
        self.positionChanged.emit()
        self.moveMade.emit(rec)
        self._check_end()
        return rec

    def push_san(self, san: str, comment: str = "") -> Optional[MoveRecord]:
        try:
            move = self.board.parse_san(san)
        except Exception:
            try:
                move = self.board.parse_uci(san)
            except Exception:
                return None
        return self.push(move, comment)

    def undo(self) -> Optional[MoveRecord]:
        if not self.records:
            return None
        rec = self.records.pop()
        self.board.pop()
        self.result = None
        self.reason = ""
        self.clock.remaining[chess.WHITE] = self.tc.initial_ms()
        self.clock.remaining[chess.BLACK] = self.tc.initial_ms()
        self.positionChanged.emit()
        return rec

    def goto_ply(self, ply: int) -> None:
        while len(self.records) > ply and self.records:
            self.records.pop()
            self.board.pop()
        self.positionChanged.emit()

    # -- results ----------------------------------------------------------
    def _check_end(self) -> None:
        board = self.board
        res = None
        reason = ""
        try:
            # python-chess cannot replay drop moves when claiming draws in
            # crazyhouse, so claims are skipped for that variant
            outcome = board.outcome(claim_draw=self.variant != "crazyhouse")
        except Exception:
            outcome = board.outcome(claim_draw=False)
        if outcome:
            if outcome.winner is None:
                res = "1/2-1/2"
            else:
                res = "1-0" if outcome.winner == chess.WHITE else "0-1"
            reason = outcome.termination.name.replace("_", " ").title()
        if res is None:
            for color in (chess.WHITE, chess.BLACK):
                if self.clock.flagged(color):
                    res = "0-1" if color == chess.WHITE else "1-0"
                    reason = "Flag fell"
                    break
        if res:
            self.result = res
            self.reason = reason
            self.clock.stop(self.board.turn)
            self.gameOver.emit(res, reason)

    def is_over(self) -> bool:
        return self.result is not None

    def turn(self) -> chess.Color:
        return self.board.turn

    def current_player(self) -> Player:
        return self.players[self.board.turn]

    # -- pgn --------------------------------------------------------------
    def to_pgn(self, event: str = APP_PGN_EVENT, site: str = "local") -> str:
        import chess.pgn
        game = chess.pgn.Game()
        try:
            start_board = make_board(self.variant, self.start_fen)
        except Exception:
            start_board = chess.Board()
        try:
            game.setup(start_board)
        except Exception:
            pass
        tags = dict(self.tags)
        tags.setdefault("Event", event)
        tags.setdefault("Site", site)
        tags.setdefault("Date", time.strftime("%Y.%m.%d"))
        tags.setdefault("Round", "?")
        tags.setdefault("White", self.players[chess.WHITE].name)
        tags.setdefault("Black", self.players[chess.BLACK].name)
        if self.result:
            tags["Result"] = self.result
        if self.variant != "standard":
            tags["Variant"] = self.variant.capitalize()
        if self.start_fen != chess.STARTING_FEN and self.start_fen != self.board.starting_fen:
            tags["SetUp"] = "1"
            tags["FEN"] = self.start_fen
        game.headers.update(tags)
        node = game
        for rec in self.records:
            node = node.add_variation(rec.move)
            if rec.comment:
                node.comment = rec.comment
            for nag in rec.nags:
                node.nags.add(nag)
        if self.result:
            game.headers["Result"] = self.result
        return str(game)

    def load_pgn(self, text: str) -> bool:
        import chess.pgn
        try:
            game = chess.pgn.read_game(io.StringIO(text))
        except Exception:
            return False
        if game is None:
            return False
        variant = game.headers.get("Variant", "standard").lower()
        variant = {"chess960": "chess960", "three-check": "3check",
                   "crazyhouse": "crazyhouse", "atomic": "atomic",
                   "king of the hill": "kingofthehill", "racing kings": "racingkings",
                   "horde": "horde", "antichess": "antichess"}.get(variant, variant)
        if variant not in VARIANTS:
            variant = "standard"
        fen = game.headers.get("FEN")
        self.reset(fen=fen, variant=variant)
        self.tags = dict(game.headers)
        board = self.board
        for node in game.mainline():
            mv = node.move
            if mv not in board.legal_moves:
                break
            rec = self.push(mv, node.comment or "")
            if rec is not None and node.nags:
                rec.nags = sorted(node.nags)
        return True
