"""
Anarchchess - the chess variant where the rules are no longer sacred.

Every rule below comes from the folklore of r/AnarchyChess and the community
implementations of it (anarchychess.org, itch.io, the "Anarchchess" bots).
Nothing here is invented: each flag carries the name the community uses.

Two presets ship with the game:

**Anarchchess** (curated)
    The famous, *playable* rules: forced en passant, knooks, the c4 bomb,
    double check wins, the king may never go to c2, Il Vaticano, the Siberian
    Swipe, vertical castling, the knight boost, dismounting, and radioactive
    queen decay.

**Full anarchy**
    Everything above plus the omnipotent pawn, promotion roulette, the
    hyper-accelerated Bongcloud instant win, and random per-turn events.

Implementation notes
--------------------
python-chess has exactly six piece types, so a **Knook** is stored as a rook
whose square is listed in ``board.knooks``; the board adds the knight attacks
and moves for those squares.  That keeps FEN, hashing, SAN and every existing
tool working while giving the piece its combined powers.

The non-standard moves (Il Vaticano, Siberian Swipe, vertical castling, the
knook fusion and dismounting) are encoded as promotions whose destination is
*not* on the back rank - something no legal promotion can ever be - so they
can never collide with a real move:

    ===============  ==========================  =========================
    promotion piece  move                        meaning
    ===============  ==========================  =========================
    pawn             ``XyXy`` (from == to)      dismount: knight -> pawn
    knight           ``from->to``               fuse into a knook
    bishop           ``b1->b2``                 Il Vaticano
    rook             ``r1->r2``                 Siberian Swipe
    king             ``k1->r1``                 vertical castling
    ===============  ==========================  =========================
"""

from __future__ import annotations

import random
from dataclasses import dataclass, asdict, replace
from typing import Dict, Iterator, List, Optional, Set, Tuple

import chess

C4 = chess.C4
C2 = chess.C2

PROMOTION_RANKS = (0, 7)

#: How the community calls each rule, and what it does here.
RULE_BOOK: List[Tuple[str, str, str]] = [
    ("en_passant_forced", "En passant is forced",
     "If en passant is on the table, you must take it - declining is not a move."),
    ("knooks", "Knooks",
     "Move a knight onto a friendly rook (or the other way round) and they "
     "fuse into a knook: rook and knight powers in one piece."),
    ("c4_bomb", "c4 is explosive",
     "The first piece to land on c4 detonates and kills everything in a one "
     "square radius - rooks and knooks shrug it off."),
    ("double_check_wins", "Double check is an instant win",
     "Give a double check and the game is over. (Pasta is optional.)"),
    ("king_no_c2", "The king cannot go to c2",
     "c2 is simply not available to a king, on either side of the board."),
    ("il_vaticano", "Il Vaticano",
     "Two friendly bishops three squares apart on a diagonal with enemy "
     "pieces between them swap places and everything in between is taken."),
    ("siberian_swipe", "Siberian Swipe",
     "An unmoved rook may take the enemy rook directly across the board on "
     "the same file, jumping over everything in between."),
    ("vertical_castle", "Vertical castling",
     "With a rook on the king's file and a clear path, castle vertically."),
    ("knight_boost", "Knight boost",
     "Promoting to a knight (or a knook) earns you an immediate extra move."),
    ("dismount", "Dismount",
     "After a knight has moved it may dismount and become a pawn."),
    ("queen_decay", "Radioactive queen decay",
     "Taking a queen irradiates the square: everything next to it dies too."),
    ("omnipotent_pawn", "Omnipotent pawn",
     "A pawn standing on h3 (white) or h8 (black) moves like any piece."),
    ("promotion_roulette", "Promotion roulette",
     "Promotions are random - and one time in five you get an enemy pawn."),
    ("bongcloud_wins", "Hyper-accelerated Bongcloud",
     "Play Ke2/Ke7 as your second move and win on the spot by asserting "
     "dominance."),
    ("random_events", "Random events",
     "Each turn something may happen: an earthquake, a conscription, a "
     "fireball or a revolution that topples a random piece."),
]


@dataclass
class AnarchRules:
    """The rule switches.  :data:`CURATED` and :data:`ANARCHY` are the presets."""
    en_passant_forced: bool = True
    knooks: bool = True
    c4_bomb: bool = True
    double_check_wins: bool = True
    king_no_c2: bool = True
    il_vaticano: bool = True
    siberian_swipe: bool = True
    vertical_castle: bool = True
    knight_boost: bool = True
    dismount: bool = True
    queen_decay: bool = True
    omnipotent_pawn: bool = False
    promotion_roulette: bool = False
    bongcloud_wins: bool = False
    random_events: bool = False

    def as_dict(self) -> Dict[str, bool]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "AnarchRules":
        base = cls()
        for key, value in (data or {}).items():
            if hasattr(base, key):
                setattr(base, key, bool(value))
        return base


CURATED = AnarchRules()
ANARCHY = AnarchRules(omnipotent_pawn=True, promotion_roulette=True,
                      bongcloud_wins=True, random_events=True)

PRESETS: Dict[str, AnarchRules] = {
    "anarchchess": CURATED,
    "anarchy": ANARCHY,
}

#: The rules actually used when a game starts.  The Anarchy menu edits these,
#: so a player can build their own house rulebook and keep it.
ACTIVE: Dict[str, AnarchRules] = {
    "anarchchess": replace(CURATED),
    "anarchy": replace(ANARCHY),
}


def active_rules(preset: str) -> AnarchRules:
    """The (possibly edited) rules for *preset*."""
    return ACTIVE.get(preset) or PRESETS.get(preset) or CURATED


def set_active_rules(preset: str, rules: AnarchRules) -> None:
    ACTIVE[preset] = rules


def reset_active_rules() -> None:
    ACTIVE.clear()
    ACTIVE["anarchchess"] = replace(CURATED)
    ACTIVE["anarchy"] = replace(ANARCHY)

#: Names used by the SAN printer for the special moves.
SPECIAL_NAMES = {
    chess.PAWN: "dismount",
    chess.KNIGHT: "knook",
    chess.BISHOP: "Il Vaticano",
    chess.ROOK: "Siberian Swipe",
    chess.KING: "vertical castle",
}


class _BoardSnapshot:
    """A minimal replacement for python-chess' private ``_BoardState``.

    Special moves mutate the bitboards directly instead of going through
    ``Board.push``, so the board has to remember and restore its own state for
    the move stack to stay consistent.
    """

    __slots__ = ("pawns", "knights", "bishops", "rooks", "queens", "kings",
                 "promoted", "occupied", "occupied_w", "occupied_b", "turn",
                 "castling_rights", "ep_square", "halfmove_clock",
                 "fullmove_number")

    def __init__(self, board: "AnarchBoard") -> None:
        self.pawns = board.pawns
        self.knights = board.knights
        self.bishops = board.bishops
        self.rooks = board.rooks
        self.queens = board.queens
        self.kings = board.kings
        self.promoted = getattr(board, "promoted", 0)
        self.occupied = board.occupied
        self.occupied_w = board.occupied_co[chess.WHITE]
        self.occupied_b = board.occupied_co[chess.BLACK]
        self.turn = board.turn
        self.castling_rights = board.castling_rights
        self.ep_square = board.ep_square
        self.halfmove_clock = board.halfmove_clock
        self.fullmove_number = board.fullmove_number

    def restore(self, board: "AnarchBoard") -> None:
        board.pawns = self.pawns
        board.knights = self.knights
        board.bishops = self.bishops
        board.rooks = self.rooks
        board.queens = self.queens
        board.kings = self.kings
        if hasattr(board, "promoted"):
            board.promoted = self.promoted
        board.occupied_co[chess.WHITE] = self.occupied_w
        board.occupied_co[chess.BLACK] = self.occupied_b
        board.occupied = self.occupied
        board.turn = self.turn
        board.castling_rights = self.castling_rights
        board.ep_square = self.ep_square
        board.halfmove_clock = self.halfmove_clock
        board.fullmove_number = self.fullmove_number


def is_special(move: chess.Move) -> bool:
    """True for the encoded anarchic moves (see the module docstring)."""
    if move.promotion is None or move.promotion == chess.QUEEN:
        return False
    if move.from_square == move.to_square:
        return True
    return chess.square_rank(move.to_square) not in PROMOTION_RANKS


class AnarchBoard(chess.Board):
    """A chess board that plays by the anarchic rulebook."""

    aliases = ["Anarchchess", "Anarchy"]
    uci_variant = "chess"
    starting_fen = chess.STARTING_FEN

    def __init__(self, fen: Optional[str] = None, rules: Optional[AnarchRules] = None,
                 chess960: bool = False, seed: Optional[int] = None):
        super().__init__(fen or chess.STARTING_FEN, chess960=chess960)
        self.rules = rules or AnarchRules()
        self.rng = random.Random(seed)
        self.knooks: Set[chess.Square] = set()
        self.c4_used = False
        self.extra_turn = False
        self.bongcloud_winner: Optional[bool] = None
        self.last_event: Optional[str] = None
        self._anarch_stack: List[Tuple] = []

    # ------------------------------------------------------------------
    # state stacking
    # ------------------------------------------------------------------
    def _anarch_state(self) -> Tuple:
        return (frozenset(self.knooks), self.c4_used, self.extra_turn,
                self.bongcloud_winner, self.last_event)

    def _restore_anarch(self, state: Tuple) -> None:
        (self.knooks, self.c4_used, self.extra_turn,
         self.bongcloud_winner, self.last_event) = state
        self.knooks = set(self.knooks)
        self.extra_turn = bool(self.extra_turn)

    def reset(self) -> None:
        # NOTE: python-chess calls reset() from Board.__init__, before this
        # subclass has set anything up, so every attribute is (re)assigned here
        # rather than mutated.
        super().reset()
        self.knooks: Set[chess.Square] = set()
        self.c4_used = False
        self.extra_turn = False
        self.bongcloud_winner = None
        self.last_event = None
        self._anarch_stack: List[Tuple] = []

    def copy(self, stack: bool = True) -> "AnarchBoard":
        board = super().copy(stack=stack)
        board.rules = self.rules
        board.rng = self.rng
        board.knooks = set(self.knooks)
        board.c4_used = self.c4_used
        board.extra_turn = self.extra_turn
        board.bongcloud_winner = self.bongcloud_winner
        board.last_event = self.last_event
        board._anarch_stack = [tuple(s) for s in self._anarch_stack]
        return board

    def _transposition_key(self):
        key = super()._transposition_key()
        return (key, frozenset(self.knooks), self.c4_used, self.extra_turn,
                self.bongcloud_winner)

    # ------------------------------------------------------------------
    # attack masks (knooks hit like knights too)
    # ------------------------------------------------------------------
    def attackers_mask(self, color: chess.Color, square: chess.Square,
                       occupied: Optional[chess.Bitboard] = None) -> chess.Bitboard:
        mask = super().attackers_mask(color, square, occupied)
        if self.rules.knooks and self.knooks:
            ours = self.occupied_co[color] if occupied is None else occupied
            for sq in self.knooks:
                if not (chess.BB_SQUARES[sq] & ours):
                    continue
                if chess.BB_KNIGHT_ATTACKS[sq] & chess.BB_SQUARES[square]:
                    mask |= chess.BB_SQUARES[sq]
        return mask

    def _knook_moves(self, square: chess.Square) -> chess.Bitboard:
        return chess.BB_KNIGHT_ATTACKS[square] & ~self.occupied_co[self.turn]

    # ------------------------------------------------------------------
    # move generation
    # ------------------------------------------------------------------
    def generate_pseudo_legal_moves(self, from_mask=chess.BB_ALL,
                                    to_mask=chess.BB_ALL) -> Iterator[chess.Move]:
        yield from super().generate_pseudo_legal_moves(from_mask, to_mask)

        rules = self.rules
        our = self.occupied_co[self.turn]

        # ---- knooks: extra knight moves
        if rules.knooks:
            for sq in sorted(self.knooks):
                if not (chess.BB_SQUARES[sq] & from_mask & our):
                    continue
                for target in chess.scan_forward(self._knook_moves(sq) & to_mask):
                    yield chess.Move(sq, target)

        # ---- knook fusion: knight onto a friendly rook (and back)
        if rules.knooks:
            knights = self.knights & our & from_mask
            rooks = self.rooks & our & to_mask
            for ksq in chess.scan_forward(knights):
                if ksq in self.knooks:
                    continue
                for rsq in chess.scan_forward(
                        rooks & chess.BB_KNIGHT_ATTACKS[ksq]):
                    yield chess.Move(ksq, rsq, promotion=chess.KNIGHT)
            for rsq in chess.scan_forward(rooks & from_mask):
                if rsq in self.knooks:
                    continue
                for ksq in chess.scan_forward(
                        (self.knights & our & to_mask) & chess.BB_KNIGHT_ATTACKS[rsq]):
                    yield chess.Move(rsq, ksq, promotion=chess.KNIGHT)

        # ---- the omnipotent pawn
        if rules.omnipotent_pawn:
            home = chess.H3 if self.turn == chess.WHITE else chess.H8
            if (chess.BB_SQUARES[home] & self.pawns & our & from_mask):
                attacks = self.attacks_mask(home)
                for target in chess.scan_forward(attacks & ~our & to_mask):
                    yield chess.Move(home, target)

        # ---- dismount (knight -> pawn, after it has moved)
        if rules.dismount:
            for sq in chess.scan_forward(self.knights & our & from_mask):
                if sq in self.knooks:
                    continue
                yield chess.Move(sq, sq, promotion=chess.PAWN)

        # ---- specials
        yield from self._specials(from_mask, to_mask)

    def _specials(self, from_mask, to_mask) -> Iterator[chess.Move]:
        rules = self.rules
        our = self.occupied_co[self.turn]
        if rules.il_vaticano:
            bishops = list(chess.scan_forward(self.bishops & our))
            for i, a in enumerate(bishops):
                if not (chess.BB_SQUARES[a] & from_mask):
                    continue
                for b in bishops[i + 1:]:
                    if not (chess.BB_SQUARES[b] & to_mask):
                        continue
                    if chess.square_distance(a, b) != 3:
                        continue
                    between = chess.between(a, b)
                    if not between or (between & self.occupied) != between:
                        continue
                    if not (between & self.occupied_co[not self.turn]):
                        continue
                    yield chess.Move(a, b, promotion=chess.BISHOP)
        if rules.siberian_swipe:
            for sq in chess.scan_forward(self.rooks & our & from_mask):
                file_mask = chess.BB_FILES[chess.square_file(sq)]
                for target in chess.scan_forward(
                        self.rooks & self.occupied_co[not self.turn] & to_mask
                        & file_mask):
                    if not self._rook_untouched(sq) or not self._rook_untouched(target):
                        continue
                    if chess.between(sq, target) & ~self.occupied:
                        continue
                    yield chess.Move(sq, target, promotion=chess.ROOK)
        if rules.vertical_castle:
            ksq = self.king(self.turn)
            if ksq is not None and (chess.BB_SQUARES[ksq] & from_mask) \
                    and self.has_castling_rights(self.turn):
                file_mask = chess.BB_FILES[chess.square_file(ksq)]
                for rsq in chess.scan_forward(
                        self.rooks & our & to_mask & file_mask):
                    if rsq in self.knooks:
                        continue
                    if chess.between(ksq, rsq) & self.occupied:
                        continue
                    yield chess.Move(ksq, rsq, promotion=chess.KING)

    def _rook_untouched(self, square: chess.Square) -> bool:
        """A rook still on its home corner counts as unmoved."""
        home = chess.BB_A1 | chess.BB_H1 | chess.BB_A8 | chess.BB_H8
        return bool(chess.BB_SQUARES[square] & home)

    # ------------------------------------------------------------------
    def generate_legal_moves(self, from_mask=chess.BB_ALL,
                             to_mask=chess.BB_ALL) -> Iterator[chess.Move]:
        if self.is_variant_end():
            return
        moves = list(super().generate_legal_moves(from_mask, to_mask))
        # An earthquake or a c4 detonation can expose a king that was safe a
        # moment ago.  Eaten kings are not a thing: the capture is struck from
        # the move list, so the exposed side is simply in check and loses if it
        # cannot get out of it.
        enemy_king = self.king(not self.turn)
        if enemy_king is not None:
            moves = [m for m in moves if m.to_square != enemy_king]
        if self.rules.king_no_c2:
            king = self.king(self.turn)
            if king is not None:
                moves = [m for m in moves
                         if not (m.from_square == king and m.to_square == C2)]
        if self.rules.en_passant_forced and self.ep_square is not None:
            forced = [m for m in moves if self.is_en_passant(m)]
            if forced:
                moves = forced
        if self.rules.dismount:
            # dismounting is only legal right after the knight has moved
            last = self.move_stack[-1] if self.move_stack else None
            if last is None or self.piece_type_at(last.to_square) != chess.KNIGHT \
                    or last.from_square == last.to_square:
                moves = [m for m in moves if not (m.from_square == m.to_square)]
        yield from moves

    # ------------------------------------------------------------------
    # making moves
    # ------------------------------------------------------------------
    def push(self, move: chess.Move) -> None:
        self._anarch_stack.append(self._anarch_state())
        try:
            mover = self.turn
            if is_special(move):
                captured = self.piece_type_at(move.to_square)
                self._stack.append(_BoardSnapshot(self))
                self.move_stack.append(move)
                self._apply_special(move)
                self._post(move, mover, captured, flipped=False)
            else:
                from_sq, to_sq = move.from_square, move.to_square
                captured = self.piece_type_at(to_sq)
                if self.is_en_passant(move):
                    captured = chess.PAWN
                was_knook = from_sq in self.knooks
                super().push(move)
                self.knooks.discard(from_sq)
                self.knooks.discard(to_sq)
                if self.is_en_passant(move):
                    victim = (to_sq - 8) if mover == chess.WHITE else (to_sq + 8)
                    self.knooks.discard(victim)
                if was_knook and self.piece_type_at(to_sq) == chess.ROOK:
                    self.knooks.add(to_sq)
                boosted = False
                if self.rules.promotion_roulette and move.promotion is not None:
                    boosted = self._roulette(to_sq)
                self._post(move, mover, captured, flipped=True,
                           promoted_knight=boosted)
        except Exception:
            self._anarch_stack.pop()
            raise

    def pop(self) -> chess.Move:
        move = super().pop()
        if self._anarch_stack:
            self._restore_anarch(self._anarch_stack.pop())
        return move

    # ------------------------------------------------------------------
    # Direct position editing.  python-chess' own remove_piece_at/set_piece_at
    # call clear_stack(), which would throw away the whole game history every
    # time an anarchic effect fires, so the bitboards are edited here instead.
    # ------------------------------------------------------------------
    def _drop(self, square: chess.Square) -> Optional[int]:
        mask = chess.BB_SQUARES[square]
        if not (self.occupied & mask):
            return None
        piece_type = self.piece_type_at(square)
        if piece_type == chess.PAWN:
            self.pawns ^= mask
        elif piece_type == chess.KNIGHT:
            self.knights ^= mask
        elif piece_type == chess.BISHOP:
            self.bishops ^= mask
        elif piece_type == chess.ROOK:
            self.rooks ^= mask
        elif piece_type == chess.QUEEN:
            self.queens ^= mask
        elif piece_type == chess.KING:
            self.kings ^= mask
        self.occupied ^= mask
        self.occupied_co[chess.WHITE] &= ~mask
        self.occupied_co[chess.BLACK] &= ~mask
        self.promoted &= ~mask
        self.castling_rights &= ~mask
        self.knooks.discard(square)
        return piece_type

    def _place(self, square: chess.Square, piece: chess.Piece) -> None:
        mask = chess.BB_SQUARES[square]
        if piece.piece_type == chess.PAWN:
            self.pawns |= mask
        elif piece.piece_type == chess.KNIGHT:
            self.knights |= mask
        elif piece.piece_type == chess.BISHOP:
            self.bishops |= mask
        elif piece.piece_type == chess.ROOK:
            self.rooks |= mask
        elif piece.piece_type == chess.QUEEN:
            self.queens |= mask
        elif piece.piece_type == chess.KING:
            self.kings |= mask
        self.occupied |= mask
        self.occupied_co[piece.color] |= mask
        if piece.piece_type == chess.KING:
            self.castling_rights &= ~mask

    # ------------------------------------------------------------------
    def _apply_special(self, move: chess.Move) -> None:
        kind = move.promotion
        src, dst = move.from_square, move.to_square

        if kind == chess.PAWN and src == dst:                 # dismount
            self._drop(src)
            self._place(src, chess.Piece(chess.PAWN, self.turn))
            return

        if kind == chess.KNIGHT:                              # knook fusion
            # python-chess has only six piece types, so the fused piece is
            # carried in the rook bitboard and remembered in ``self.knooks``;
            # that gives it the rook's moves for free and the knight's moves
            # from generate_pseudo_legal_moves().
            self._drop(dst)
            self._drop(src)
            self._place(dst, chess.Piece(chess.ROOK, self.turn))
            self.knooks.discard(src)
            self.knooks.add(dst)
            return

        if kind == chess.BISHOP:                              # Il Vaticano
            for sq in chess.scan_forward(chess.between(src, dst)):
                self._drop(sq)
            a = self.piece_at(src)
            b = self.piece_at(dst)
            self._drop(src)
            self._drop(dst)
            self._place(dst, a)
            self._place(src, b)
            return

        if kind == chess.ROOK:                                # Siberian Swipe
            self._drop(dst)
            rook = self.piece_at(src)
            self._drop(src)
            self._place(dst, rook)
            return

        if kind == chess.KING:                                # vertical castling
            king = self.piece_at(src)
            rook = self.piece_at(dst)
            rank = chess.square_rank(src)
            step = 1 if chess.square_rank(dst) > rank else -1
            self._drop(src)
            self._drop(dst)
            self._place(chess.square(chess.square_file(src), rank + step), king)
            self._place(src, rook)
            self.castling_rights &= ~chess.BB_SQUARES[src]
            return

        raise ValueError(f"unknown anarchic move {move.uci()}")

    def _roulette(self, square: chess.Square) -> bool:
        """Promotion roulette.  Returns True when the piece became a knight."""
        table = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]
        piece = table[self.rng.randrange(len(table))]
        self._drop(square)
        if self.rng.random() < 0.2:
            self._place(square, chess.Piece(chess.PAWN, not self.turn))
            return False
        self._place(square, chess.Piece(piece, self.turn))
        return piece == chess.KNIGHT

    def _post(self, move: chess.Move, mover: chess.Color,
              captured: Optional[int], flipped: bool,
              promoted_knight: bool = False) -> None:
        """Effects, counters and the (possibly repeated) turn change."""
        # ---- radioactive queen decay
        if self.rules.queen_decay and captured == chess.QUEEN:
            for sq in chess.scan_forward(
                    chess.BB_KING_ATTACKS[move.to_square] & self.occupied):
                piece = self.piece_at(sq)
                if piece is None or piece.piece_type in (chess.KING, chess.QUEEN):
                    continue
                self._drop(sq)
        # ---- the c4 detonation
        if self.rules.c4_bomb and not self.c4_used and move.to_square == C4:
            self.c4_used = True
            for sq in chess.scan_forward(
                    (chess.BB_KING_ATTACKS[C4] | chess.BB_SQUARES[C4])
                    & self.occupied):
                piece = self.piece_at(sq)
                if piece is None or piece.piece_type == chess.KING:
                    continue
                if piece.piece_type == chess.ROOK:      # rooks and knooks shrug
                    continue
                self._drop(sq)
        # ---- hyper-accelerated bongcloud
        if (self.rules.bongcloud_wins and self.bongcloud_winner is None
                and self.fullmove_number == 2
                and self.piece_type_at(move.to_square) == chess.KING):
            target = chess.E2 if mover == chess.WHITE else chess.E7
            if move.to_square == target:
                self.bongcloud_winner = mover

        if not flipped:
            # special moves do not go through Board.push(), so they have to
            # move the clock on themselves.  A normal move has already set the
            # en passant square - never clear it here.
            self.ep_square = None
            self.turn = not self.turn
            self.halfmove_clock += 1
            if self.turn == chess.WHITE:
                self.fullmove_number += 1

        boost = self.rules.knight_boost and (
            promoted_knight or
            (move.promotion == chess.KNIGHT
             and chess.square_rank(move.to_square) in PROMOTION_RANKS))
        if boost:
            self.extra_turn = True
            self.turn = mover                 # the same side moves again
            if mover == chess.BLACK:
                self.fullmove_number -= 1
            self.halfmove_clock = max(0, self.halfmove_clock - 1)
            self.last_event = None
            return

        self.extra_turn = False
        self.last_event = (self._roll_event()
                           if self.rules.random_events else None)

    def _roll_event(self) -> Optional[str]:
        if self.rng.random() > 0.12:
            return None
        event = ["earthquake", "conscription", "fireball", "fog"][
            self.rng.randrange(4)]
        occupied = list(chess.scan_forward(self.occupied))
        if event == "earthquake" and occupied:
            sq = occupied[self.rng.randrange(len(occupied))]
            piece = self.piece_at(sq)
            if piece is not None and piece.piece_type != chess.KING:
                self._drop(sq)
        elif event == "conscription":
            empty = list(chess.scan_forward(~self.occupied & chess.BB_ALL))
            if empty:
                sq = empty[self.rng.randrange(len(empty))]
                self._place(sq, chess.Piece(chess.PAWN, self.turn))
        elif event == "fireball":
            pawns = list(chess.scan_forward(
                self.pawns & self.occupied_co[not self.turn]))
            if pawns:
                self._drop(pawns[self.rng.randrange(len(pawns))])
        return event

    # ------------------------------------------------------------------
    # result handling
    # ------------------------------------------------------------------
    def is_double_check(self) -> bool:
        king = self.king(self.turn)
        if king is None:
            return False
        return chess.popcount(self.attackers_mask(not self.turn, king)) >= 2

    def is_variant_end(self) -> bool:
        return self.is_variant_win() or self.is_variant_loss()

    def is_variant_win(self) -> bool:
        if self.bongcloud_winner is not None:
            return self.bongcloud_winner == self.turn
        return self.king(not self.turn) is None

    def is_variant_loss(self) -> bool:
        if self.bongcloud_winner is not None:
            return self.bongcloud_winner != self.turn
        if self.king(self.turn) is None:
            return True
        if self.rules.double_check_wins and self.is_double_check():
            return True
        return False

    def is_checkmate(self) -> bool:
        if self.is_variant_loss():
            return True
        return super().is_checkmate()

    def is_stalemate(self) -> bool:
        if self.is_variant_end():
            return False
        return super().is_stalemate()

    def is_game_over(self, claim_draw: bool = False) -> bool:
        if self.is_variant_end():
            return True
        return super().is_game_over(claim_draw=claim_draw)

    def result(self, claim_draw: bool = False) -> str:
        if self.is_variant_win():
            return "1-0" if self.turn == chess.WHITE else "0-1"
        if self.is_variant_loss():
            return "0-1" if self.turn == chess.WHITE else "1-0"
        return super().result(claim_draw=claim_draw)

    # ------------------------------------------------------------------
    # notation
    # ------------------------------------------------------------------
    def san(self, move: chess.Move) -> str:
        if is_special(move):
            return SPECIAL_NAMES.get(move.promotion or 0, "anarchy")
        return super().san(move)

    def parse_san(self, san: str) -> chess.Move:
        text = san.strip().rstrip("+#?!")
        lowered = text.lower()
        for code, name in SPECIAL_NAMES.items():
            if lowered == name.lower() or lowered == name.lower().replace(" ", ""):
                for move in self.legal_moves:
                    if move.promotion == code and is_special(move):
                        return move
        return super().parse_san(san)

    def is_knook(self, square: chess.Square) -> bool:
        return square in self.knooks

    def status_line(self) -> str:
        bits = []
        if self.bongcloud_winner is not None:
            bits.append("Bongcloud dominance")
        if self.rules.double_check_wins and self.is_double_check():
            bits.append("Double check!")
        if self.last_event:
            bits.append(f"event: {self.last_event}")
        if self.knooks:
            bits.append(f"{len(self.knooks)} knook(s)")
        return " - ".join(bits)


def make_board(preset: str = "anarchchess", rules: Optional[Dict] = None) -> AnarchBoard:
    """Build a board for one of the two presets (honouring the active rules)."""
    base = active_rules(preset)
    if rules:
        base = replace(base, **{k: bool(v) for k, v in rules.items()
                                if hasattr(base, k)})
    return AnarchBoard(rules=base)
