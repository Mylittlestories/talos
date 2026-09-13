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

from .rules import AnarchessAction, AnarchessGame, AnarchessRules, neighbours

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
    """Position value in *player*'s eyes."""
    enemies = [p for p in range(game.players) if p != player]
    score = 0

    # ---- territory
    for group in game.areas():
        size = len(group)
        if size < game.rules.min_area:
            continue
        counts = _counts(game, group)
        mine = counts.get(player, 0)
        best_other = max((counts.get(e, 0) for e in enemies), default=0)
        if mine > best_other:
            score += 14 * size + 6 * (mine - best_other)
        elif mine == best_other and mine:
            score += 4 * size              # contested but present
        elif mine:
            score += 2 * size              # behind, but still on the board

    # ---- presence
    on_land = sum(1 for c, p in game.pawns.items() if p == player)
    score += 9 * on_land
    score += 3 * game.reserve[player]

    # ---- pressure: what can be taken, what is hanging
    threatens = 0
    hanging = 0
    for cell, owner in game.pawns.items():
        if owner == player:
            continue
        for nb in neighbours(cell):
            if game.pawns.get(nb) == player:
                # can we support an attack from nb?
                supported = any(game.pawns.get(n2) == player
                                for n2 in neighbours(nb) if n2 != cell)
                if supported or not game.rules.attack_needs_support:
                    threatens += 1
                    break
    for cell, owner in game.pawns.items():
        if owner != player:
            continue
        enemies_adjacent = sum(1 for nb in neighbours(cell)
                               if game.pawns.get(nb) not in (None, player))
        if enemies_adjacent:
            supported = any(game.pawns.get(nb) == player
                            for nb in neighbours(cell))
            if enemies_adjacent >= 2 or not supported:
                hanging += 1
    score += 7 * threatens - 9 * hanging

    # ---- supply: unused reserve late in the game is wasted
    if game.tiles_left() < 12:
        score -= 5 * game.reserve[player]

    return score


def _tile_promise(game: AnarchessGame, cell, colour: bool, player: int) -> int:
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
    # edges are safer to grow into than the middle of an enemy cluster
    return value


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
        keep = {1: 6, 2: 10, 3: 14}[self.level]
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
            if self.level == 3 and best_score is not None and score < best_score - 60:
                continue
            if self.level == 3:
                score -= self._opponent_best(trial) * 0.5
            score += self.rng.randint(0, {1: 22, 2: 8, 3: 0}[self.level])
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
        """Best reply score the next player can reach (level 3 only)."""
        tiles = game.legal_tile_actions()
        if not tiles:
            return 0
        if len(tiles) > 6:
            tiles.sort(key=lambda a: -_tile_promise(game, a.cell, bool(a.colour),
                                                    game.current))
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
                    best = max(best, evaluate(probe, self.player) * -1)
        return best
