"""
Anarchess bot.

Anarchess is a territory game, not a chess game, so there is no alpha-beta
tree here - the interesting decision is the *pair* of actions (which tile,
then which pawn) and how the pair reshapes the areas on the board.

The bot works in three stages:

1. every legal tile placement is scored with a cheap static term and only the
   best handful survives (the perimeter of the land can be 60+ cells);
2. for each surviving tile the bot tries the pawn actions and keeps the best
   resulting position;
3. on the harder levels the best few candidates are checked against the
   opponent's best reply, so the bot does not walk into a capture.

Levels: 1 = Settler (loose, noisy), 2 = Tribe (solid), 3 = Warlord (looks one
move ahead and plays for area control).
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence, Tuple

from .rules import (Cell, PAWNS_PER_PLAYER, AnarchessAction, AnarchessGame,
                    AnarchessRules, diagonals, neighbours)

LEVELS: List[Tuple[str, str]] = [
    ("Settler", "Greedy and a little careless - good for learning the game."),
    ("Tribe",   "Plays a solid territorial game and takes free captures."),
    ("Warlord", "Looks one move ahead and fights for every contested area."),
]


def _counts(game: AnarchessGame, cells: Sequence) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for cell in cells:
        owner = game.pawns.get(cell)
        if owner is not None:
            counts[owner] = counts.get(owner, 0) + 1
    return counts


def evaluate(game: AnarchessGame, player: int) -> int:
    """Position value in *player*'s eyes.

    The weights are the rulebook's own arithmetic, not a free invention: an
    area is worth its tile rate times its size to whoever leads it, a pawn
    standing on the land is the only way to lead anything, and a pawn left in
    the reserve is worth minus the reserve penalty.  An earlier version paid
    players for keeping pawns in hand, which under the published scoring is
    exactly backwards - six points thrown away per pawn.
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
    on_land = sum(1 for c, p in game.pawns.items() if p == player)
    score += 14 * on_land
    score -= 2 * game.rules.reserve_penalty * game.reserve[player]

    # ---- pressure: attacks land on the diagonals, so that is where danger
    #      and opportunity live
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


def _area_is_empty(game: AnarchessGame, cell: Cell, colour: bool) -> bool:
    """Would the area *cell* joins hold no pawn at all?"""
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
    """Cheap static value of laying *colour* at *cell*."""
    value = 0
    same = 0
    for nb in neighbours(cell):
        if nb in game.tiles and game.tiles[nb] == colour:
            same += 1
    value += 14 * same
    # does it hand an area to somebody?
    mine = sum(1 for nb in neighbours(cell) if game.pawns.get(nb) == player)
    value += 10 * mine
    for nb in neighbours(cell):
        owner = game.pawns.get(nb)
        if owner is not None and owner != player:
            value -= 5
    # A pawn may only be settled into an area that is empty, so a tile that
    # opens such an area is a place to spend a reserve pawn - worth more the
    # more pawns are still waiting.
    if game.reserve[player] > 0 and _area_is_empty(game, cell, colour):
        value += 12 + 2 * game.reserve[player]
    # edges are safer to grow into than the middle of an enemy cluster
    return value


# How much level 3 discounts a move by the best reply it allows, and how far
# a candidate may trail the leader before it is dropped from the search.  Both
# are measured on the scale of evaluate(), which doubled when the scoring was
# rewritten, so they are tuned together (see tools/selftest.py).
OPPONENT_WEIGHT = 0.25
PRUNE_MARGIN = 150
# Per level: how many candidate tiles are examined, and how much random noise
# is added to each score.  Both move with the scale of evaluate().
KEEP = {1: 6, 2: 10, 3: 14}
NOISE = {1: 22, 2: 8, 3: 0}


class AnarchessBot:
    """Picks the (tile, pawn action) pair for one turn."""

    def __init__(self, player: int, level: int = 2, seed: Optional[int] = None):
        self.player = player
        self.level = max(1, min(3, level))
        self.rng = random.Random(seed)

    # ------------------------------------------------------------------
    def choose(self, game: AnarchessGame) -> List[AnarchessAction]:
        """Return the actions to play this turn (tile first, then the pawn
        action - or an explicit pass, which is what ends the turn)."""
        if game.finished:
            return []
        if game.placed_tile:                     # called mid-turn
            if game.used_pawn_action:
                return []
            pawn = self._best_pawn_action(game)
            return [pawn if pawn is not None else AnarchessAction("pass")]
        tiles = game.legal_tile_actions()
        if not tiles:
            return []
        if self.level == 1 and self.rng.random() < 0.25:
            tiles = self.rng.sample(tiles, min(len(tiles), 12))
        keep = KEEP[self.level]
        if len(tiles) > keep:
            tiles.sort(key=lambda a: -_tile_promise(game, a.cell, bool(a.colour),
                                                    self.player))
            tiles = tiles[:keep]

        best: List[AnarchessAction] = []
        best_score = None
        for tile in tiles:
            trial = game.clone()
            if not trial.apply(tile):
                continue
            if trial.finished:                 # the last tile ends the turn
                return [tile]
            pawn = self._best_pawn_action(trial)
            if pawn is not None:
                trial.apply(pawn)
            score = evaluate(trial, self.player)
            if self.level == 3 and best_score is not None and score < best_score - PRUNE_MARGIN:
                continue
            if self.level == 3:
                score -= self._opponent_best(trial) * OPPONENT_WEIGHT
            score += self.rng.randint(0, NOISE[self.level])
            if best_score is None or score > best_score:
                best_score = score
                best = [tile, pawn if pawn is not None
                        else AnarchessAction("pass")]
        return best

    # ------------------------------------------------------------------
    def _best_pawn_action(self, game: AnarchessGame) -> Optional[AnarchessAction]:
        actions = [a for a in game.legal_pawn_actions() if a.kind != "pass"]
        if not actions:
            return None
        # keep the search small: attacks and settles first, then moves
        actions.sort(key=lambda a: {"attack": 0, "settle": 1, "move": 2}
                     .get(a.kind, 3))
        actions = actions[:26]
        best, best_score = None, None
        for action in actions:
            trial = game.clone()
            if not trial.apply(action):
                continue
            score = evaluate(trial, self.player)
            if best_score is None or score > best_score:
                best_score, best = score, action
        if best is not None and best_score is not None:
            # a pawn action that makes things worse is skipped
            baseline = evaluate(game, self.player)
            if best_score < baseline - 4 and self.level > 1:
                return None
        return best

    def _opponent_best(self, game: AnarchessGame) -> int:
        """How much the next player can improve their own position (level 3).

        Measured as the opponent's own gain, not as our loss: a reply that
        costs us nothing while building them an area is the move worth
        fearing, and scoring it from their side is what makes the term
        discriminate between our candidate tiles.
        """
        opponent = game.current
        base = evaluate(game, opponent)
        tiles = game.legal_tile_actions()
        if not tiles:
            return 0
        if len(tiles) > 6:
            tiles.sort(key=lambda a: -_tile_promise(game, a.cell, bool(a.colour),
                                                    opponent))
            tiles = tiles[:6]
        best = 0
        for tile in tiles:
            trial = game.clone()
            if not trial.apply(tile):
                continue
            for action in trial.legal_pawn_actions()[:8]:
                if action.kind == "pass":
                    continue
                probe = trial.clone()
                if probe.apply(action):
                    best = max(best, evaluate(probe, opponent) - base)
        return best
