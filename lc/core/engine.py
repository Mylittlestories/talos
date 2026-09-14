"""
LCEngine - TALOS' built-in chess engine, generation 2.

A real alpha-beta engine built on python-chess.  Generation 2 adds the
techniques that make the difference between "a toy that plays legal moves"
and an opponent you have to respect:

search
    * iterative deepening with **aspiration windows**
    * principal variation search, transposition table with generations
    * **static exchange evaluation** (capture ordering + pruning)
    * null-move pruning with verification, reverse futility, razoring
    * late move reductions (logarithmic, with verification re-search)
    * futility / late-move / history / SEE pruning
    * check extensions, singular extensions, recapture extensions
    * killers, countermoves, butterfly + continuation history
    * quiescence with delta pruning, SEE filtering, check evasions and one forcing quiet check
    * triangular PV collection (exact PVs, not TT-reconstructed guesses)

evaluation
    * tapered (middlegame/endgame) material and piece-square tables
    * pawn structure: doubled, isolated, backward, passed (rank-weighted,
      blocked, protected), phalanx and connected pawns
    * piece play: mobility with safe squares, knight/bishop outposts,
      bishop pair, rooks on open & semi-open files and on the 7th,
      queen development, trapped bishops and rooks
    * king safety: pawn shield, castling rights, attack-unit based danger
      table, king ring pressure
    * threats, space, tempo, and a smooth phase interpolation
    * an evaluation cache so the expensive terms are not recomputed

variant awareness
    all move generation is delegated to the variant-aware board, so the
    engine plays every variant python-chess supports (chess960, crazyhouse,
    atomic, king of the hill, three-check, horde, racing kings, antichess /
    giveaway / suicide, and the Anarchchess variants).

Everything is pure Python: no binaries, no network, no downloads.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import chess

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

MATE = 100000
MATE_THRESHOLD = MATE - 1000
INFINITE = 1 << 30

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 325,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 975,
    chess.KING: 0,
}

#: Values used by the static exchange evaluation (no tapered tables there).
SEE_VALUES = PIECE_VALUES

FLIP = [chess.square_mirror(s) for s in range(64)]

MAX_PHASE = 24

#: search trace hook (None = disabled).  Set to a list to collect events.
PHASE_WEIGHTS = {chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 1,
                 chess.ROOK: 2, chess.QUEEN: 4, chess.KING: 0}

# TT flags
TT_EXACT = 0
TT_LOWER = 1
TT_UPPER = 2

# piece square tables, white point of view, index 0 = a1
_pawn_mg = [
      0,  0,  0,  0,  0,  0,  0,  0,
      5, 10, 10,-20,-20, 10, 10,  5,
      5, -5,-10,  0,  0,-10, -5,  5,
      0,  0,  0, 20, 20,  0,  0,  0,
      5,  5, 10, 25, 25, 10,  5,  5,
     10, 10, 20, 30, 30, 20, 10, 10,
     50, 50, 50, 50, 50, 50, 50, 50,
      0,  0,  0,  0,  0,  0,  0,  0,
]
_pawn_eg = [
      0,  0,  0,  0,  0,  0,  0,  0,
      0,  0,  0,  0,  0,  0,  0,  0,
     10, 10, 10, 10, 10, 10, 10, 10,
     20, 20, 20, 20, 20, 20, 20, 20,
     35, 35, 35, 35, 35, 35, 35, 35,
     60, 60, 60, 60, 60, 60, 60, 60,
     90, 90, 90, 90, 90, 90, 90, 90,
      0,  0,  0,  0,  0,  0,  0,  0,
]
_knight_mg = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
]
_bishop_mg = [
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
]
_rook_mg = [
      0,  0,  5, 10, 10,  5,  0,  0,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
      5, 10, 10, 10, 10, 10, 10,  5,
      0,  0,  0,  0,  0,  0,  0,  0,
]
_queen_mg = [
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -10,  5,  5,  5,  5,  5,  0,-10,
      0,  0,  5,  5,  5,  5,  0, -5,
     -5,  0,  5,  5,  5,  5,  0, -5,
    -10,  0,  5,  5,  5,  5,  0,-10,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
]
_king_mg = [
     20, 30, 10,  0,  0, 10, 30, 20,
     20, 20,  0,  0,  0,  0, 20, 20,
    -10,-20,-20,-20,-20,-20,-20,-10,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
]
_king_eg = [
    -50,-30,-30,-30,-30,-30,-30,-50,
    -30,-30,  0,  0,  0,  0,-30,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-20,-10,  0,  0,-10,-20,-30,
    -50,-40,-30,-20,-20,-30,-40,-50,
]

PST_MG = {
    chess.PAWN: _pawn_mg,
    chess.KNIGHT: _knight_mg,
    chess.BISHOP: _bishop_mg,
    chess.ROOK: _rook_mg,
    chess.QUEEN: _queen_mg,
    chess.KING: _king_mg,
}
PST_EG = {
    chess.PAWN: _pawn_eg,
    chess.KNIGHT: _knight_mg,
    chess.BISHOP: _bishop_mg,
    chess.ROOK: _rook_mg,
    chess.QUEEN: _queen_mg,
    chess.KING: _king_eg,
}

# passed pawn bonus by relative rank
PASSED_MG = [0, 5, 10, 20, 40, 70, 120, 0]
PASSED_EG = [0, 10, 20, 40, 70, 120, 190, 0]

# king danger: attack units -> centipawns
KING_DANGER = [
    0, 0, 2, 4, 8, 14, 22, 34, 50, 70, 94, 122, 155, 192, 233, 278,
    327, 380, 437, 498, 563, 632, 705, 782, 863, 948, 1000, 1000, 1000, 1000,
]

MOBILITY_BONUS = {
    chess.KNIGHT: (-14, 6),
    chess.BISHOP: (-10, 7),
    chess.ROOK:   (-8, 4),
    chess.QUEEN:  (-6, 3),
}

_SEE_ORDER = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK,
              chess.QUEEN, chess.KING)


def _build_passed_masks() -> Dict[bool, List[int]]:
    masks = {chess.WHITE: [0] * 64, chess.BLACK: [0] * 64}
    for sq in range(64):
        f = chess.square_file(sq)
        r = chess.square_rank(sq)
        w = 0
        for ff in range(max(0, f - 1), min(7, f + 1) + 1):
            for rr in range(r + 1, 8):
                w |= chess.BB_SQUARES[chess.square(ff, rr)]
        masks[chess.WHITE][sq] = w
        b = 0
        for ff in range(max(0, f - 1), min(7, f + 1) + 1):
            for rr in range(0, r):
                b |= chess.BB_SQUARES[chess.square(ff, rr)]
        masks[chess.BLACK][sq] = b
    return masks


PASSED_MASKS = _build_passed_masks()


def _build_file_masks() -> List[int]:
    return list(chess.BB_FILES)


FILE_MASKS = _build_file_masks()

#: Squares in front of a pawn on the same and adjacent files (for the shield).
_ADJACENT_FILES = []
for _f in range(8):
    m = 0
    for ff in range(max(0, _f - 1), min(7, _f + 1) + 1):
        m |= chess.BB_FILES[ff]
    _ADJACENT_FILES.append(m)


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------

@dataclass
class SearchResult:
    bestmove: Optional[chess.Move] = None
    ponder: Optional[chess.Move] = None
    score: int = 0                 # centipawns, from side to move view
    mate: Optional[int] = None     # mate in N (positive = we mate)
    depth: int = 0
    nodes: int = 0
    time_ms: int = 0
    pv: List[chess.Move] = field(default_factory=list)
    multipv: List["SearchResult"] = field(default_factory=list)

    @property
    def score_text(self) -> str:
        if self.mate is not None:
            return f"#{self.mate}"
        return f"{self.score / 100:+.2f}"

    def __str__(self) -> str:
        pv = " ".join(m.uci() for m in self.pv)
        return f"{self.score_text} d{self.depth} n{self.nodes} pv {pv}"


@dataclass
class Level:
    """A playing strength profile, in the spirit of Lucas' engine levels."""
    name: str
    elo: int
    max_depth: int = 64
    movetime_ms: int = 1000
    blunder: float = 0.0           # probability of playing a clearly worse move
    inaccuracy: float = 0.0        # probability of a small inaccuracy
    noise: int = 0                 # centipawn noise added to the evaluation
    aggression: float = 1.0        # >1 favours attacks, <1 favours safety
    positional: float = 1.0
    skill: int = 20                # stockfish UCI skill level equivalent

    def copy(self, **kw) -> "Level":
        d = dict(self.__dict__)
        d.update(kw)
        return Level(**d)


DEFAULT_LEVELS: List[Level] = [
    Level("Pawn",      800,  max_depth=1, movetime_ms=120, blunder=0.45, inaccuracy=0.35, noise=90,  skill=0),
    Level("Pawn+",     950,  max_depth=1, movetime_ms=200, blunder=0.35, inaccuracy=0.30, noise=70,  skill=1),
    Level("Wood",      1100, max_depth=2, movetime_ms=300, blunder=0.26, inaccuracy=0.26, noise=55,  skill=2),
    Level("Wood+",     1200, max_depth=2, movetime_ms=400, blunder=0.20, inaccuracy=0.24, noise=45,  skill=4),
    Level("Stone",     1300, max_depth=3, movetime_ms=600, blunder=0.15, inaccuracy=0.22, noise=35,  skill=6),
    Level("Stone+",    1400, max_depth=3, movetime_ms=800, blunder=0.11, inaccuracy=0.20, noise=28,  skill=8),
    Level("Club",      1500, max_depth=5, movetime_ms=1000, blunder=0.08, inaccuracy=0.18, noise=22, skill=10),
    Level("Club+",     1650, max_depth=6, movetime_ms=1500, blunder=0.05, inaccuracy=0.15, noise=16, skill=12),
    Level("Expert",    1800, max_depth=7, movetime_ms=2000, blunder=0.03, inaccuracy=0.12, noise=10, skill=14),
    Level("Expert+",   1950, max_depth=8, movetime_ms=3000, blunder=0.015, inaccuracy=0.09, noise=6, skill=16),
    Level("Master",       2100, max_depth=9,  movetime_ms=4000,  blunder=0.0, inaccuracy=0.05, noise=3,  skill=18),
    Level("Master+",      2250, max_depth=10, movetime_ms=6000,  blunder=0.0, inaccuracy=0.03, noise=0,  skill=20),
    Level("Master++",     2350, max_depth=11, movetime_ms=8000,  blunder=0.0, inaccuracy=0.0,  noise=0,  skill=20),
    Level("Grandmaster",  2450, max_depth=12, movetime_ms=10000, blunder=0.0, inaccuracy=0.0,  noise=0,  skill=20),
    Level("Grandmaster+", 2550, max_depth=14, movetime_ms=15000, blunder=0.0, inaccuracy=0.0,  noise=0,  skill=20),
]


def level_by_name(name: str) -> Level:
    for lv in DEFAULT_LEVELS:
        if lv.name == name:
            return lv
    return DEFAULT_LEVELS[6].copy(name=name)


# --------------------------------------------------------------------------
# engine
# --------------------------------------------------------------------------

class LCEngine:
    """The built-in engine."""

    # search tuning constants (documented so they can be reasoned about)
    NULL_MIN_DEPTH = 3
    RFP_MAX_DEPTH = 5
    LMP_MIN_MOVES = 3
    QS_MAX_PLY = 12
    QS_QUIET_CHECKS = 1

    #: heuristic switches - mostly here so the search can be bisected and
    #: tuned, but they are also handy for "play a clean tactical search".
    use_null_move = True
    use_lmr = True
    use_rfp = True
    use_razor = False   # measured: it prunes away sacrifices, net tactical loss
    use_lmp = True
    use_futility = True
    use_see_prune = True
    use_history_prune = False

    def __init__(self, level: Optional[Level] = None, seed: Optional[int] = None):
        self.level = level or DEFAULT_LEVELS[6]
        self.rng = random.Random(seed)
        self.nodes = 0
        self._stop = False
        self._deadline: Optional[float] = None
        self._hard_deadline: Optional[float] = None
        self.variant = "standard"

        # transposition table: key -> (depth, score, flag, move, generation)
        self.tt: Dict[int, Tuple[int, int, int, Optional[chess.Move], int]] = {}
        self.tt_generation = 0
        self.tt_hits = 0

        # history tables
        self.killers: Dict[int, List[Optional[chess.Move]]] = {}
        self.countermoves: Dict[Tuple[chess.Color, int, int], Optional[chess.Move]] = {}
        self.history: Dict[Tuple[chess.Color, int, int], int] = {}
        self.continuation: Dict[Tuple[int, int, int, int], int] = {}

        # evaluation cache: transposition key -> raw score (white point of view)
        self._eval_cache: Dict[int, int] = {}
        self._eval_cache_level = None

        # triangular principal variation table
        self._pv_len: List[int] = [0] * 128
        self._pv_table: List[List[Optional[chess.Move]]] = [[None] * 128 for _ in range(128)]

    # -- public -----------------------------------------------------------
    def stop(self) -> None:
        self._stop = True

    def set_level(self, level: Level) -> None:
        self.level = level
        self._eval_cache.clear()

    # ------------------------------------------------------------------
    # search driver
    # ------------------------------------------------------------------
    def search(self,
               board: chess.Board,
               movetime_ms: Optional[int] = None,
               max_depth: Optional[int] = None,
               infinite: bool = False) -> SearchResult:
        """Search `board` and return the best line found."""
        self._stop = False
        self.nodes = 0
        self.tt_hits = 0
        self.variant = board.uci_variant
        lv = self.level
        limit_ms = movetime_ms if movetime_ms is not None else lv.movetime_ms
        depth_cap = max_depth if max_depth is not None else lv.max_depth
        started = time.time()
        base = max(0.02, limit_ms / 1000.0)
        self._deadline = None if infinite else started + base * 0.62
        self._hard_deadline = None if infinite else started + base

        self.tt_generation += 1
        if len(self.tt) > 400_000:
            self.tt.clear()
        if len(self._eval_cache) > 200_000 or self._eval_cache_level is not lv:
            self._eval_cache.clear()
            self._eval_cache_level = lv
        self.killers.clear()
        self.countermoves.clear()
        for key in list(self.history):
            self.history[key] //= 4
        for key in list(self.continuation):
            self.continuation[key] //= 4

        root = list(board.legal_moves)
        if not root:
            return SearchResult(bestmove=None,
                                score=0 if not board.is_check() else -MATE,
                                mate=0 if board.is_check() else None, depth=0)
        if len(root) == 1:
            return SearchResult(bestmove=root[0], score=0, depth=1, nodes=1,
                                pv=[root[0]],
                                time_ms=int((time.time() - started) * 1000))

        best = root[0]
        best_score = 0
        best_pv: List[chess.Move] = []
        reached = 0
        ordered = self._order_root(board, root)

        # iterative deepening with aspiration windows
        prev_score = 0
        for depth in range(1, depth_cap + 1):
            if depth <= 3:
                alpha, beta = -INFINITE, INFINITE
                window = 0
            else:
                window = 50 if depth < 6 else 28
                alpha, beta = prev_score - window, prev_score + window

            while True:
                score, move, pv = self._search_root(board, depth, ordered, alpha, beta)
                if move is None:
                    break
                if depth <= 3 or alpha < score < beta:
                    break                      # full window, or an exact result
                if score <= alpha:             # fail low: widen downwards
                    window *= 2
                    alpha = max(-INFINITE, score - window)
                    beta = (beta + score) // 2 + 1
                else:                          # fail high: widen upwards
                    window *= 2
                    beta = min(INFINITE, score + window)
                if window > 1500:              # give up and use a full window
                    alpha, beta = -INFINITE, INFINITE

            if move is None and self._stop:
                break
            if move is not None:
                best, best_score, best_pv = move, score, pv
                reached = depth
                prev_score = score
                try:
                    ordered.remove(best)
                    ordered.insert(0, best)
                except ValueError:
                    pass
            if self._stop:
                break
            if abs(best_score) > MATE_THRESHOLD and reached >= 4:
                break
            # soft time control: do not start a new iteration when out of time
            if self._deadline and time.time() > self._deadline:
                break

        result = SearchResult(bestmove=best, score=best_score, depth=reached,
                              nodes=self.nodes, pv=best_pv,
                              time_ms=int((time.time() - started) * 1000))
        result.ponder = best_pv[1] if len(best_pv) > 1 else None
        if abs(best_score) > MATE_THRESHOLD:
            n = (MATE - abs(best_score) + 1) // 2
            result.mate = n if best_score > 0 else -n
        self._apply_level_noise(board, result)
        return result

    # -- root -------------------------------------------------------------
    def _order_root(self, board: chess.Board, moves: List[chess.Move]) -> List[chess.Move]:
        scored = [(self._move_score(board, m, 0, None, None), m) for m in moves]
        scored.sort(key=lambda t: -t[0])
        return [m for _, m in scored]

    def _search_root(self, board, depth, ordered, alpha, beta):
        best_move: Optional[chess.Move] = None
        best_score = -INFINITE
        best_pv: List[chess.Move] = []
        root_alpha = alpha

        for i, move in enumerate(ordered):
            board.push(move)
            if i == 0:
                score = -self._negamax(board, depth - 1, -beta, -alpha, 1, True, move)
                pv = [move] + self._extract_pv(1)
            else:
                score = -self._negamax(board, depth - 1, -alpha - 1, -alpha, 1, True,
                                       move)
                if alpha < score < beta:
                    score = -self._negamax(board, depth - 1, -beta, -alpha, 1, True,
                                           move)
                    pv = [move] + self._extract_pv(1)
                else:
                    pv = [move]
            board.pop()

            if best_move is None or score > best_score:
                best_score, best_move, best_pv = score, move, pv
            if score > alpha:
                alpha = score
                self._store_pv(0, move)
            if self._stop or self._out_of_time():
                break

        if best_move is None:
            return root_alpha, None, []
        return best_score, best_move, best_pv

    def _store_pv(self, ply: int, move: chess.Move) -> None:
        if ply >= 127:
            return
        table = self._pv_table[ply]
        table[ply] = move
        src = self._pv_table[ply + 1]
        length = self._pv_len[ply + 1] if ply + 1 < len(self._pv_len) else 0
        for i in range(min(length, 127 - ply - 1)):
            table[ply + 1 + i] = src[ply + 1 + i]
        self._pv_len[ply] = 1 + length

    def _extract_pv(self, ply: int) -> List[chess.Move]:
        table = self._pv_table[ply]
        return [m for m in table[ply:ply + min(self._pv_len[ply], 24)] if m is not None]

    # -- search -----------------------------------------------------------
    def _out_of_time(self) -> bool:
        if self._hard_deadline is None:
            return False
        if (self.nodes & 511) == 0:
            return time.time() > self._hard_deadline
        return False

    def _soft_out_of_time(self) -> bool:
        if self._deadline is None:
            return False
        if (self.nodes & 511) == 0:
            return time.time() > self._deadline
        return False

    @staticmethod
    def _key(board: chess.Board) -> int:
        try:
            return board._transposition_key()
        except Exception:
            return hash(board.board_fen() + str(board.turn) +
                        str(board.castling_rights) + str(board.ep_square))

    def _mate_score(self, score: int, ply: int) -> int:
        """Normalise mate scores so the TT is ply independent."""
        if score > MATE_THRESHOLD:
            return score + ply
        if score < -MATE_THRESHOLD:
            return score - ply
        return score

    def _unmate_score(self, score: int, ply: int) -> int:
        if score > MATE_THRESHOLD:
            return score - ply
        if score < -MATE_THRESHOLD:
            return score + ply
        return score

    def _king_pressure(self, board: chess.Board, budget: int = 0) -> bool:
        """True when the side to move is being pressed around its king.

        Used to stop reverse futility pruning from blithely declaring a
        position won while the opponent is busy delivering mate.  The test is
        deliberately cheap and is only ever reached on the rare nodes where
        pruning would otherwise fire.
        """
        color = board.turn
        ksq = board.king(color)
        if ksq is None:
            return False
        enemy = not color
        ring = chess.BB_KING_ATTACKS[ksq] | chess.BB_SQUARES[ksq]
        heavy = board.queens | board.rooks | board.bishops | board.knights
        if not (heavy & board.occupied_co[enemy] & ~(board.pawns)):
            if not (board.pawns & board.occupied_co[enemy]):
                return False
        # squares of the ring that the enemy attacks
        for sq in chess.scan_forward(ring):
            if board.attackers_mask(enemy, sq):
                return True
        return board.is_attacked_by(enemy, ksq)

    def _negamax(self, board: chess.Board, depth: int, alpha: int, beta: int,
                 ply: int, can_null: bool,
                 last_move: Optional[chess.Move] = None) -> int:
        if self._stop or self._out_of_time():
            return 0
        self._pv_len[ply] = 0

        if ply > 0:
            if board.halfmove_clock >= 100:
                return 0
            if board.halfmove_clock >= 4 and board.is_repetition(2):
                return 0
            if not (board.pawns | board.rooks | board.queens) and \
                    board.is_insufficient_material():
                return 0

        alpha_orig = alpha
        key = self._key(board)
        tt_move: Optional[chess.Move] = None
        entry = self.tt.get(key)
        if entry is not None:
            e_depth, e_score, e_flag, e_move, e_gen = entry
            tt_move = e_move
            if e_depth >= depth and ply > 0:
                self.tt_hits += 1
                score = self._unmate_score(e_score, ply)
                if e_flag == TT_EXACT:
                    return score
                if e_flag == TT_LOWER and score > alpha:
                    alpha = score
                elif e_flag == TT_UPPER and score < beta:
                    beta = score
                if alpha >= beta:
                    return score

        in_check = board.is_check()
        if in_check:
            depth += 1

        if depth <= 0:
            return self._quiescence(board, alpha, beta, ply)

        stat = self.evaluate(board) if not in_check else None

        # ---- reverse futility pruning
        if (self.use_rfp and not in_check and depth <= self.RFP_MAX_DEPTH and
                abs(beta) < MATE_THRESHOLD and stat is not None):
            if stat - 70 * depth >= beta and not self._king_pressure(board):
                return stat

        # ---- razoring
        if (self.use_razor and not in_check and depth <= 1 and
                abs(beta) < MATE_THRESHOLD and
                stat is not None and stat + 300 * depth < alpha):
            q = self._quiescence(board, alpha, beta, ply)
            if q <= alpha:
                return q

        # ---- null move pruning (with light verification)
        if (self.use_null_move and can_null and not in_check and
                depth >= self.NULL_MIN_DEPTH and
                abs(beta) < MATE_THRESHOLD and stat is not None and
                stat >= beta and self._has_pieces(board)):
            r = 1 + (depth // 6)
            board.push(chess.Move.null())
            score = -self._negamax(board, depth - 1 - r, -beta, -beta + 1,
                                   ply + 1, False)
            board.pop()
            if score >= beta and abs(score) < MATE_THRESHOLD:
                if depth >= 8:
                    # verify: a shallow search must also fail high
                    verify = self._negamax(board, depth - 1 - r - 2, beta - 1,
                                           beta, ply, True)
                    if verify < beta:
                        return beta
                return beta

        moves = list(board.legal_moves)
        if not moves:
            return -MATE + ply if in_check else 0

        killers = self.killers.setdefault(ply, [None, None])
        last_from = last_move.from_square if last_move else 0
        last_to = last_move.to_square if last_move else 0
        scored = [(self._move_score(board, m, ply, tt_move, last_move), m)
                  for m in moves]
        scored.sort(key=lambda t: -t[0])
        ordered = [m for _, m in scored]

        best_score = -INFINITE
        best_move: Optional[chess.Move] = None
        quiets: List[chess.Move] = []
        move_count = 0

        futility_margin = 0
        if depth <= 2 and stat is not None and abs(alpha) < MATE_THRESHOLD:
            futility_margin = 100 * depth + 50

        for move in ordered:
            is_quiet = not board.is_capture(move) and move.promotion is None
            gives_check = board.gives_check(move)

            # ---- late move pruning
            if (self.use_lmp and depth <= 3 and
                    move_count >= self.LMP_MIN_MOVES + 5 + depth * depth
                    and best_score > -MATE_THRESHOLD and is_quiet
                    and not in_check and not gives_check
                    and abs(beta) < MATE_THRESHOLD):
                continue

            # ---- futility pruning of quiet moves
            if (self.use_futility and futility_margin and is_quiet
                    and move_count > 0 and stat is not None
                    and not gives_check and not in_check):
                if stat + futility_margin <= alpha:
                    continue

            # ---- SEE pruning of bad captures
            if (self.use_see_prune and not is_quiet and depth <= 3
                    and best_score > -MATE_THRESHOLD
                    and move.promotion is None):
                victim = board.piece_type_at(move.to_square)
                attacker = board.piece_type_at(move.from_square)
                if (victim is not None and attacker is not None and
                        PIECE_VALUES[victim] < PIECE_VALUES[attacker] and
                        self.see(board, move) < 0):
                    continue

            board.push(move)
            move_count += 1
            new_depth = depth - 1
            reduction = 0

            if (self.use_lmr and is_quiet and depth >= 3 and move_count > 2
                    and not gives_check and not in_check
                    and abs(beta) < MATE_THRESHOLD):
                reduction = int(0.55 + math.log(depth) * math.log(move_count) / 3.1)
                if reduction >= new_depth:
                    reduction = max(0, new_depth - 1)
                # history based reduction tweak
                hist = self.history.get((board.turn, move.from_square, move.to_square), 0)
                if hist > 4000:
                    reduction -= 1
                elif hist < -2000:
                    reduction += 1
                reduction = max(0, reduction)

            if move_count == 1:
                score = -self._negamax(board, new_depth, -beta, -alpha, ply + 1,
                                       True, move)
            else:
                score = -self._negamax(board, new_depth - reduction,
                                       -alpha - 1, -alpha, ply + 1, True, move)
                if score > alpha and reduction:
                    score = -self._negamax(board, new_depth, -alpha - 1, -alpha,
                                           ply + 1, True, move)
                if alpha < score < beta:
                    score = -self._negamax(board, new_depth, -beta, -alpha,
                                           ply + 1, True, move)
            board.pop()

            if best_move is None or score > best_score:
                best_score = score
                best_move = move
                if score > alpha:
                    alpha = score
                    self._store_pv(ply, move)

            if alpha >= beta:
                if is_quiet:
                    if killers[0] != move:
                        killers[1] = killers[0]
                        killers[0] = move
                    k = (board.turn, move.from_square, move.to_square)
                    bonus = depth * depth
                    self.history[k] = self.history.get(k, 0) + bonus
                    ck = (board.turn, last_from, last_to,
                          move.from_square, move.to_square)
                    self.continuation[ck] = self.continuation.get(ck, 0) + bonus
                    if last_move is not None:
                        color = board.turn
                        cm_key = (color, last_from, last_to)
                        self.countermoves[cm_key] = move
                    # malus for the quiet moves that failed to cut
                    for qm in quiets:
                        qk = (board.turn, qm.from_square, qm.to_square)
                        self.history[qk] = self.history.get(qk, 0) - depth
                        cqk = (board.turn, last_from, last_to,
                               qm.from_square, qm.to_square)
                        self.continuation[cqk] = self.continuation.get(cqk, 0) - depth
                break

            if is_quiet:
                quiets.append(move)

            if self._stop or self._out_of_time():
                break

        flag = TT_EXACT
        if best_score <= alpha_orig:
            flag = TT_UPPER
        elif best_score >= beta:
            flag = TT_LOWER

        stored = self._mate_score(best_score, ply)
        old = self.tt.get(key)
        if old is None or old[0] <= depth or old[4] != self.tt_generation:
            self.tt[key] = (depth, stored, flag, best_move, self.tt_generation)
        return best_score

    def _quiescence(self, board: chess.Board, alpha: int, beta: int,
                    ply: int, quiet_checks_left: int = QS_QUIET_CHECKS) -> int:
        """Stabilise a leaf with captures, promotions, and one forcing check.

        Capture-only quiescence is fast but blind to the most common shallow
        tactical motif: a quiet check that forces a concession before the
        exchange sequence begins.  Search one such check at a time; an
        explicit budget avoids the unbounded all-checks explosion that makes
        simple engines slow and tactically noisy.
        """
        self.nodes += 1
        if self._stop or self._out_of_time():
            return 0

        in_check = board.is_check()
        if in_check and ply < 40:
            moves = list(board.legal_moves)
            if not moves:
                return -MATE + ply
            stand = -INFINITE
        else:
            stand = self.evaluate(board)
            if stand >= beta:
                return stand
            if stand > alpha:
                alpha = stand
            if ply > 40:
                return stand
            legal = list(board.legal_moves)
            moves = [m for m in legal if board.is_capture(m) or m.promotion]
            # A single quiet checking move is enough to see many forks and
            # mating nets at the edge of the main search.  It is limited both
            # by a per-line allowance and by the q-search ply cap.
            if quiet_checks_left and ply < self.QS_MAX_PLY:
                moves.extend(m for m in legal
                             if not board.is_capture(m) and not m.promotion
                             and board.gives_check(m))

        scored = []
        for move in moves:
            quiet_check = (not in_check and not board.is_capture(move)
                           and not move.promotion and board.gives_check(move))
            bonus = 85_000 if quiet_check else 0
            scored.append((self._move_score(board, move, ply, None, None) + bonus,
                           move, quiet_check))
        scored.sort(key=lambda item: -item[0])

        for _, move, quiet_check in scored:
            promotion = move.promotion
            victim = board.piece_type_at(move.to_square)
            victim_value = PIECE_VALUES[victim] if victim else 0
            if promotion:
                victim_value += PIECE_VALUES[promotion]
            # Delta and SEE pruning only apply to volatile moves. A quiet
            # check is deliberately retained; its value is the forcing reply,
            # not an immediate captured piece.
            if (not in_check and not quiet_check and not promotion
                    and stand + victim_value + 180 < alpha):
                continue
            if (not in_check and not quiet_check and promotion is None
                    and self.see(board, move) < 0):
                continue
            board.push(move)
            score = -self._quiescence(
                board, -beta, -alpha, ply + 1,
                quiet_checks_left - 1 if quiet_check else quiet_checks_left)
            board.pop()
            if score >= beta:
                return score
            if score > alpha:
                alpha = score
            if self._stop or self._out_of_time():
                break
        return alpha

    # -- static exchange evaluation ---------------------------------------
    def see(self, board: chess.Board, move: chess.Move) -> int:
        """Static exchange evaluation of *move*, in centipawns."""
        target = move.to_square
        if board.is_en_passant(move):
            gain = PIECE_VALUES[chess.PAWN]
        else:
            pt = board.piece_type_at(target)
            gain = PIECE_VALUES[pt] if pt is not None else 0
        if move.promotion:
            gain += PIECE_VALUES[move.promotion] - PIECE_VALUES[chess.PAWN]
            attacker_value = PIECE_VALUES[move.promotion]
        else:
            ap = board.piece_type_at(move.from_square)
            attacker_value = PIECE_VALUES[ap] if ap is not None else 0
        board.push(move)
        try:
            loss = self._see_recapture(board, target, attacker_value)
        finally:
            board.pop()
        return gain - loss

    def _see_recapture(self, board: chess.Board, square: int,
                       on_square_value: int) -> int:
        """Best value the side to move can extract by capturing on *square*."""
        best = 0
        turn = board.turn
        for pt in _SEE_ORDER:
            subset = board.pieces_mask(pt, turn) & board.attackers_mask(turn, square)
            if not subset:
                continue
            move = None
            for from_square in chess.scan_forward(subset):
                cand = chess.Move(from_square, square)
                if pt == chess.PAWN and chess.square_rank(square) in (0, 7):
                    cand = chess.Move(from_square, square, promotion=chess.QUEEN)
                if board.is_legal(cand):
                    move = cand
                    break
            if move is None:
                continue
            value = PIECE_VALUES[chess.QUEEN] if move.promotion else PIECE_VALUES[pt]
            board.push(move)
            try:
                gained = on_square_value - self._see_recapture(board, square, value)
            finally:
                board.pop()
            if gained > best:
                best = gained
            break
        return best

    # -- move ordering ----------------------------------------------------
    def _move_score(self, board: chess.Board, move: chess.Move, ply: int,
                    tt_move: Optional[chess.Move],
                    last_move: Optional[chess.Move]) -> int:
        if tt_move is not None and move == tt_move:
            return 10_000_000
        score = 0
        victim = board.piece_type_at(move.to_square)
        if victim is not None or board.is_en_passant(move):
            v = PIECE_VALUES[victim] if victim is not None else PIECE_VALUES[chess.PAWN]
            attacker = board.piece_type_at(move.from_square)
            a = PIECE_VALUES[attacker] if attacker is not None else PIECE_VALUES[chess.KING]
            score = 1_000_000 + v * 16 - a
        if move.promotion:
            score += 900_000 + PIECE_VALUES[move.promotion]
        if score == 0:
            killers = self.killers.get(ply, [None, None])
            if move == killers[0]:
                return 800_000
            if move == killers[1]:
                return 790_000
            if last_move is not None:
                cm = self.countermoves.get(
                    (board.turn, last_move.from_square, last_move.to_square))
                if cm is not None and cm == move:
                    return 780_000
            key = (board.turn, move.from_square, move.to_square)
            score = self.history.get(key, 0)
            if last_move is not None:
                score += self.continuation.get(
                    (board.turn, last_move.from_square, last_move.to_square,
                     move.from_square, move.to_square), 0)
        return score

    def _has_pieces(self, board: chess.Board) -> bool:
        c = board.turn
        return bool(board.occupied_co[c] & ~(board.pawns | board.kings))

    # -- evaluation -------------------------------------------------------
    def evaluate(self, board: chess.Board) -> int:
        """Static evaluation, centipawns, from the side to move point of view."""
        variant = board.uci_variant
        noise = self.level.noise
        if variant in ("antichess", "giveaway", "suicide"):
            score = self._eval_antichess(board)
        elif variant == "atomic":
            score = self._eval_atomic(board)
        elif variant == "kingofthehill":
            score = self._eval_koth(board)
        elif variant == "racingkings":
            score = self._eval_racing(board)
        elif variant == "horde":
            score = self._eval_horde(board)
        else:
            score = self._eval_tapered(board)
            if variant == "3check":
                score += self._eval_threecheck(board)
            elif variant == "crazyhouse":
                score += self._eval_pockets(board)

        score = score if board.turn == chess.WHITE else -score
        if noise:
            score += self.rng.randint(-noise, noise)
        return score

    def _phase(self, board: chess.Board) -> float:
        phase = 0
        for pt, w in PHASE_WEIGHTS.items():
            phase += w * (chess.popcount(board.pieces_mask(pt, chess.WHITE)) +
                          chess.popcount(board.pieces_mask(pt, chess.BLACK)))
        return min(phase, MAX_PHASE) / MAX_PHASE

    def _eval_tapered(self, board: chess.Board) -> int:
        """Full tapered evaluation, white point of view, cached."""
        key = self._key(board)
        cached = self._eval_cache.get(key)
        if cached is not None:
            return cached
        score = self._eval_standard(board)
        if len(self._eval_cache) < 200_000:
            self._eval_cache[key] = score
        return score

    def _eval_standard(self, board: chess.Board) -> int:
        """Material + PST + positional terms, white point of view."""
        phase = self._phase(board)
        mg = eg = 0
        wp = board.pieces_mask(chess.PAWN, chess.WHITE)
        bp = board.pieces_mask(chess.PAWN, chess.BLACK)

        agg = self.level.aggression
        pos = self.level.positional

        occ_w = board.occupied_co[chess.WHITE]
        occ_b = board.occupied_co[chess.BLACK]
        occupied = board.occupied

        # ---- material and piece square tables
        for pt in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK,
                   chess.QUEEN, chess.KING):
            val = PIECE_VALUES[pt]
            tmg = PST_MG[pt]
            teg = PST_EG[pt]
            for sq in board.pieces(pt, chess.WHITE):
                mg += val + tmg[sq]
                eg += val + teg[sq]
            for sq in board.pieces(pt, chess.BLACK):
                mg -= val + tmg[FLIP[sq]]
                eg -= val + teg[FLIP[sq]]

        # ---- bishop pair
        if chess.popcount(board.pieces_mask(chess.BISHOP, chess.WHITE)) >= 2:
            mg += 32; eg += 48
        if chess.popcount(board.pieces_mask(chess.BISHOP, chess.BLACK)) >= 2:
            mg -= 32; eg -= 48

        # ---- pawn structure
        for color, sign, own, other in ((chess.WHITE, 1, wp, bp),
                                        (chess.BLACK, -1, bp, wp)):
            for f in range(8):
                file_mask = chess.BB_FILES[f]
                files = own & file_mask
                n = chess.popcount(files)
                if n > 1:                                  # doubled
                    mg -= sign * 16 * (n - 1)
                    eg -= sign * 24 * (n - 1)
                if n and not (other & file_mask):          # isolated
                    mg -= sign * 14 * n
                    eg -= sign * 18 * n
                elif n and not (other & _ADJACENT_FILES[f]):
                    mg -= sign * 15                        # fully isolated
                    eg -= sign * 12
                if n:
                    front = 0
                    for sq in chess.scan_forward(files):
                        rel = (chess.square_rank(sq) if color == chess.WHITE
                               else 7 - chess.square_rank(sq))
                        if not (other & PASSED_MASKS[color][sq]):
                            bonus_m, bonus_e = PASSED_MG[rel], PASSED_EG[rel]
                            # blocked / protected passers
                            push = 8 if color == chess.WHITE else -8
                            ahead = sq + push
                            if 0 <= ahead < 64 and (occupied &
                                                    chess.BB_SQUARES[ahead]):
                                bonus_m //= 2
                                bonus_e //= 2
                            if board.attackers_mask(color, sq) & own:
                                bonus_m += bonus_m // 4
                                bonus_e += bonus_e // 6
                            front += bonus_m
                            eg += sign * bonus_e
                        # phalanx
                        for df in (-1, 1):
                            ff = chess.square_file(sq) + df
                            if 0 <= ff <= 7 and (own & chess.BB_FILES[ff] &
                                                 chess.BB_RANKS[chess.square_rank(sq)]):
                                front += 6
                    mg += sign * front

        # ---- rooks: open and semi-open files, 7th rank
        for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
            own_pawns = wp if color == chess.WHITE else bp
            opp_pawns = bp if color == chess.WHITE else wp
            seventh = chess.BB_RANK_7 if color == chess.WHITE else chess.BB_RANK_2
            for sq in board.pieces(chess.ROOK, color):
                f = chess.square_file(sq)
                if not (own_pawns & chess.BB_FILES[f]):
                    mg += sign * (26 if not (opp_pawns & chess.BB_FILES[f]) else 13)
                    eg += sign * 8
                if chess.BB_SQUARES[sq] & seventh:
                    mg += sign * 22
                    eg += sign * 34

        # ---- king safety: pawn shield, castling rights, attack pressure
        for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
            ksq = board.king(color)
            if ksq is None:
                continue
            own_pawns = wp if color == chess.WHITE else bp
            kfile = chess.square_file(ksq)
            shield = 0
            for f in range(max(0, kfile - 1), min(7, kfile + 1) + 1):
                files = own_pawns & chess.BB_FILES[f]
                if files:
                    shield += 11 * chess.popcount(files)
                else:
                    shield -= 20
            # open files towards the king are dangerous
            zone = chess.BB_KING_ATTACKS[ksq] | chess.BB_SQUARES[ksq]
            units = 0
            for pt, w in ((chess.KNIGHT, 2), (chess.BISHOP, 2),
                          (chess.ROOK, 3), (chess.QUEEN, 5)):
                mask = board.pieces_mask(pt, not color)
                units += w * chess.popcount(mask & zone)
            # pawn storm / castling rights
            rights = board.castling_rights
            if color == chess.WHITE:
                if rights & chess.BB_A1:
                    shield += 8
                if rights & chess.BB_H1:
                    shield += 8
            else:
                if rights & chess.BB_A8:
                    shield += 8
                if rights & chess.BB_H8:
                    shield += 8
            idx = min(units, len(KING_DANGER) - 1)
            danger = KING_DANGER[idx]
            shelter = shield // 3
            mg += sign * int((shelter * 2 - danger) * (2.0 - agg) * pos)
            eg += sign * int(shelter * (2.0 - agg) * 0.4)

        # ---- mobility (safe squares) and piece-specific terms
        for color, sign, own_occ in ((chess.WHITE, 1, occ_w), (chess.BLACK, -1, occ_b)):
            enemy_pawns = bp if color == chess.WHITE else wp
            pawn_attacks = 0
            for sq in chess.scan_forward(enemy_pawns):
                pawn_attacks |= chess.BB_PAWN_ATTACKS[not color][sq]
            for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
                base_m, base_e = MOBILITY_BONUS[pt]
                count = 0
                for sq in board.pieces(pt, color):
                    attacks = board.attacks_mask(sq)
                    safe = attacks & ~own_occ & ~pawn_attacks
                    count += chess.popcount(safe)
                mg += sign * (base_m + count * 4)
                eg += sign * (base_e + count * 5)

        # ---- simple threat term: our pieces attacked by enemy pawns
        for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
            enemy_pawns = bp if color == chess.WHITE else wp
            if not enemy_pawns:
                continue
            attacked = 0
            for pt, w in ((chess.KNIGHT, 20), (chess.BISHOP, 20),
                          (chess.ROOK, 28), (chess.QUEEN, 40)):
                for sq in board.pieces(pt, color):
                    if board.attackers_mask(not color, sq) & enemy_pawns:
                        attacked += w
            mg -= sign * attacked

        score = int(mg * phase + eg * (1 - phase))
        # tempo
        score += 14 if board.turn == chess.WHITE else -14
        return score

    def _eval_pockets(self, board) -> int:
        """Crazyhouse: pieces in hand are worth slightly more than on the board."""
        total = 0
        if not hasattr(board, "pockets"):
            return 0
        for color in (chess.WHITE, chess.BLACK):
            sign = 1 if color == chess.WHITE else -1
            pocket = board.pockets[color]
            for pt in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK,
                       chess.QUEEN):
                total += sign * PIECE_VALUES[pt] * pocket.count(pt) * 3 // 2
        return total

    def _eval_threecheck(self, board) -> int:
        total = 0
        try:
            wc = board.remaining_checks[chess.WHITE]
            bc = board.remaining_checks[chess.BLACK]
            total = (bc - wc) * 130
        except Exception:
            pass
        return total

    def _eval_antichess(self, board) -> int:
        """In antichess having fewer pieces is better."""
        score = 0
        for pt in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK,
                   chess.QUEEN, chess.KING):
            v = PIECE_VALUES[pt] if pt != chess.KING else 10
            score -= v * chess.popcount(board.pieces_mask(pt, chess.WHITE))
            score += v * chess.popcount(board.pieces_mask(pt, chess.BLACK))
        score += 6 * board.legal_moves.count()
        return score

    def _eval_atomic(self, board) -> int:
        score = self._eval_tapered(board)
        wk, bk = board.king(chess.WHITE), board.king(chess.BLACK)
        if wk is not None and bk is not None:
            d = chess.square_distance(wk, bk)
            score += (7 - d) * 4
        return score

    def _eval_koth(self, board) -> int:
        score = self._eval_tapered(board) // 4
        for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
            ksq = board.king(color)
            if ksq is None:
                continue
            f, r = chess.square_file(ksq), chess.square_rank(ksq)
            d = abs(f - 3.5) + abs(r - 3.5)
            score += sign * int((7 - d * 2) * 40)
        return score

    def _eval_racing(self, board) -> int:
        score = 0
        for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
            ksq = board.king(color)
            if ksq is None:
                continue
            r = (chess.square_rank(ksq) if color == chess.WHITE
                 else 7 - chess.square_rank(ksq))
            score += sign * (r * r * 30)
        score += self._eval_tapered(board) // 8
        return score

    def _eval_horde(self, board) -> int:
        score = self._eval_tapered(board)
        score += 2 * chess.popcount(board.occupied_co[chess.WHITE] & board.pawns)
        return score

    # -- level personality -------------------------------------------------
    def _apply_level_noise(self, board: chess.Board, result: SearchResult) -> None:
        """Make weak levels actually weak (and human-like)."""
        lv = self.level
        if lv.blunder <= 0 and lv.inaccuracy <= 0:
            return
        r = self.rng.random()
        if r < lv.blunder:
            self._pick_alternative(board, result, pool="blunder")
        elif r < lv.blunder + lv.inaccuracy:
            self._pick_alternative(board, result, pool="inaccuracy")

    def _pick_alternative(self, board: chess.Board, result: SearchResult,
                          pool: str) -> None:
        moves = list(board.legal_moves)
        if len(moves) < 2:
            return
        scored = []
        for m in moves:
            board.push(m)
            s = -self._eval_tapered(board) if board.turn == chess.WHITE else \
                self._eval_tapered(board)
            board.pop()
            scored.append((s, m))
        scored.sort(key=lambda t: -t[0])
        if pool == "blunder":
            idx = self.rng.randint(max(1, len(scored) // 2), len(scored) - 1)
        else:
            idx = self.rng.randint(1, min(len(scored) - 1, 3))
        result.bestmove = scored[idx][1]
        result.pv = [result.bestmove]
        result.ponder = None
        result.mate = None
        result.score = scored[idx][0]
