"""
Anarchess view - the controller that binds rules, bot, board and panel.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QSizePolicy, QTextBrowser, QVBoxLayout, QWidget)

from .ai import LEVELS, AnarchessBot
from .rules import (DARK, LIGHT, PAWNS_PER_PLAYER, PLAYER_COLOURS,
                    PLAYER_NAMES, AnarchessAction, AnarchessGame,
                    AnarchessRules, RULINGS, neighbours)
from .widget import AnarchessBoard

BOT_DELAY_MS = 260


def default_config(players: int = 2, level: int = 2) -> Dict:
    """A ready-to-play table: you against one computer tribe."""
    return {
        "players": players,
        "seats": ["human"] + ["bot"] * (players - 1),
        "human": 0,
        "level": level,
        "names": PLAYER_NAMES[:players],
        "rules": AnarchessRules(),
        "seed": None,
    }


class _PlayerRow(QFrame):
    def __init__(self, index: int, name: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#card {{ background: #1d212c; border-radius: 8px; padding: 2px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        self.dot = QLabel()
        self.dot.setFixedSize(14, 14)
        self.dot.setStyleSheet(
            f"background: {PLAYER_COLOURS[index % len(PLAYER_COLOURS)]};"
            f" border-radius: 7px;")
        self.name = QLabel(name)
        self.name.setStyleSheet("font-weight: 600;")
        self.reserve = QLabel("")
        self.reserve.setObjectName("dim")
        self.score = QLabel("0")
        self.score.setStyleSheet("font-weight: 700; color: #f0b429;")
        lay.addWidget(self.dot)
        lay.addWidget(self.name, 1)
        lay.addWidget(self.reserve)
        lay.addWidget(self.score)

    def update(self, reserve: int, score: int, active: bool) -> None:  # noqa: A003
        self.reserve.setText(f"{reserve} in hand")
        self.score.setText(f"{score} pts")
        border = "#f0b429" if active else "transparent"
        self.setStyleSheet(
            f"#card {{ background: #1d212c; border-radius: 8px; padding: 2px;"
            f" border: 1px solid {border}; }}")


class AnarchessView(QWidget):
    """Playable Anarchess: board on the left, controls on the right."""

    statusChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.game = AnarchessGame(2, AnarchessRules())
        self.bots: List[Optional[AnarchessBot]] = [None, None]
        self.human_seat = 0
        self.selected_pawn: Optional[Tuple[int, int]] = None
        self._bot_timer = QTimer(self)
        self._bot_timer.setInterval(BOT_DELAY_MS)
        self._bot_timer.timeout.connect(self._bot_step)
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self.board = AnarchessBoard(self.game)
        self.board.canvas.cellClicked.connect(self._on_cell)
        layout.addWidget(self.board, 1)

        right = QWidget()
        right.setFixedWidth(310)
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)

        self.turn_label = QLabel("Anarchess")
        self.turn_label.setObjectName("title")
        self.phase_label = QLabel("")
        self.phase_label.setObjectName("dim")
        col.addWidget(self.turn_label)
        col.addWidget(self.phase_label)

        self.players_box = QGroupBox("Tribes")
        self.players_layout = QVBoxLayout(self.players_box)
        col.addWidget(self.players_box)

        self.tile_box = QGroupBox("Tile supply")
        tile_lay = QGridLayout(self.tile_box)
        self.colour_buttons: Dict[bool, QPushButton] = {}
        for i, (colour, text) in enumerate(((LIGHT, "Light tile"), (DARK, "Dark tile"))):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(colour is LIGHT)
            swatch = QColor("#efe4cd") if colour else QColor("#8d6a48")
            btn.setStyleSheet(
                f"QPushButton {{ padding: 8px; border: 2px solid #2a3040; "
                f"background: {swatch.name()}; color:"
                f" {'#2a2620' if colour else '#f2ede1'}; font-weight: 700; }}"
                f"QPushButton:checked {{ border: 2px solid #f0b429; }}")
            btn.clicked.connect(lambda _=False, c=colour: self._pick_colour(c))
            self.colour_buttons[colour] = btn
            tile_lay.addWidget(btn, 0, i)
        self.supply_label = QLabel("")
        self.supply_label.setObjectName("dim")
        tile_lay.addWidget(self.supply_label, 1, 0, 1, 2)
        col.addWidget(self.tile_box)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        col.addWidget(self.hint_label)

        buttons = QHBoxLayout()
        self.skip_button = QPushButton("Skip pawn action")
        self.skip_button.clicked.connect(self._skip)
        self.new_button = QPushButton("New game")
        self.new_button.setProperty("accent", True)
        self.new_button.clicked.connect(lambda: self.new_game_requested())
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.new_button)
        col.addLayout(buttons)

        self.rules_view = QTextBrowser()
        self.rules_view.setHtml(self.game.rules_text())
        self.rules_view.setMinimumHeight(150)
        col.addWidget(self.rules_view, 1)

        layout.addWidget(right, 0)
        self._rebuild_players()
        self._refresh()

    # ------------------------------------------------------------------
    # game lifecycle
    # ------------------------------------------------------------------
    def new_game_requested(self) -> None:
        from .dialog import AnarchessDialog
        dlg = AnarchessDialog(self, players=self.game.players,
                              rules=self.game.rules)
        if dlg.exec():
            self.start(dlg.config())

    def start(self, cfg: Dict) -> None:
        players = int(cfg.get("players", 2))
        rules = cfg.get("rules") or AnarchessRules()
        game = AnarchessGame(players, rules, seed=cfg.get("seed"))
        game.names = list(cfg.get("names") or game.names)
        self.game = game
        self.board.canvas.set_game(game)
        self.human_seat = int(cfg.get("human", 0))
        seats: List[Optional[AnarchessBot]] = []
        for i in range(players):
            kind = (cfg.get("seats") or ["human"] + ["bot"] * (players - 1))
            kind = kind[i] if i < len(kind) else "bot"
            if kind == "human":
                seats.append(None)
                self.human_seat = i
            else:
                seats.append(AnarchessBot(i, int(cfg.get("level", 2)),
                                          seed=(cfg.get("seed") or 0) + i))
        self.bots = seats
        self.selected_pawn = None
        self._rebuild_players()
        self._refresh()
        self._maybe_bot()

    def _rebuild_players(self) -> None:
        while self.players_layout.count():
            item = self.players_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.rows: List[_PlayerRow] = []
        for i in range(self.game.players):
            kind = " (you)" if i == self.human_seat and self.bots[i] is None else ""
            row = _PlayerRow(i, self.game.names[i] + kind)
            self.players_layout.addWidget(row)
            self.rows.append(row)
        self.players_layout.addStretch(1)

    # ------------------------------------------------------------------
    # interaction
    # ------------------------------------------------------------------
    def _pick_colour(self, colour: bool) -> None:
        for c, btn in self.colour_buttons.items():
            btn.setChecked(c is colour)
        self.board.canvas.set_colour(colour)

    def _my_turn(self) -> bool:
        return (not self.game.finished and self.game.current == self.human_seat
                and self.bots[self.game.current] is None)

    def _on_cell(self, x: int, y: int) -> None:
        if not self._my_turn():
            return
        game = self.game
        cell = (x, y)
        if not game.placed_tile:
            colour = self.board.canvas.selected_colour
            action = AnarchessAction("tile", cell=cell, colour=colour)
            if cell in set(game.tile_cells()) and game.supply.get(colour, 0) > 0:
                game.apply(action)
                self.board.canvas.last_cell = cell
                self.board.centre_on(x, y)
                self._after_action()
            else:
                self._flash("That cell is not a legal tile placement.")
            return

        # phase B
        if self.selected_pawn is not None and cell in self.board.canvas.targets:
            kind = self.board.canvas.targets[cell]
            action = AnarchessAction(kind, source=self.selected_pawn, cell=cell)
            if game.apply(action):
                self.selected_pawn = None
                self._after_action()
            return
        if cell in self.board.canvas.settle_cells:
            if game.apply(AnarchessAction("settle", cell=cell)):
                self.selected_pawn = None
                self._after_action()
            return
        if game.pawns.get(cell) == self.human_seat:
            self.selected_pawn = None if self.selected_pawn == cell else cell
            self._refresh()
            return
        self.selected_pawn = None
        self._refresh()

    def _skip(self) -> None:
        if not self._my_turn() or not self.game.placed_tile:
            return
        self.selected_pawn = None
        self.game.apply(AnarchessAction("pass"))
        self._after_action()

    def _after_action(self) -> None:
        self._refresh()
        if self.game.finished:
            self._show_result()
            return
        self._maybe_bot()

    def _maybe_bot(self) -> None:
        if self.game.finished:
            return
        bot = self.bots[self.game.current] if self.game.current < len(self.bots) else None
        if bot is not None:
            self._bot_timer.start()

    def _bot_step(self) -> None:
        if self.game.finished:
            self._bot_timer.stop()
            return
        index = self.game.current
        bot = self.bots[index] if index < len(self.bots) else None
        if bot is None:
            self._bot_timer.stop()
            return
        actions = bot.choose(self.game)
        if not actions:
            self._bot_timer.stop()
            return
        for action in actions:
            if not self.game.apply(action):
                break
            if action.kind == "tile" and action.cell is not None:
                self.board.canvas.last_cell = action.cell
            if self.game.finished:
                break
        # only advance the timer while the same seat is still a bot
        nxt = self.game.current
        still_bot = (not self.game.finished and nxt < len(self.bots)
                     and self.bots[nxt] is not None)
        if not still_bot:
            self._bot_timer.stop()
        self._refresh()
        self.board.centre_on(*(self.board.canvas.last_cell or (0, 0)))
        if self.game.finished:
            self._show_result()

    # ------------------------------------------------------------------
    def _flash(self, text: str) -> None:
        self.hint_label.setText(text)
        QTimer.singleShot(2600, lambda: self.hint_label.setText("")
                          if self.hint_label.text() == text else None)

    def _refresh(self) -> None:
        game = self.game
        canvas = self.board.canvas
        legal: List[Tuple[int, int]] = []
        targets: Dict[Tuple[int, int], str] = {}
        settle: List[Tuple[int, int]] = []
        if self._my_turn():
            if not game.placed_tile:
                legal = game.tile_cells()
            else:
                actions = game.legal_pawn_actions()
                if self.selected_pawn is not None:
                    # a pawn is picked: show only what that pawn can do
                    targets = {a.cell: a.kind for a in actions
                               if a.source == self.selected_pawn and a.cell is not None}
                else:
                    settle = [a.cell for a in actions
                              if a.kind == "settle" and a.cell is not None]
        canvas.set_hints(legal, self.selected_pawn if self._my_turn() else None,
                         targets, settle if self._my_turn() else [])

        self.turn_label.setText(f"Turn {game.turn_number}")
        if game.finished:
            self.phase_label.setText("Game over")
        else:
            phase = ("1. lay a tile" if not game.placed_tile
                     else "2. pawn action (optional)")
            self.phase_label.setText(
                f"{game.names[game.current]} - {phase} - "
                f"{game.tiles_left()} tiles left")
        self.supply_label.setText(
            f"light {game.supply[LIGHT]}   dark {game.supply[DARK]}   "
            f"land {len(game.tiles)} tiles"
            + ("   (bag: the tile is drawn for you)"
               if game.rules.random_colour else ""))
        for colour, btn in self.colour_buttons.items():
            btn.setEnabled(not game.rules.random_colour
                           and game.supply[colour] > 0)
        if game.rules.random_colour:
            if game.drawn is not None:
                self._pick_colour(game.drawn)
        elif game.supply.get(canvas.selected_colour, 0) <= 0:
            # never leave the player holding a colour that has run out
            for colour in (LIGHT, DARK):
                if game.supply[colour] > 0:
                    self._pick_colour(colour)
                    break
        self.skip_button.setEnabled(self._my_turn() and game.placed_tile)
        scores = game.live_scores()
        for i, row in enumerate(self.rows):
            row.update(game.reserve[i], scores[i],
                       i == game.current and not game.finished)
        text = game.status()
        self.statusChanged.emit(text)
        if not self._my_turn() and not game.finished:
            self.hint_label.setText("Waiting for the other tribes…")
        elif self.hint_label.text().startswith("Waiting"):
            self.hint_label.setText("")

    def _show_result(self) -> None:
        game = self.game
        winner = game.winner()
        scores = game.scores
        if winner is None:
            head = "Draw"
        else:
            head = f"{game.names[winner]} wins"
        detail = ", ".join(f"{game.names[i]} {scores[i]}" for i in range(game.players))
        self.hint_label.setText(f"<b>{head}</b><br>{detail} points<br>"
                                f"<span style='color:#98a1b5'>{len(game.areas())} areas, "
                                f"{len(game.tiles)} tiles</span>")
        self.statusChanged.emit(f"Anarchess - {head} ({detail})")

    # ------------------------------------------------------------------
    def rulings_text(self) -> str:
        rows = "".join(f"<li><b>{k}</b> - {v}</li>" for k, v in RULINGS)
        return f"<h4>Rulings</h4><ol>{rows}</ol>"
