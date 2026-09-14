"""
Anarchess - the land before Chess.

Rules
-----
These are the **official** rules, taken from the designer's own rulebook
(Anarchess Quick Guide v1.8 and the Deluxe Detailed Guide v1.7, both supplied
with the game).  Earlier versions of this module were a reconstruction: the
rulebook the designer published in 2018 lived behind a link that has since
gone dead, and the details below were inferred from a short summary plus
playtesting.  Several of those inferences were wrong, and they are corrected
here - see :data:`RULINGS` for the source of each one.

The land
    The game is played with 32 light and 32 dark square tiles (16 or 24 of
    each for a shorter game) and 8 light and 8 dark pawns.

Setting up
    Place two tiles of each colour at the centre of the table, the two light
    ones diagonal to each other.  All pawns begin out of play, in their
    owner's Reserve.  Roll the die: **the player with the opposite colour
    plays first**.

A turn is two actions, in this order
    1. *Roll the die and take a tile of that colour.*  When every remaining
       tile is the same colour, take one without rolling.
    2. *Lay the tile* so at least one of its sides touches a tile already on
       the table.  If it touches the side of exactly one tile, that tile must
       be of the **opposite** colour.  If it touches two or more, they may be
       of any colour.  When no placement satisfies that, it may be ignored.
    3. *Optionally one pawn action*, or none at all:
       - settle a pawn from the Reserve **onto the tile just laid**, provided
         no pawn of any colour stands anywhere in the area that tile belongs
         to;
       - move one of your pawns to a horizontally or vertically adjacent
         tile of any colour, if it is empty;
       - attack an enemy pawn on a **diagonally** adjacent tile of any
         colour.  The attacker takes its place and the defender goes back to
         its owner's Reserve, from where it can be settled again.

The end
    The game ends after the last tile is laid **and** its pawn action is
    taken.  On that last turn a pawn may not be moved to a tile where an
    enemy pawn could attack it.

Scoring
    An area belongs to whoever has the most pawns in it; a tie and it belongs
    to nobody.  For every area you own of two or more tiles:

    * each tile counts **2** points;
    * if the area holds exactly one pawn, each tile counts **3**;
    * if the area is the same colour as its owner, each tile counts **3**;
    * the **largest** area (or every area tied for largest) is taxed: its
      tiles count **1** each, whatever else is true of it;
    * an area of a single tile scores nothing;
    * every pawn left in a Reserve counts **-6**.

    Ties are broken by, in order: more tiles conquered, fewer pawns left in
    Reserve, more areas owned, and finally a round of optional single pawn
    moves until the players agree to stop.

Variants
    :attr:`AnarchessRules.solo` is the published one-player puzzle: the pawn
    action is not optional or chosen when one is available: it follows a
    fixed priority (settle, else attack, else move) with the pawn colour
    forced to be the opposite of the tile just laid. If none is available,
    passing ends the turn. The target is 192 points.

    :attr:`AnarchessRules.checkers` is Anarcheckers, also from the
    rulebook: pieces move diagonally instead of orthogonally, captures are
    jumps over an enemy into the empty tile beyond, and a jump must be taken
    when one is available and repeated for as long as it can be.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

LIGHT = True
DARK = False

Cell = Tuple[int, int]

#: Display colours for the two to four tribes.
PLAYER_COLOURS = ["#f2ede1", "#3a3550", "#4cc2ff", "#f0b429"]
PLAYER_NAMES = ["Light", "Dark", "Azure", "Amber"]

#: The tile colour each player's pawns match.  The third and fourth players
#: are our own extension and have no colour of their own, so they never earn
#: the same-colour bonus.
PLAYER_TILE_COLOUR: Dict[int, Optional[bool]] = {0: LIGHT, 1: DARK, 2: None, 3: None}

#: Pawns a side starts with: eight each at two players, six at three, five at
#: four (the rulebook's own numbers).
PAWNS_PER_PLAYER = {2: 8, 3: 6, 4: 5}

_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAGONALS = ((1, 1), (1, -1), (-1, 1), (-1, -1))

#: The designer's target for the one-player game.
SOLO_PERFECT_SCORE = 192

#: Every ruling below is quoted from the rulebook; the ones marked *were*
#: differ from what this module used to do.
RULINGS: List[Tuple[str, str]] = [
    ("Setup", "Two tiles of each colour start at the centre, lights diagonal. "
              "*was* an empty table."),
    ("Die", "Roll for the tile colour each turn; the opposite colour plays "
            "first. *was* the player choosing the colour."),
    ("R1", "A tile touching exactly one other must touch the opposite "
           "colour; touching two or more, any colour. Ignored when nothing "
           "fits. *was* any edge-adjacent empty cell."),
    ("R2", "A pawn may only be settled on the tile laid that turn, and only "
           "when its whole area is empty of pawns. *was* any empty tile "
           "next to one of your own."),
    ("R3", "An area is a maximal group of edge-connected tiles of one "
           "colour; a lone tile scores nothing."),
    ("R4", "A pawn moves to an orthogonally adjacent empty tile."),
    ("R5", "A pawn attacks a DIAGONALLY adjacent enemy and takes its place. "
           "*was* orthogonally adjacent, and only with a friendly pawn "
           "beside the attacker - the rulebook requires no support."),
    ("R6", "A captured pawn returns to its owner's Reserve and can be "
           "settled again."),
    ("R7", "The game ends after the last tile is laid AND its pawn action "
           "is taken; on that turn a pawn may not be moved where it could "
           "be attacked. *was* the last tile ending the game at once."),
    ("R8", "Owned areas of two or more tiles: 2 a tile; 3 a tile with only "
           "one pawn in the area; 3 a tile when the area matches its "
           "owner's colour; 1 a tile for the largest area, which is taxed; "
           "a pawn left in a Reserve is -6. *was* 1 a tile, no penalty, no "
           "tax, no bonus."),
    ("Ties", "Broken by tiles conquered, then pawns left in Reserve, then "
             "areas owned, then optional single moves."),
    ("Tax", "When an area is both the largest and worth three a tile, the "
            "tax wins: the rulebook sets the largest area at one point a "
            "tile, whatever else is true of it. Our ruling."),
]


def neighbours(cell: Cell) -> Iterable[Cell]:
    """The four orthogonally adjacent cells."""
    x, y = cell
    for dx, dy in _NEIGHBOURS:
        yield (x + dx, y + dy)


def diagonals(cell: Cell) -> Iterable[Cell]:
    """The four diagonally adjacent cells."""
    x, y = cell
    for dx, dy in _DIAGONALS:
        yield (x + dx, y + dy)


@dataclass
class AnarchessRules:
    """Dials for the readings the rulebook leaves open, and the variants."""
    tiles_per_colour: int = 32          # 16, 24 or 32 - the designer's dial
    draw_tile_colour: bool = True       # the die decides the colour
    single_touch_opposite: bool = True  # R1
    diagonal_attack: bool = True        # R5
    captives_return: bool = True        # R6
    pawn_action_on_last_tile: bool = True   # R7
    protect_last_move: bool = True      # R7, the last-turn restriction
    tax_largest_area: bool = True       # R8, the largest-area tax
    same_colour_bonus: bool = True      # R8, area matching its owner
    reserve_penalty: int = 6            # R8, -6 a pawn left out
    min_area: int = 2                   # R3, areas below this score nothing
    solo: bool = False                  # the published one-player game
    checkers: bool = False              # Anarcheckers

    # --- names kept from the reconstruction, so older code keeps working ---
    @property
    def random_colour(self) -> bool:
        """Old name for :attr:`draw_tile_colour`."""
        return self.draw_tile_colour

    @property
    def attack_needs_support(self) -> bool:
        """Never true now: the rulebook requires no support to attack."""
        return False


@dataclass
class AnarchessAction:
    """One half of a turn."""
    kind: str                        # "tile" | "settle" | "move" | "attack" | "pass"
    cell: Optional[Cell] = None      # target cell
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
        self.rules = rules or AnarchessRules()
        # SOLO is one person playing the two original tribes.  Keeping this
        # invariant in the model prevents a stale UI or saved browser state
        # from quietly creating third and fourth reserves that SOLO never has.
        self.players = 2 if self.rules.solo else max(2, min(4, players))
        self.rng = random.Random(seed)
        default_names = PLAYER_NAMES[:self.players]
        supplied_names = list(names or default_names)
        self.names: List[str] = (supplied_names + default_names[len(supplied_names):])[:self.players]

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
        self.drawn: Optional[bool] = None          # this turn's tile colour
        self.last_tile: Optional[Cell] = None      # the tile laid this turn
        self.history: List[Tuple[str, AnarchessAction]] = []
        self.scores: List[int] = [0] * self.players
        self.last_action: Optional[AnarchessAction] = None

        self._opening()
        self._roll()
        # "Roll the die. The player with the opposite colour plays first."
        self.current = 1 if self.drawn == LIGHT else 0

    # ------------------------------------------------------------------ setup
    def _opening(self) -> None:
        """Two tiles of each colour, the two light ones diagonal."""
        for cell, colour in (((0, 0), LIGHT), ((1, 0), DARK),
                             ((0, 1), DARK), ((1, 1), LIGHT)):
            self.tiles[cell] = colour
            self.supply[colour] -= 1

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
        g.drawn = self.drawn
        g.last_tile = self.last_tile
        g.names = list(self.names)
        return g

    def total_tiles(self) -> int:
        return len(self.tiles)

    def tiles_left(self) -> int:
        return self.supply[LIGHT] + self.supply[DARK]

    def is_last_turn(self) -> bool:
        """True once the final tile is on the table (the game ends after the
        pawn action that follows it)."""
        return self.tiles_left() == 0

    # -------------------------------------------------------------- the die
    def available_colours(self) -> List[bool]:
        return [c for c in (LIGHT, DARK) if self.supply[c] > 0]

    def _roll(self) -> None:
        """Roll the die for this turn's tile colour.  When only one colour is
        left the rulebook skips the roll."""
        colours = self.available_colours()
        self.drawn = self.rng.choice(colours) if colours else None

    # --------------------------------------------------------------- legality
    def tile_cells(self) -> List[Cell]:
        """Every empty cell that touches the land."""
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

    def _touching(self, cell: Cell) -> List[Cell]:
        return [nb for nb in neighbours(cell) if nb in self.tiles]

    def _placement_ok(self, cell: Cell, colour: bool) -> bool:
        """R1 / R2: touching exactly one tile, it must be the opposite colour."""
        touching = self._touching(cell)
        if not touching:
            return False
        if len(touching) == 1 and self.rules.single_touch_opposite:
            return self.tiles[touching[0]] != colour
        return True

    def legal_tile_actions(self) -> List[AnarchessAction]:
        if self.finished or self.placed_tile:
            return []
        if self.drawn is None or self.supply.get(self.drawn, 0) <= 0:
            self._roll()
        colour = self.drawn
        if colour is None:
            return []
        cells = self.tile_cells()
        legal = [c for c in cells if self._placement_ok(c, colour)]
        if not legal:
            # "If the new tile cannot be placed according to these rules,
            #  then R1 can be ignored."
            legal = list(cells)
        return [AnarchessAction("tile", cell=c, colour=colour) for c in legal]

    # -- pawns -------------------------------------------------------------
    def acting_pawn_player(self) -> int:
        """Whose pawn acts this turn.

        In the solo game the rulebook forces the colour: "you always play a
        pawn of the opposite colour of the recently placed tile".
        """
        if self.rules.solo and self.last_tile is not None:
            return 1 if self.tiles[self.last_tile] == LIGHT else 0
        return self.current

    def area_of(self, cell: Cell) -> List[Cell]:
        """Every tile of the area *cell* belongs to."""
        if cell not in self.tiles:
            return []
        colour = self.tiles[cell]
        seen: Set[Cell] = {cell}
        stack = [cell]
        group: List[Cell] = []
        while stack:
            cur = stack.pop()
            group.append(cur)
            for nb in neighbours(cur):
                if nb in self.tiles and nb not in seen and self.tiles[nb] == colour:
                    seen.add(nb)
                    stack.append(nb)
        return group

    def _can_settle(self, cell: Optional[Cell], player: int) -> bool:
        """R2: onto the tile just laid, and only if its area holds no pawn."""
        if cell is None or cell not in self.tiles or cell in self.pawns:
            return False
        return not any(c in self.pawns for c in self.area_of(cell))

    def _attackable(self, cell: Cell, by: int) -> bool:
        """Could a pawn of *by* attack *cell* from where it stands?"""
        for nb in diagonals(cell):
            if self.pawns.get(nb) == by:
                return True
        return False

    def _would_be_attacked(self, cell: Cell, player: int) -> bool:
        return any(self._attackable(cell, other)
                   for other in range(self.players) if other != player)

    def _moves_from(self, cell: Cell) -> List[Cell]:
        """Empty tiles one step away: orthogonal, or diagonal for checkers."""
        steps = diagonals(cell) if self.rules.checkers else neighbours(cell)
        return [nb for nb in steps if nb in self.tiles and nb not in self.pawns]

    def _attacks_from(self, cell: Cell, me: int) -> List[Tuple[Cell, Cell]]:
        """(landing cell, victim cell) pairs for a pawn standing on *cell*."""
        out: List[Tuple[Cell, Cell]] = []
        if self.rules.checkers:
            for dx, dy in _DIAGONALS:
                victim = (cell[0] + dx, cell[1] + dy)
                landing = (cell[0] + 2 * dx, cell[1] + 2 * dy)
                if self.pawns.get(victim) in (None, me):
                    continue
                if landing in self.tiles and landing not in self.pawns:
                    out.append((landing, victim))
            return out
        for nb in diagonals(cell):
            victim = self.pawns.get(nb)
            if victim is not None and victim != me and nb in self.tiles:
                out.append((nb, nb))
        return out

    def _pawn_options(self, me: int) -> Dict[str, List[AnarchessAction]]:
        settle: List[AnarchessAction] = []
        moves: List[AnarchessAction] = []
        attacks: List[AnarchessAction] = []

        # settle a pawn on the tile laid this turn
        if self.reserve[me] > 0 and self._can_settle(self.last_tile, me):
            settle.append(AnarchessAction("settle", cell=self.last_tile))

        # the last-turn restriction: no move to a tile that can be attacked
        guard = self.rules.protect_last_move and self.is_last_turn()

        for cell, owner in list(self.pawns.items()):
            if owner != me:
                continue
            for landing, victim in self._attacks_from(cell, me):
                attacks.append(AnarchessAction("attack", source=cell, cell=landing))
            for nb in self._moves_from(cell):
                if guard and self._would_be_attacked(nb, me):
                    continue
                moves.append(AnarchessAction("move", source=cell, cell=nb))
        return {"settle": settle, "move": moves, "attack": attacks}

    def legal_pawn_actions(self) -> List[AnarchessAction]:
        if self.finished or not self.placed_tile or self.used_pawn_action:
            return []
        me = self.acting_pawn_player()
        options = self._pawn_options(me)

        if self.rules.solo:
            # "you must perform just one of these actions, with the following
            #  priority": settle, else attack, else move, else nothing
            for key in ("settle", "attack", "move"):
                if options[key]:
                    return list(options[key])
            return []

        if self.rules.checkers and options["attack"]:
            # "If a piece can attack, then there is no option."
            return list(options["attack"])
        return options["settle"] + options["attack"] + options["move"]

    def legal_actions(self) -> List[AnarchessAction]:
        if self.finished:
            return []
        if not self.placed_tile:
            return self.legal_tile_actions()
        acts = self.legal_pawn_actions()
        forced_capture = (self.rules.checkers
                          and any(a.kind == "attack" for a in acts))
        if (self.rules.solo and not acts) or (not self.rules.solo
                                              and not forced_capture):
            # The pawn action is optional in a normal multiplayer turn, so
            # doing nothing is normally on the menu. A compulsory checkers
            # jump is the exception. SOLO forces its prescribed action - but
            # only when one exists: a player who can neither settle, attack
            # nor move must still be able to end the turn instead of deadlocking.
            acts.append(AnarchessAction("pass"))
        return acts

    # -------------------------------------------------------------- mutation
    def apply(self, action: AnarchessAction) -> bool:
        if self.finished:
            return False
        if action.kind == "tile":
            if self.placed_tile or action.cell is None:
                return False
            colour = action.colour
            if colour is None:
                return False
            if not any(a.cell == action.cell and a.colour == colour
                       for a in self.legal_tile_actions()):
                return False
            self.tiles[action.cell] = colour
            self.supply[colour] -= 1
            self.placed_tile = True
            self.last_tile = action.cell
            self.last_action = action
            # The last tile no longer ends the game on the spot: the player
            # still gets the pawn action that follows it.
            return True

        if not self.placed_tile or self.used_pawn_action:
            return False
        acting = self.acting_pawn_player()

        if action.kind == "pass":
            # A pass is legal only when legal_actions offers one. This keeps
            # SOLO's no-action escape hatch while preserving compulsory SOLO
            # actions and Anarcheckers' compulsory captures at the model
            # boundary, not merely in the interface.
            if not any(a.kind == "pass" for a in self.legal_actions()):
                return False
            self.used_pawn_action = True
            self.last_action = action
            self._end_turn()
            return True

        if action.kind == "settle":
            if (self.reserve[acting] <= 0 or action.cell is None
                    or not self._can_settle(action.cell, acting)):
                return False
            self.pawns[action.cell] = acting
            self.reserve[acting] -= 1
            self.used_pawn_action = True
            self.last_action = action
            self._end_turn()
            return True

        if action.kind in ("move", "attack"):
            src, dst = action.source, action.cell
            if src is None or dst is None:
                return False
            if self.pawns.get(src) != acting:
                return False
            if action.kind == "move":
                if dst not in self._moves_from(src):
                    return False
                del self.pawns[src]
                self.pawns[dst] = acting
            else:
                pair = next(((l, v) for l, v in self._attacks_from(src, acting)
                             if l == dst), None)
                if pair is None:
                    return False
                _landing, victim_cell = pair
                victim = self.pawns[victim_cell]
                del self.pawns[victim_cell]
                if self.rules.captives_return:
                    self.reserve[victim] += 1
                del self.pawns[src]
                self.pawns[dst] = acting
            self.last_action = action
            if self.rules.checkers and self._attacks_from(dst, acting):
                # "the attacking piece must continue until there are no more
                #  jumps" - the same pawn keeps going this turn
                self.used_pawn_action = False
                return True
            self.used_pawn_action = True
            self._end_turn()
            return True

        return False

    def _end_turn(self) -> None:
        self.history.append((self.names[self.current], self.last_action))
        self.current = (self.current + 1) % self.players
        if self.current == 0:
            self.turn_number += 1
        self.placed_tile = False
        self.used_pawn_action = False
        self.last_tile = None
        self._roll()
        if not self.tile_cells() or self.tiles_left() == 0:
            # no tile left to lay, or nowhere to lay one: score it now
            self.finish()

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        self.scores = self.final_scores()

    # ------------------------------------------------------- areas, scoring
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
        """Player with strictly the most pawns in *group*, or None."""
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

    def area_tile_rate(self, group: Sequence[Cell], owner: int,
                       largest: int) -> int:
        """Points a tile of *group* is worth to *owner*."""
        if self.rules.tax_largest_area and len(group) == largest:
            return 1                                   # the largest is taxed
        if (self.rules.same_colour_bonus
                and PLAYER_TILE_COLOUR.get(owner) is not None
                and self.tiles[group[0]] == PLAYER_TILE_COLOUR[owner]):
            return 3                                   # matching colour
        if sum(1 for c in group if c in self.pawns) == 1:
            return 3                                   # held by a single pawn
        return 2

    def final_scores(self) -> List[int]:
        scores = [0] * self.players
        groups = self.areas()
        largest = max((len(g) for g in groups), default=0)
        for group in groups:
            if len(group) < self.rules.min_area:
                continue
            owner = self.area_control(group)
            if owner is None:
                continue
            scores[owner] += self.area_tile_rate(group, owner, largest) * len(group)
        for player in range(self.players):
            scores[player] -= self.rules.reserve_penalty * self.reserve[player]
        return scores

    def solo_score(self) -> int:
        """The one-player total, where a tied area is worth 4 a tile.

        The rulebook: "If an area has the same number of pawns of both
        colours, then each tile counts for 4 points" - which is how the
        target of 192 (or 256 with ties) is reached.
        """
        total = 0
        groups = self.areas()
        largest = max((len(g) for g in groups), default=0)
        for group in groups:
            if len(group) < self.rules.min_area:
                continue
            light = sum(1 for c in group if self.pawns.get(c) == 0)
            dark = sum(1 for c in group if self.pawns.get(c) == 1)
            if light == dark:
                total += 4 * len(group)
                continue
            owner = 0 if light > dark else 1
            total += self.area_tile_rate(group, owner, largest) * len(group)
        total -= self.rules.reserve_penalty * sum(self.reserve)
        return total

    def live_scores(self) -> List[int]:
        """Running score if the game ended right now."""
        return self.final_scores()

    def tiles_conquered(self, player: int) -> int:
        """Tiles in areas *player* owns - the first tiebreak."""
        groups = [g for g in self.areas() if len(g) >= self.rules.min_area]
        return sum(len(g) for g in groups if self.area_control(g) == player)

    def areas_owned(self, player: int) -> int:
        return sum(1 for g in self.areas()
                   if len(g) >= self.rules.min_area
                   and self.area_control(g) == player)

    def winner(self) -> Optional[int]:
        """Highest score, then the rulebook's tiebreaks, else None."""
        if not self.finished:
            return None
        if self.rules.solo:
            return None                     # the solo game has no opponent
        best = max(self.scores)
        leaders = [i for i, s in enumerate(self.scores) if s == best]
        if len(leaders) == 1:
            return leaders[0]
        # more tiles conquered
        best = max(self.tiles_conquered(i) for i in leaders)
        leaders = [i for i in leaders if self.tiles_conquered(i) == best]
        if len(leaders) == 1:
            return leaders[0]
        # fewer pawns left in the reserve
        best = min(self.reserve[i] for i in leaders)
        leaders = [i for i in leaders if self.reserve[i] == best]
        if len(leaders) == 1:
            return leaders[0]
        # most areas owned
        best = max(self.areas_owned(i) for i in leaders)
        leaders = [i for i in leaders if self.areas_owned(i) == best]
        return leaders[0] if len(leaders) == 1 else None

    # ---------------------------------------------------------- presentation
    def bounds(self) -> Tuple[int, int, int, int]:
        if not self.tiles:
            return (-1, 1, -1, 1)
        xs = [c[0] for c in self.tiles]
        ys = [c[1] for c in self.tiles]
        return min(xs), max(xs), min(ys), max(ys)

    def status(self) -> str:
        if self.finished:
            if self.rules.solo:
                return (f"Solo finished - {self.solo_score()} points "
                        f"(target {SOLO_PERFECT_SCORE})")
            w = self.winner()
            if w is None:
                return "Game over - draw"
            return f"Game over - {self.names[w]} wins with {self.scores[w]} points"
        if not self.placed_tile:
            colour = "light" if self.drawn else "dark"
            who = self.names[self.current]
            return f"{who} to lay a {colour} tile"
        who = self.names[self.acting_pawn_player()]
        return f"{who} may use one pawn action"

    def rules_text(self) -> str:
        return (
            "<h3>A turn</h3><ol>"
            "<li><b>Roll the die</b> and take a tile of that colour.</li>"
            "<li><b>Lay the tile</b> touching at least one side of the land. "
            "If it touches exactly one tile, that tile must be the opposite "
            "colour; touching two or more, any colour goes. When nothing "
            "fits, that restriction is ignored.</li>"
            "<li><b>Optionally use one pawn</b>: settle a pawn from your "
            "reserve on the tile you just laid, but only if its whole area "
            "is empty; move a pawn to an orthogonally adjacent empty tile; "
            "or attack an enemy pawn on a diagonally adjacent tile and take "
            "its place.</li></ol>"
            "<h3>Scoring</h3><ul>"
            "<li>An area of two or more tiles belongs to whoever has the "
            "most pawns in it; a tie and it belongs to nobody.</li>"
            "<li>Each tile counts <b>2</b>; <b>3</b> when the area holds a "
            "single pawn; <b>3</b> when the area matches its owner's colour; "
            "<b>1</b> in the largest area, which is taxed.</li>"
            "<li>An area of one tile scores nothing. Every pawn left in your "
            "reserve counts <b>-6</b>.</li></ul>")
