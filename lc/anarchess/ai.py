"""
Anarchess computer opponents.

Anarchess is a territory game, not chess: the meaningful decision is a *whole
turn* (lay one die-selected tile, then settle, move, attack, or pass).  Earlier
bots chose the two halves independently and only estimated an opponent's gain.
That made them overlook a forced Anarcheckers capture chain and walk into
simple territorial replies.

This module plans legal complete turns.  The stronger opponents rank a bounded
set of their own turns, examine the next tribe's best full reply, and—at the
highest level in a two-player table—check their own counter-turn.  Bounds keep
it responsive in CPython and in the browser's Pyodide worker; legality remains
entirely in :mod:`lc.anarchess.rules`.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Dict, List, Optional, Sequence, Tuple

from .rules import (Cell, PAWNS_PER_PLAYER, AnarchessAction, AnarchessGame,
                    diagonals, neighbours)


# These names are shared by the desktop setup dialog and the browser bridge.
# Keep the descriptions player-facing: difficulty is about the quality of the
# plan, not an unverified Elo claim for a non-chess game.
LEVELS: List[Tuple[str, str]] = [
    ("Settler", "Makes sensible local claims, but leaves opportunities open."),
    ("Tribe", "Builds solid territory and takes straightforward captures."),
    ("Strategist", "Reads the next tribe's best reply before committing."),
    ("Warlord", "Defends contested areas and, head-to-head, plans a counter-turn."),
]


@dataclass(frozen=True)
class _Profile:
    """A deliberately bounded turn-search budget for one difficulty tier."""

    tile_limit: int
    turn_limit: int
    reply_tiles: int = 0
    reply_turns: int = 0
    counter_tiles: int = 0
    counter_turns: int = 0
    noise: int = 0


_PROFILES = {
    1: _Profile(tile_limit=8, turn_limit=10, noise=38),
    2: _Profile(tile_limit=14, turn_limit=20, noise=10),
    3: _Profile(tile_limit=20, turn_limit=28, reply_tiles=6, reply_turns=10),
    # The Warlord adds a counter-turn, so its candidate sets stay deliberately
    # tight.  This keeps a high-level reply below a human-visible pause in the
    # desktop app and reasonable in Pyodide on a phone.
    4: _Profile(tile_limit=18, turn_limit=22, reply_tiles=5, reply_turns=6,
                counter_tiles=4, counter_turns=4),
}


# ---------------------------------------------------------------------------
# Position evaluation
# ---------------------------------------------------------------------------

def _counts(game: AnarchessGame, cells: Sequence[Cell]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for cell in cells:
        owner = game.pawns.get(cell)
        if owner is not None:
            counts[owner] = counts.get(owner, 0) + 1
    return counts


def evaluate(game: AnarchessGame, player: int) -> int:
    """Position value in ``player``'s eyes.

    The weights follow the rulebook's real arithmetic rather than paying for
    abstract board shape: an owned area is worth its tile rate times its size;
    unused pawns cost points; diagonal pressure decides whether a claim is
    stable.  It is intentionally a *relative* evaluation—the public helper is
    also useful to inspect an AI decision in tests or tools.
    """
    enemies = [p for p in range(game.players) if p != player]
    score = 0
    groups = game.areas()
    largest = max((len(g) for g in groups), default=0)

    # ---- territory
    for group in groups:
        size = len(group)
        if size < game.rules.min_area:
            continue
        counts = _counts(game, group)
        mine = counts.get(player, 0)
        best_other = max((counts.get(e, 0) for e in enemies), default=0)
        leader = game.area_control(group)
        rate = game.area_tile_rate(group, player if leader is None else leader,
                                   largest)
        if leader == player:
            score += 12 * rate * size
        elif leader is not None:
            score -= 12 * rate * size
            if game.rules.tax_largest_area and size == largest:
                score += 8 * size        # the enemy holds the taxed area
        else:
            score += 4 * size            # unclaimed, and worth a fight
        if mine == best_other and mine:
            score += 6 * size            # one pawn from flipping it
        elif mine and mine < best_other:
            score += 2 * mine            # a foothold, nothing more

    # ---- pawns
    on_land = sum(1 for owner in game.pawns.values() if owner == player)
    score += 14 * on_land
    score -= 2 * game.rules.reserve_penalty * game.reserve[player]

    # ---- pressure: attacks land on diagonals in Anarchess; Anarcheckers
    #      uses jumps, but the adjacent enemy is still the tactical signal.
    threatens = 0
    hanging = 0
    for cell, owner in game.pawns.items():
        if owner == player:
            continue
        if any(game.pawns.get(nb) == player for nb in diagonals(cell)):
            threatens += 1
    for cell, owner in game.pawns.items():
        if owner != player:
            continue
        if any(game.pawns.get(nb) not in (None, player)
               for nb in diagonals(cell)):
            hanging += 1
    score += 8 * threatens - 11 * hanging

    # ---- the clock: reserve that can no longer be spent is a pure loss
    if game.tiles_left() <= PAWNS_PER_PLAYER.get(game.players, 8):
        score -= game.rules.reserve_penalty * game.reserve[player]

    return score


def _utility(game: AnarchessGame, player: int) -> int:
    """A cautious game value from one tribe's perspective.

    ``evaluate()`` describes a tribe.  A computer opponent needs to compare
    that tribe with the most dangerous rival, especially in three- and
    four-player games where a coalition-like lead is worse than a single
    opponent being merely a few points ahead.
    """
    enemies = [p for p in range(game.players) if p != player]
    if game.finished:
        scores = game.scores or game.final_scores()
        mine = scores[player]
        danger = max((scores[p] for p in enemies), default=0)
        # Finished games dominate any heuristic preference or tie-break noise.
        return (mine - danger) * 120 + 4 * game.tiles_conquered(player)
    mine = evaluate(game, player)
    danger = max((evaluate(game, p) for p in enemies), default=0)
    return mine - int(danger * 0.58)


# ---------------------------------------------------------------------------
# Turn construction
# ---------------------------------------------------------------------------

def _area_is_empty(game: AnarchessGame, cell: Cell, colour: bool) -> bool:
    """Whether laying ``colour`` at ``cell`` would open an empty area."""
    seen = {cell}
    stack = [nb for nb in neighbours(cell)
             if nb in game.tiles and game.tiles[nb] == colour]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in game.pawns:
            return False
        for nb in neighbours(cur):
            if nb in game.tiles and nb not in seen and game.tiles[nb] == colour:
                stack.append(nb)
    return True


def _tile_promise(game: AnarchessGame, cell: Cell, colour: bool,
                  player: int) -> int:
    """Cheap pre-filter before full turn simulation."""
    value = 0
    same = sum(1 for nb in neighbours(cell)
               if nb in game.tiles and game.tiles[nb] == colour)
    value += 14 * same
    mine = sum(1 for nb in neighbours(cell) if game.pawns.get(nb) == player)
    value += 10 * mine
    for nb in neighbours(cell):
        owner = game.pawns.get(nb)
        if owner is not None and owner != player:
            value -= 5
    if game.reserve[player] > 0 and _area_is_empty(game, cell, colour):
        value += 12 + 2 * game.reserve[player]
    return value


def _action_key(action: AnarchessAction) -> Tuple:
    """Stable tie-breaker: reproducible decisions matter for saved games."""
    return (action.kind, action.cell or (-999, -999), action.source or (-999, -999),
            -1 if action.colour is None else int(action.colour))


def _sequence_key(actions: Sequence[AnarchessAction]) -> Tuple:
    return tuple(_action_key(action) for action in actions)


def _rank_tiles(game: AnarchessGame, player: int, limit: int) -> List[AnarchessAction]:
    tiles = game.legal_tile_actions()
    tiles.sort(key=lambda action: (-_tile_promise(game, action.cell, bool(action.colour),
                                                   player), _action_key(action)))
    return tiles[:max(1, limit)]


def _finish_turns(state: AnarchessGame, prefix: List[AnarchessAction],
                  out: List[Tuple[List[AnarchessAction], AnarchessGame]],
                  depth: int = 0) -> None:
    """Expand a pawn phase until the turn ends.

    A normal turn ends after one pawn action.  Anarcheckers is the exception:
    its forced jump sequence may have several actions, all performed by the
    same piece.  The rules model exposes precisely those legal actions, so the
    AI never recreates capture logic on its own.
    """
    if state.finished or not state.placed_tile:
        out.append((prefix, state))
        return
    # At most every on-land pawn can be captured in a legal chain.  The guard
    # protects a malformed imported snapshot without truncating a real game.
    if depth > len(state.pawns) + sum(state.reserve) + 2:
        return
    actions = state.legal_actions()
    for action in actions:
        if action.kind == "tile":
            continue
        trial = state.clone()
        if not trial.apply(action):
            continue
        _finish_turns(trial, prefix + [action], out, depth + 1)


def _complete_turns(game: AnarchessGame, player: int, *, tile_limit: int,
                    turn_limit: int) -> List[Tuple[List[AnarchessAction], AnarchessGame]]:
    """Return the strongest bounded set of fully legal turn sequences."""
    starts: List[Tuple[List[AnarchessAction], AnarchessGame]] = []
    if game.finished:
        return starts
    if game.placed_tile:
        starts.append(([], game.clone()))
    else:
        for tile in _rank_tiles(game, player, tile_limit):
            trial = game.clone()
            if trial.apply(tile):
                starts.append(([tile], trial))

    outcomes: List[Tuple[List[AnarchessAction], AnarchessGame]] = []
    for prefix, state in starts:
        _finish_turns(state, prefix, outcomes)

    outcomes.sort(key=lambda item: (-_utility(item[1], player), _sequence_key(item[0])))
    return outcomes[:max(1, turn_limit)]


# ---------------------------------------------------------------------------
# Opponent
# ---------------------------------------------------------------------------

class AnarchessBot:
    """A complete-turn opponent for Anarchess and Anarcheckers.

    The bot only acts for its own current tribe.  A caller that wants a whole
    table of computer opponents creates one bot per tribe—the desktop view and
    browser bridge both do exactly that.
    """

    def __init__(self, player: int, level: int = 2, seed: Optional[int] = None):
        self.player = player
        self.level = max(1, min(max(_PROFILES), int(level)))
        self.rng = random.Random(seed)

    def choose(self, game: AnarchessGame) -> List[AnarchessAction]:
        """Return every action necessary to complete this computer's turn."""
        if game.finished or game.current != self.player:
            return []
        profile = _PROFILES[self.level]
        candidates = _complete_turns(game, self.player,
                                     tile_limit=profile.tile_limit,
                                     turn_limit=profile.turn_limit)
        if not candidates:
            return []

        best_actions: List[AnarchessAction] = []
        best_score: Optional[int] = None
        for actions, after in candidates:
            score = _utility(after, self.player)
            if profile.reply_turns:
                score = self._after_reply(after, profile)
            if profile.noise:
                score += self.rng.randint(-profile.noise, profile.noise)
            if (best_score is None or score > best_score or
                    (score == best_score and _sequence_key(actions) < _sequence_key(best_actions))):
                best_score = score
                best_actions = actions
        return best_actions

    def _after_reply(self, after: AnarchessGame, profile: _Profile) -> int:
        """Score a candidate after the next tribe's best full answer.

        A multiplayer table is not strictly zero-sum, so each rival's moves
        are ranked by *their* evaluation and the root player assumes the reply
        that leaves them worst off.  In a two-player Warlord game, examine one
        affordable counter-turn too; this catches common bait-and-capture
        sequences without making a browser move feel stalled.
        """
        if after.finished:
            return _utility(after, self.player)
        opponent = after.current
        replies = _complete_turns(after, opponent,
                                  tile_limit=profile.reply_tiles,
                                  turn_limit=profile.reply_turns)
        if not replies:
            return _utility(after, self.player)

        worst: Optional[int] = None
        for _actions, reply in replies:
            value = _utility(reply, self.player)
            if (profile.counter_turns and not reply.finished and reply.players == 2
                    and reply.current == self.player):
                counters = _complete_turns(reply, self.player,
                                           tile_limit=profile.counter_tiles,
                                           turn_limit=profile.counter_turns)
                if counters:
                    value = max(_utility(counter, self.player)
                                for _sequence, counter in counters)
            worst = value if worst is None else min(worst, value)
        return worst if worst is not None else _utility(after, self.player)
