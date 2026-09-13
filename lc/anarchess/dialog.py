"""New-game dialog for Anarchess."""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget)

from .ai import LEVELS
from .rules import PAWNS_PER_PLAYER, PLAYER_NAMES, AnarchessRules


class AnarchessDialog(QDialog):
    def __init__(self, parent=None, players: int = 2,
                 rules: Optional[AnarchessRules] = None):
        super().__init__(parent)
        self.setWindowTitle("New Anarchess game")
        self.setModal(True)
        rules = rules or AnarchessRules()

        layout = QVBoxLayout(self)

        setup = QGroupBox("Table")
        form = QVBoxLayout(setup)
        row = QHBoxLayout()
        row.addWidget(QLabel("Players"))
        self.players = QComboBox()
        for n in (2, 3, 4):
            self.players.addItem(f"{n} players ({PAWNS_PER_PLAYER[n]} pawns each)", n)
        self.players.setCurrentIndex(max(0, min(3, players - 2)))
        self.players.currentIndexChanged.connect(self._sync)
        row.addWidget(self.players, 1)
        form.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Opponents"))
        self.level = QComboBox()
        for name, tip in LEVELS:
            self.level.addItem(name, tip)
        self.level.setCurrentIndex(1)
        row.addWidget(self.level, 1)
        form.addLayout(row)
        layout.addWidget(setup)

        self.seats_box = QGroupBox("Seats")
        self.seats_layout = QVBoxLayout(self.seats_box)
        self.seat_combos: List[QComboBox] = []
        layout.addWidget(self.seats_box)

        opts = QGroupBox("Rules")
        opts_layout = QVBoxLayout(opts)
        self.bag = QCheckBox("Draw tiles from a bag (colour is not a choice)")
        self.bag.setChecked(rules.random_colour)
        self.bag.setToolTip(
            "The published summary does not say whether you choose the tile "
            "colour or draw it.  Drawing gives a more varied landscape.")
        self.support = QCheckBox("Attacks need a supporting pawn")
        self.support.setChecked(rules.attack_needs_support)
        self.captives = QCheckBox("Captured pawns return to the reserve")
        self.captives.setChecked(rules.captives_return)
        self.per_tile = QCheckBox("Score one point per tile (not per area)")
        self.per_tile.setChecked(rules.score_per_tile)
        for box in (self.bag, self.support, self.captives, self.per_tile):
            opts_layout.addWidget(box)
        layout.addWidget(opts)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync()

    # ------------------------------------------------------------------
    def _sync(self) -> None:
        while self.seats_layout.count():
            item = self.seats_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.seat_combos = []
        n = self.players.currentData()
        for i in range(n):
            combo = QComboBox()
            combo.addItem("Human", "human")
            combo.addItem("Computer", "bot")
            combo.setCurrentIndex(0 if i == 0 else 1)
            self.seats_layout.addWidget(combo)
            self.seat_combos.append(combo)

    # ------------------------------------------------------------------
    def config(self) -> Dict:
        seats = [c.currentData() for c in self.seat_combos]
        human = seats.index("human") if "human" in seats else 0
        return {
            "players": self.players.currentData(),
            "seats": seats,
            "human": human,
            "level": self.level.currentIndex() + 1,
            "names": PLAYER_NAMES[:self.players.currentData()],
            "rules": AnarchessRules(
                random_colour=self.bag.isChecked(),
                attack_needs_support=self.support.isChecked(),
                captives_return=self.captives.isChecked(),
                score_per_tile=self.per_tile.isChecked()),
        }
