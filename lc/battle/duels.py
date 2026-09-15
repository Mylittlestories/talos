"""The thirty duels of Battle Chess.

The 1988 original did not have one capture animation with the pieces swapped
about: *"There is a different animation for each permutation, depending on
which pieces are capturing or being captured."*  A knight taking a knight cuts
his enemy limb from limb; a knight facing the queen dodges her magic and
turns it against her.  Thirty-odd little murders, each one written for the
pair of pieces in it.

This module is that list.  Every entry names the duel, picks how the attacker
moves (``style``), how the victim dies (``choreo``), how long each beat of the
fight lasts, and what is left on the square afterwards.  Two invariants are
checked by the test suite:

* every (attacker, victim) pair a game can produce has an entry - six pieces
  can capture, five can be captured (a king is never taken), so thirty duels;
* no two entries share a (style, choreo) pair, so no two captures are the
  same animation wearing a different hat.

The tone is the 1988 one: stylised, darkly comic, never gratuitous.  The
``gore`` setting on the widget decides how far the mess goes, not this table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import chess

__all__ = ["Duel", "DUELS", "duel_for", "all_duels", "duel_rows", "PIECE_LETTER",
           "PIECE_NAME", "STYLES", "CHOREOS", "DUEL_COUNT"]


@dataclass(frozen=True)
class Duel:
    """One permutation of attacker and victim."""

    key: str                  # "NxQ"
    name: str                 # "Deflect"
    line: str                 # what happens, in one line
    style: str                # how the attacker moves
    choreo: str               # how the victim dies
    approach: float = 0.42    # seconds: closing on the victim
    strike: float = 0.34      # seconds: winding up and landing the blow
    impact: float = 0.14      # seconds: the blow itself
    recover: float = 0.42     # seconds: walking to the square
    debris: str = "blood"     # blood | dust | spark | glass | rubble
    shake: float = 0.8        # camera shake, 0..1
    sound: str = "clash"

    @property
    def duration(self) -> float:
        return self.approach + self.strike + self.impact + self.recover


PIECE_LETTER = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B",
                chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K"}
PIECE_NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
              chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}

#: How an attacker can move (consumed by the fight's strike beat).
STYLES = ("stab", "slash", "beam", "smash", "shock", "hammer",
          "club", "pounce", "charge", "hex", "swing", "crush")
#: How a victim can die (consumed by the victim and impact beats).
CHOREOS = ("topple", "crumble", "shatter", "flatten", "behead", "burst",
           "dismember", "spin", "melt", "disintegrate", "impale", "crush")


def _sound_for(style: str, choreo: str) -> str:
    """The cue a duel plays when the blow lands.

    Derived from the animation rather than listed per entry: blades ring,
    heavy things thud, and anything that comes apart shatters.
    """
    if choreo in ("shatter", "dismember", "burst", "crumble", "crush"):
        return "shatter"
    if style in ("slash", "stab"):
        return "sword"
    if style in ("smash", "hammer", "club", "crush", "swing", "charge", "pounce"):
        return "thud"
    return "clash"


def _d(attacker: int, victim: int, name: str, line: str, style: str,
       choreo: str, **kw) -> Tuple[Tuple[int, int], "Duel"]:
    kw.setdefault("sound", _sound_for(style, choreo))
    return (attacker, victim), Duel(
        key=f"{PIECE_LETTER[attacker]}x{PIECE_LETTER[victim]}",
        name=name, line=line, style=style, choreo=choreo, **kw)


P, N, B, R, Q, K = (chess.PAWN, chess.KNIGHT, chess.BISHOP,
                    chess.ROOK, chess.QUEEN, chess.KING)

DUELS: Dict[Tuple[int, int], Duel] = dict([

    # ------------------------------------------------------------ the pawns
    # Small, earthy, and utterly without dignity: they grapple, trip and
    # clobber. Whatever they do, they do it from below.
    _d(P, P, "Scuffle", "Two little ones grapple at close quarters and one "
       "goes over like a skittle.", "stab", "topple",
       approach=0.34, strike=0.22, debris="dust", shake=0.35, sound="clash"),
    _d(P, N, "Hamstring", "He goes in low and the horse folds at the knee.",
       "stab", "crumble", approach=0.36, strike=0.24, debris="blood",
       shake=0.6),
    _d(P, B, "Sacrilege", "A swing of the censer and the bishop comes apart "
       "in shards of glass.", "club", "shatter", debris="glass", shake=0.7),
    _d(P, R, "Undermine", "He hits the base and the tower drops flat on its "
       "own footprint.", "club", "flatten", debris="rubble", shake=0.9),
    _d(P, Q, "Regicide", "He climbs her, and comes down with her crown.",
       "pounce", "behead", approach=0.5, strike=0.4, debris="blood",
       shake=1.0),

    # ----------------------------------------------------------- the knight
    # The sword arm of the board. Everything he does is fast and final.
    _d(N, P, "Ride down", "The horse rides straight over the little one "
       "without breaking stride.", "slash", "burst", approach=0.46,
       strike=0.18, debris="blood", shake=0.55),
    _d(N, N, "Duel", "Cut his enemy limb from limb, and leave the pieces "
       "where they fall.", "slash", "dismember", strike=0.4, impact=0.2,
       debris="blood", shake=1.0),
    _d(N, B, "Unhood", "The mitre spins one way and the head goes the other.",
       "slash", "spin", debris="blood", shake=0.7),
    _d(N, R, "Storm", "He takes the tower apart stone by stone from the "
       "saddle.", "charge", "crumble", approach=0.6, strike=0.3,
       debris="rubble", shake=0.85),
    _d(N, Q, "Deflect", "He dodges her magic, turns it aside, and she comes "
       "undone by her own spell.", "charge", "melt", approach=0.55,
       strike=0.36, debris="spark", shake=0.8),

    # ----------------------------------------------------------- the bishop
    # Never touches his victim. Light, and a word.
    _d(B, P, "Smite", "A finger of light, and the little one is simply not "
       "there any more.", "beam", "disintegrate", approach=0.3,
       strike=0.44, debris="spark", shake=0.4),
    _d(B, N, "Unhorse", "The horse rears at the glare and goes over "
       "backwards.", "beam", "topple", debris="spark", shake=0.5),
    _d(B, B, "Schism", "Heresy answered with heresy: the rival comes apart "
       "in shards.", "beam", "shatter", debris="glass", shake=0.6),
    _d(B, R, "Sunder", "The tower grinds itself to rubble at a word.",
       "hex", "crumble", approach=0.34, strike=0.5, debris="rubble",
       shake=0.7),
    _d(B, Q, "Exorcise", "Her own magic boils over and she runs like wax.",
       "hex", "melt", approach=0.34, strike=0.48, debris="spark",
       shake=0.65),

    # ------------------------------------------------------------- the rook
    # Weight. Nothing clever, nothing quick.
    _d(R, P, "Swat", "The tower swats him flat as a coin and does not look.",
       "smash", "flatten", approach=0.4, strike=0.28, debris="dust",
       shake=0.75),
    _d(R, N, "Trample", "Stone hooves: the horse is driven down into the "
       "square.", "smash", "crumble", debris="rubble", shake=0.9),
    _d(R, B, "Fell the steeple", "One sweep and the bishop goes over "
       "sideways.", "swing", "topple", approach=0.38, strike=0.3,
       debris="dust", shake=0.7),
    _d(R, R, "Batter", "Tower against tower. Both crumble; only one is left "
       "standing.", "swing", "crumble", strike=0.42, debris="rubble",
       shake=1.0),
    _d(R, Q, "Crush", "The stone comes down and spreads her across the "
       "square.", "crush", "flatten", approach=0.44, strike=0.4,
       debris="blood", shake=1.0),

    # ------------------------------------------------------------ the queen
    # Magic, and a temper. She rarely needs to raise a hand.
    _d(Q, P, "Scorn", "She barely looks at him, and he is gone.",
       "shock", "disintegrate", approach=0.28, strike=0.4, debris="spark",
       shake=0.45),
    _d(Q, N, "Unseat", "She catches him mid-charge and throws him clear of "
       "the board.", "shock", "spin", debris="blood", shake=0.7),
    _d(Q, B, "Silence", "She hushes the preaching one; the glass goes with "
       "him.", "shock", "shatter", debris="glass", shake=0.6),
    _d(Q, R, "Wrath", "The tower comes apart at a word she does not bother "
       "to finish.", "shock", "crumble", debris="rubble", shake=0.9),
    _d(Q, Q, "Mirror", "Two queens, one spell. The slower one runs like wax.",
       "shock", "melt", approach=0.32, strike=0.46, debris="spark",
       shake=0.8),

    # -------------------------------------------------------------- the king
    # Rarely fights, and badly - a heavy man with a sceptre, swinging it like
    # a club. When he does take something, it stays taken.
    _d(K, P, "Backhand", "A royal backhand sends the little one rolling.",
       "hammer", "topple", approach=0.4, strike=0.3, debris="dust",
       shake=0.5),
    _d(K, N, "Sceptre", "One blow of the sceptre and the horse folds.",
       "hammer", "crumble", debris="blood", shake=0.85),
    _d(K, B, "Crown", "He crowns him with the mace and the mitre bursts.",
       "swing", "shatter", debris="glass", shake=0.75),
    _d(K, R, "Demolish", "He has his own tower pulled down on top of it.",
       "crush", "crumble", approach=0.46, strike=0.42, debris="rubble",
       shake=1.0),
    _d(K, Q, "Abdication", "The last queen loses her head to the crown.",
       "hammer", "behead", approach=0.48, strike=0.44, debris="blood",
       shake=1.0),
])

DUEL_COUNT = len(DUELS)


def duel_for(attacker, victim) -> Duel:
    """The duel for *attacker* capturing *victim*.

    Accepts pieces or piece types.  Kings are never captured in a legal game,
    so a king victim falls back on how the attacker would take a queen -
    variants that allow it still get a sensible animation rather than a crash.
    """
    at = attacker.piece_type if isinstance(attacker, chess.Piece) else int(attacker)
    vt = victim.piece_type if isinstance(victim, chess.Piece) else int(victim)
    if (at, vt) in DUELS:
        return DUELS[(at, vt)]
    if (at, chess.QUEEN) in DUELS:
        return DUELS[(at, chess.QUEEN)]
    if (chess.PAWN, vt) in DUELS:
        return DUELS[(chess.PAWN, vt)]
    return DUELS[(chess.PAWN, chess.PAWN)]


def all_duels() -> List[Duel]:
    """Every duel, in board order: attackers first, then victims."""
    order = (P, N, B, R, Q, K)
    victims = (P, N, B, R, Q)
    return [DUELS[(a, v)] for a in order for v in victims if (a, v) in DUELS]


def duel_rows() -> List[Tuple[str, str, str]]:
    """(key, name, line) for every duel - for the UI and the docs."""
    return [(d.key, d.name, d.line) for d in all_duels()]


def describe(attacker, victim) -> Optional[str]:
    """One-line description of a capture, or None if there is no duel."""
    duel = duel_for(attacker, victim)
    return f"{duel.key} — {duel.name}: {duel.line}"
