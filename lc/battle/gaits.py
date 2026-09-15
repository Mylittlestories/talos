"""How each piece walks.

In the 1988 original the pieces are not chessmen sliding about: they are
small figures that walk, and each rank walks in its own way.  A knight
leaves the ground entirely, a rook comes down heavy, a bishop never quite
touches the floor, and the king waddles.  That difference is most of what
makes the board feel populated.

This table is that difference.  Every piece type has a gait: how many steps
it takes across the move, how high it lifts, how much it sways and leans,
whether it turns to face where it is going, and what it does on arrival.

Nothing here is an animation file - the motion is a handful of curves per
gait, evaluated against the fraction of the move completed, which is why
the whole mode still fits in a few hundred lines and needs no assets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import chess

__all__ = ["Gait", "GAITS", "gait_for", "all_gaits", "move_duration",
           "Idle", "IDLES", "idle_motion"]


@dataclass(frozen=True)
class Gait:
    """One way of crossing the board."""

    key: str                  # "stomp"
    piece: str                # "rook"
    name: str                 # "Stomp"
    line: str                 # what the walk looks like
    steps: int = 2            # paces taken over the whole move
    bob: float = 0.05         # how high it lifts, in board squares
    sway: float = 0.0         # side-to-side roll, radians
    lean: float = 0.0         # forward pitch, radians
    face: bool = True         # turn to face the direction of travel
    wobble: float = 0.10      # how far it wanders off that heading
    hop: float = 0.28         # vertical arc multiplier (leapers leave the ground)
    duration: float = 0.40    # seconds for a one-square move
    per_square: float = 0.30  # extra seconds per square beyond the first
    landing: str = ""         # "", "dust" or "thud"
    sound: str = "move"


P, N, B, R, Q, K = (chess.PAWN, chess.KNIGHT, chess.BISHOP,
                    chess.ROOK, chess.QUEEN, chess.KING)

GAITS: Dict[int, Gait] = {
    # ---- the pawn -------------------------------------------------------
    # Hurried little steps, head down, going where it is told.
    P: Gait(key="shuffle", piece="pawn", name="Shuffle",
            line="Hurried little steps, head down, leaning into the walk.",
            steps=4, bob=0.055, sway=0.05, lean=0.16, face=True, wobble=0.07,
            hop=0.30, duration=0.38, per_square=0.24, landing="dust"),
    # ---- the knight -----------------------------------------------------
    # The only piece that truly leaves the board: one arc, and a landing.
    N: Gait(key="leap", piece="knight", name="Leap",
            line="Leaves the ground altogether and lands facing his victim.",
            steps=1, bob=0.0, sway=0.0, lean=0.22, face=True, wobble=0.05,
            hop=1.15, duration=0.50, per_square=0.16, landing="thud",
            sound="gallop"),
    # ---- the bishop -----------------------------------------------------
    # Glides. His feet are not visible and he is not using them.
    B: Gait(key="glide", piece="bishop", name="Glide",
            line="Drifts across the board without ever quite touching it.",
            steps=1, bob=0.02, sway=0.10, lean=0.02, face=True, wobble=0.04,
            hop=0.10, duration=0.46, per_square=0.26),
    # ---- the rook -------------------------------------------------------
    # Stone, and heavy with it: two paces and a thud on each.
    R: Gait(key="stomp", piece="rook", name="Stomp",
            line="Two enormous paces, each one landing like a dropped wall.",
            steps=2, bob=0.075, sway=0.0, lean=0.05, face=True, wobble=0.03,
            hop=0.34, duration=0.52, per_square=0.30, landing="thud"),
    # ---- the queen ------------------------------------------------------
    # Unhurried, upright, and entirely sure of herself.
    Q: Gait(key="strut", piece="queen", name="Strut",
            line="Unhurried and upright; she is never in a hurry to arrive.",
            steps=3, bob=0.045, sway=0.12, lean=-0.04, face=True, wobble=0.05,
            hop=0.20, duration=0.50, per_square=0.28),
    # ---- the king -------------------------------------------------------
    # Slow, and listing to one side. He would rather not be walking at all.
    K: Gait(key="waddle", piece="king", name="Waddle",
            line="A slow waddle, listing to one side, as if the crown were heavy.",
            steps=3, bob=0.05, sway=0.18, lean=0.08, face=True, wobble=0.09,
            hop=0.26, duration=0.58, per_square=0.32, landing="dust"),
}

#: used when a piece has no gait of its own (variants, promoted pieces)
DEFAULT_GAIT = GAITS[P]


# --------------------------------------------------------------------------
# standing still
# --------------------------------------------------------------------------
# Between moves the board should not be frozen: the original's pieces shift
# their weight, paw the ground and look about. These are the amplitudes of
# that, in board squares and radians - deliberately small, so it reads as
# breathing rather than fidgeting.

@dataclass(frozen=True)
class Idle:
    """How a piece occupies itself when nothing is happening to it."""

    bob: float = 0.006        # vertical drift, board squares
    roll: float = 0.0         # side to side, radians
    pitch: float = 0.0        # fore and aft, radians
    yaw: float = 0.0          # looking about, radians
    period: float = 3.4       # seconds for one breath


IDLES: Dict[int, Idle] = {
    P: Idle(bob=0.006, roll=0.022, period=3.1),                # shifts weight
    N: Idle(bob=0.013, pitch=0.028, period=1.9),               # restless, paws
    B: Idle(bob=0.004, roll=0.014, period=4.2),                # sways slowly
    R: Idle(bob=0.002, roll=0.004, period=5.5),                # stone: barely
    Q: Idle(bob=0.008, yaw=0.055, period=3.8),                 # looks about
    K: Idle(bob=0.010, yaw=0.038, roll=0.012, period=2.6),     # fidgets
}

DEFAULT_IDLE = Idle()


def idle_motion(piece, t: float, phase: float = 0.0
                ) -> Tuple[float, float, float, float]:
    """(dy, dyaw, dpitch, droll) for a piece standing still at time *t*.

    *phase* is per piece, so the board does not breathe in unison. A second,
    slower harmonic is mixed in at a different rate: a single sine at one
    shared period reads as a metronome.
    """
    kind = piece.piece_type if isinstance(piece, chess.Piece) else int(piece)
    idle = IDLES.get(kind, DEFAULT_IDLE)
    w = 2.0 * math.pi / max(0.5, idle.period)
    swing = math.sin(w * t + phase)
    drift = math.sin(w * 0.43 * t + phase * 1.7)
    return (idle.bob * (0.7 * swing + 0.3 * drift),
            idle.yaw * drift,
            idle.pitch * swing,
            idle.roll * swing)


def gait_for(piece) -> Gait:
    """The gait for *piece* - a ``chess.Piece`` or a piece type."""
    kind = piece.piece_type if isinstance(piece, chess.Piece) else int(piece)
    return GAITS.get(kind, DEFAULT_GAIT)


def move_duration(gait: Gait, from_square: int, to_square: int) -> float:
    """How long this walk takes: further is slower, but not linearly.

    A knight's two-and-a-half squares should not take three times as long as
    a pawn's single step, so only part of the distance is charged for.
    """
    distance = chess.square_distance(from_square, to_square)
    return gait.duration * (1.0 + gait.per_square * max(0, distance - 1))


def all_gaits() -> List[Gait]:
    """Every gait, in board order."""
    return [GAITS[k] for k in (P, N, B, R, Q, K) if k in GAITS]


def gait_rows() -> List[Tuple[str, str, str]]:
    """(piece, name, line) for every gait - for the UI and the docs."""
    return [(g.piece, g.name, g.line) for g in all_gaits()]


def describe(piece) -> Optional[str]:
    gait = gait_for(piece)
    return f"{gait.piece} — {gait.name}: {gait.line}"
