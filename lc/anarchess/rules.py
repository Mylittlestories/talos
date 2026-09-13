"""
Anarchess - the rules engine.

Anarchess is an abstract strategy board game by **Dimitris Grammenos**
(ICS-FORTH, Heraklion, Crete).  BoardGameGeek entry: ``boardgame/262401``.

    "ANARCHESS takes place in the land of Chess long before the enemy White
    and Black kingdoms were formed.  Back when the land was not ruled by kings
    and queens, neither structured armies with bishops, knights and rooks
    existed.  The world was unexplored and amorphous and it had not been
    squeezed yet into the rigid cast of the contemporary chessboard.  There
    were just 2 proud tribes constantly struggling to expand their territories
    to ensure survival in a barren and harsh land.  And those who today we
    (somewhat degradingly) call 'pawns', were free entities with dreams, fears
    and hopes who defined their own destiny."

Components (as published)
    32 light ('white') and 32 dark ('black') square tiles, plus 8 light and
    8 dark pawns.  2 players, 7+, 5-10 minutes to learn, 30-60 minutes a game.
    Also playtested for 3 players (6 pawns each) and 4 players (5 pawns each).

Turn structure (as published)
    "On a turn, a player can perform 2 actions:
       A. Tile Placement
       B. (Optional) Pawn Action (placing a new pawn, moving or attacking)"
    "The game ends after a player places the last available tile."
    "Players earn points by controlling areas (i.e., having the most pawns in
     them) comprising two or more tiles.  The player with the most points wins."

Reconstruction notes
--------------------
The official rulebook (a Google Drive link the designer posted in 2018) is
offline, as is the Tabletop-Simulator mod's copy, so the details below are a
faithful reconstruction from the published summary plus playtesting.  Every
decision is recorded in :data:`RULINGS` so it can be checked against a printed
copy, and most of them are switchable through :class:`AnarchessRules`.

  R1  The land grows on an implicit square grid: a tile may only be laid in an
      empty cell edge-adjacent to the existing land (any cell when the land is
      empty).  This is what makes the land "amorphous" rather than an 8x8 grid.
  R2  The player *chooses* the colour of the tile they lay, from a shared
      supply of 32 light and 32 dark.  The equal counts only matter if colour
      is a choice; with 64 placements in a two player game (32 turns each) the
      supply runs out exactly when the game ends.  Set ``random_colour=True``
      for the alternative "draw a tile from a bag" reading.
  R3  An *area* is a maximal group of edge-connected tiles of the same colour.
      Areas of a single tile are worth nothing.
  R4  A pawn action is one of: settle a pawn from the reserve onto an empty
      tile next to one of your own pawns (any empty tile if you have none on
      the land), move one pawn one step to an orthogonally adjacent empty
      tile, or attack an orthogonally adjacent enemy pawn.
  R5  An attack only succeeds when the attacker is *supported*: at least one
      friendly pawn stands orthogonally beside it.  A tribe fights together.
  R6  A captured pawn returns to its owner's reserve (it can be settled again
      later).  Set ``captives_return=False`` for permanent elimination.
  R7  Placing the final tile ends the game immediately - the player who does
      it does not get a pawn action that turn.
  R8  Scoring happens once, at the end: each area of two or more tiles is
      worth one point per tile to whoever has strictly the most pawns on it.
      Set ``score_per_tile=False`` for one point per area instead.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

LIGHT = True
DARK = False

Cell = Tuple[int, int]

#: The documented design decisions described in the module docstring.
RULINGS: List[Tuple[str, str]] = [
    ("R1", "Tiles go on an implicit square grid, edge-adjacent to the land."),
    ("R2", "The player chooses the tile colour; the supply is 32 light + 32 dark."),
    ("R3", "An area is a maximal group of edge-connected same-colour tiles."),
    ("R4", "One pawn action per turn: settle, move one step, or attack."),
    ("R5", "An attack needs a friendly pawn orthogonally beside the attacker."),
    ("R6", "Captured pawns go back to their owner's reserve."),
    ("R7", "Laying the last tile ends the game at once."),
    ("R8", "Score 1 point per tile of every area of 2+ tiles you lead."),
]

PLAYER_COLOURS = ["#f2ede1", "#3a3550", "#4cc2ff", "#f0b429"]
PLAYER_NAMES = ["Light", "Dark", "Azure", "Amber"]

PAWNS_PER_PLAYER = {2: 8, 3: 6, 4: 5}

_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def neighbours(cell: Cell) -> Iterable[Cell]:
    x, y = cell
    for dx, dy in _NEIGHBOURS:
        yield (x + dx, y + dy)


@dataclass
class AnarchessRules:
    """Switchable interpretations of the reconstructed rules."""
    tiles_per_colour: int = 32
    random_colour: bool = False      # R2 alternative
    captives_return: bool = True     # R6
    attack_needs_support: bool = True  # R5
    score_per_tile: bool = True      # R8
    min_area: int = 2                # R3
    final_tile_ends_game: bool = True  # R7


@dataclass
class AnarchessAction:
    """One half of a turn."""
    kind: str                        # "tile" | "settle" | "move" | "attack" | "pass"
    cell: Optional[Cell] = None      # target cell (tile/settle/move destination)
    source: Optional[Cell] = None    # origin for move/attack
    colour: Optional[bool] = None    # tile colour

    def describe(self) -> str:
        if self.kind == "tile":
            where = _cell_name(self.cell) if self.cell else "?"
            return f"lay a {'light' if self.colour else 'dark'} tile at {where}"
        if self.kind == "settle":
            return f"settle a pawn at {_cell_name(self.cell)}"
        if self.kind == "move":
            return f"move {_cell_name(self.source)} to {_cell_name(self.cell)}"
        if self.kind == "attack":
            return f"attack {_cell_name(self.cell)} from {_cell_name(self.source)}"
        return "pass"


def _cell_name(cell: Optional[Cell]) -> str:
    if cell is None:
        return "?"
    x, y = cell
    return f"{'abcdefghijklmnopqrstuvwxyz'[x % 26]}{y + 1}"


class AnarchessGame:
    """Complete, self-contained Anarchess game state."""

    def __init__(self, players: int = 2, rules: Optional[AnarchessRules] = None,
                 seed: Optional[int] = None, names: Optional[Sequence[str]] = None):
        self.players = max(2, min(4, players))
        self.rules = rules or AnarchessRules()
        self.rng = random.Random(seed)
        self.names: List[str] = list(names or PLAYER_NAMES[:self.players])

        self.tiles: Dict[Cell, bool] = {}          # cell -> LIGHT / DARK
        self.pawns: Dict[Cell, int] = {}           # cell -> player index
        self.supply = {LIGHT: self.rules.tiles_per_colour,
                       DARK: self.rules.tiles_per_colour}
        self.reserve = [PAWNS_PER_PLAYER[self.players] for _ in range(self.players)]

        self.current = 0
        self.turn_number = 1
        self.placed_tile = False                   # action A done this turn?
        self.used_pawn_action = False
        self.finished = False
        self.drawn: Optional[bool] = None     # tile drawn from the bag (R2 alt)
        self._draw()
        self.history: List[Tuple[str, AnarchessAction]] = []
        self.scores: List[int] = [0] * self.players
        self.last_action: Optional[AnarchessAction] = None

    # ------------------------------------------------------------------
    # setup helpers
    # ------------------------------------------------------------------
    def clone(self) -> "AnarchessGame":
        g = AnarchessGame(self.players, self.rules, seed=self.rng.random())
        g.tiles = dict(self.tiles)
        g.pawns = dict(self.pawns)
        g.supply = dict(self.supply)
        g.reserve = list(self.reserve)
        g.current = self.current
        g.turn_number = self.turn_number
        g.placed_tile = self.placed_tile
        g.used_pawn_action = self.used_pawn_action
        g.finished = self.finished
        g.names = list(self.names)
        return g

    def total_tiles(self) -> int:
        return len(self.tiles)

    def tiles_left(self) -> int:
        return self.supply[LIGHT] + self.supply[DARK]

    # ------------------------------------------------------------------
    # legality
    # ------------------------------------------------------------------
    def tile_cells(self) -> List[Cell]:
        """Every empty cell where a tile may be laid (R1)."""
        if not self.tiles:
            return [(0, 0)]
        seen: Set[Cell] = set()
        out: List[Cell] = []
        for cell in self.tiles:
            for nb in neighbours(cell):
                if nb not in self.tiles and nb not in seen:
                    seen.add(nb)
                    out.append(nb)
        out.sort()
        return out

    def available_colours(self) -> List[bool]:
        return [c for c in (LIGHT, DARK) if self.supply[c] > 0]

    def _draw(self) -> None:
        """Draw the tile this turn from the bag (only used in bag mode)."""
        if not self.rules.random_colour:
            self.drawn = None
            return
        colours = self.available_colours()
        self.drawn = self.rng.choice(colours) if colours else None

    def legal_tile_actions(self) -> List[AnarchessAction]:
        if self.finished or self.placed_tile:
            return []
        colours = self.available_colours()
        if self.rules.random_colour:
            if self.drawn is None or self.supply.get(self.drawn, 0) <= 0:
                self._draw()
            colours = [self.drawn] if self.drawn is not None else []
        acts = []
        for cell in self.tile_cells():
            for colour in colours:
                acts.append(AnarchessAction("tile", cell=cell, colour=colour))
        return acts

    def _supported(self, cell: Cell, player: int) -> bool:
        for nb in neighbours(cell):
            if self.pawns.get(nb) == player:
                return True
        return False

    def legal_pawn_actions(self) -> List[AnarchessAction]:
        if self.finished or not self.placed_tile or self.used_pawn_action:
            return []
        me = self.current
        acts: List[AnarchessAction] = []

        # settle a pawn from the reserve
        if self.reserve[me] > 0:
            mine = [c for c, p in self.pawns.items() if p == me]
            if not mine:
                targets = [c for c in self.tiles if c not in self.pawns]
            else:
                targets = []
                seen: Set[Cell] = set()
                for c in mine:
                    for nb in neighbours(c):
                        if (nb in self.tiles and nb not in self.pawns
                                and nb not in seen):
                            seen.add(nb)
                            targets.append(nb)
            for t in targets:
                acts.append(AnarchessAction("settle", cell=t))

        # move / attack
        for cell, owner in list(self.pawns.items()):
            if owner != me:
                continue
            for nb in neighbours(cell):
                if nb not in self.tiles:
                    continue
                target = self.pawns.get(nb)
                if target is None:
                    acts.append(AnarchessAction("move", source=cell, cell=nb))
                elif target != me:
                    if (self.rules.attack_needs_support
                            and not self._supported(cell, me)):
                        continue
                    acts.append(AnarchessAction("attack", source=cell, cell=nb))
        return acts

    def legal_actions(self) -> List[AnarchessAction]:
        if self.finished:
            return []
        if not self.placed_tile:
            return self.legal_tile_actions()
        # The pawn action is optional, so "do nothing" is always on the menu.
        # Without it a player whose pawns are all boxed in would have no legal
        # action at all and the game would stop dead.
        acts = self.legal_pawn_actions()
        acts.append(AnarchessAction("pass"))
        return acts

    # ------------------------------------------------------------------
    # mutation
    # ------------------------------------------------------------------
    def apply(self, action: AnarchessAction) -> bool:
        if self.finished:
            return False
        me = self.current

        if action.kind == "tile":
            if self.placed_tile or action.cell is None:
                return False
            if action.cell not in self.tiles and action.cell in set(self.tile_cells()):
                pass
            else:
                return False
            colour = action.colour
            if colour is None or self.supply[colour] <= 0:
                return False
            self.tiles[action.cell] = colour
            self.supply[colour] -= 1
            self.placed_tile = True
            self.last_action = action
            if self.rules.final_tile_ends_game and self.tiles_left() == 0:
                self.finish()
            return True

        if not self.placed_tile or self.used_pawn_action:
            return False

        if action.kind == "pass":
            self.used_pawn_action = True
            self.last_action = action
            self._end_turn()
            return True

        if action.kind == "settle":
            if (self.reserve[me] <= 0 or action.cell is None
                    or action.cell not in self.tiles
                    or action.cell in self.pawns):
                return False
            if not self._can_settle(action.cell, me):
                return False
            self.pawns[action.cell] = me
            self.reserve[me] -= 1
            self.used_pawn_action = True
            self.last_action = action
            self._end_turn()
            return True

        if action.kind in ("move", "attack"):
            src, dst = action.source, action.cell
            if src is None or dst is None:
                return False
            if self.pawns.get(src) != me or dst not in self.tiles:
                return False
            if dst not in set(neighbours(src)):
                return False
            victim = self.pawns.get(dst)
            if action.kind == "move":
                if victim is not None:
                    return False
                del self.pawns[src]
                self.pawns[dst] = me
            else:
                if victim is None or victim == me:
                    return False
                if (self.rules.attack_needs_support
                        and not self._supported(src, me)):
                    return False
                del self.pawns[dst]
                if self.rules.captives_return:
                    self.reserve[victim] += 1
                del self.pawns[src]
                self.pawns[dst] = me
            self.used_pawn_action = True
            self.last_action = action
            self._end_turn()
            return True

        return False

    def _can_settle(self, cell: Cell, player: int) -> bool:
        mine = [c for c, p in self.pawns.items() if p == player]
        if not mine:
            return True
        return any(self.pawns.get(nb) == player for nb in neighbours(cell))

    def _end_turn(self) -> None:
        self.history.append((self.names[self.current], self.last_action))
        self.current = (self.current + 1) % self.players
        if self.current == 0:
            self.turn_number += 1
        self.placed_tile = False
        self.used_pawn_action = False
        self._draw()
        if not self.tile_cells() or self.tiles_left() == 0:
            self.finish()

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        self.scores = self.final_scores()

    # ------------------------------------------------------------------
    # areas and scoring
    # ------------------------------------------------------------------
    def areas(self) -> List[List[Cell]]:
        """Maximal edge-connected same-colour groups (R3)."""
        seen: Set[Cell] = set()
        out: List[List[Cell]] = []
        for start in self.tiles:
            if start in seen:
                continue
            colour = self.tiles[start]
            group: List[Cell] = []
            stack = [start]
            seen.add(start)
            while stack:
                cell = stack.pop()
                group.append(cell)
                for nb in neighbours(cell):
                    if nb in self.tiles and nb not in seen and self.tiles[nb] == colour:
                        seen.add(nb)
                        stack.append(nb)
            out.append(group)
        out.sort(key=len, reverse=True)
        return out

    def area_control(self, group: Sequence[Cell]) -> Optional[int]:
        """Player with strictly most pawns in *group*, or None."""
        counts: Dict[int, int] = {}
        for cell in group:
            owner = self.pawns.get(cell)
            if owner is not None:
                counts[owner] = counts.get(owner, 0) + 1
        if not counts:
            return None
        best = max(counts.values())
        leaders = [p for p, n in counts.items() if n == best]
        return leaders[0] if len(leaders) == 1 else None

    def final_scores(self) -> List[int]:
        scores = [0] * self.players
        for group in self.areas():
            if len(group) < self.rules.min_area:
                continue
            owner = self.area_control(group)
            if owner is None:
                continue
            scores[owner] += len(group) if self.rules.score_per_tile else 1
        return scores

    def live_scores(self) -> List[int]:
        """Running score if the game ended right now."""
        return self.final_scores()

    def winner(self) -> Optional[int]:
        if not self.finished:
            return None
        best = max(self.scores)
        leaders = [i for i, s in enumerate(self.scores) if s == best]
        return leaders[0] if len(leaders) == 1 else None

    # ------------------------------------------------------------------
    # presentation helpers
    # ------------------------------------------------------------------
    def bounds(self) -> Tuple[int, int, int, int]:
        if not self.tiles:
            return (-1, 1, -1, 1)
        xs = [c[0] for c in self.tiles]
        ys = [c[1] for c in self.tiles]
        return (min(xs), max(xs), min(ys), max(ys))

    def status(self) -> str:
        if self.finished:
            w = self.winner()
            if w is None:
                return "Game over - a draw"
            return f"Game over - {self.names[w]} wins with {self.scores[w]} points"
        phase = "lay a tile" if not self.placed_tile else "pawn action (optional)"
        return (f"Turn {self.turn_number} - {self.names[self.current]}: {phase} "
                f"- {self.tiles_left()} tiles left")

    def rules_text(self) -> str:
        lines = [
            "<h3>Anarchess</h3>",
            "<p><i>The land of Chess before kings.</i> Grow the land, settle your "
            "tribe, and control the largest territories when the last tile is "
            "laid.</p>",
            "<p><b>Your turn has two parts</b></p><ol>",
            "<li><b>Lay a tile.</b> Choose an empty cell touching the land and "
            "pick its colour. The supply is 32 light and 32 dark - shared.</li>",
            "<li><b>Optionally use one pawn</b>: settle a pawn from your reserve "
            "next to one of your own (anywhere if you have none), step one pawn "
            "to a neighbouring empty tile, or attack a neighbouring enemy pawn. "
            "An attack needs a friendly pawn standing beside the attacker.</li>",
            "</ol>",
            "<p><b>Scoring.</b> When the last tile is laid the game ends at once. "
            "Every <i>area</i> - a group of edge-connected tiles of the same "
            "colour - of two or more tiles scores one point per tile for whoever "
            "has the most pawns on it. Lone tiles score nothing, and a tied area "
            "scores for nobody.</p>",
            "<p style='color:#98a1b5'>Reconstruction note: the printed rulebook is "
            "off line, so a handful of details were reconstructed and are listed "
            "under <i>Rulings</i>. They can all be switched off in the dialog.</p>",
        ]
        return "".join(lines)
