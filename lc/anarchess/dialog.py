"""New-game dialog for Anarchess."""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QSpinBox, QVBoxLayout)

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
        opts_form = QFormLayout(opts)

        self.tile_count = QComboBox()
        for count, label in ((16, "16 of each colour - a short game"),
                             (24, "24 of each colour"),
                             (32, "32 of each colour - the full land")):
            self.tile_count.addItem(label, count)
        self.tile_count.setCurrentIndex(
            max(0, self.tile_count.findData(rules.tiles_per_colour)))
        opts_form.addRow("Tiles", self.tile_count)

        self.mode = QComboBox()
        self.mode.addItem("Two tribes", "standard")
        self.mode.addItem("Solo - one player, target 192", "solo")
        self.mode.addItem("Anarcheckers - pieces jump", "checkers")
        self.mode.setCurrentIndex(
            self.mode.findData("solo" if rules.solo else
                               ("checkers" if rules.checkers else "standard")))
        self.mode.currentIndexChanged.connect(self._sync)
        opts_form.addRow("Game", self.mode)

        self.single_touch = QCheckBox(
            "A tile touching one other must be the opposite colour")
        self.single_touch.setChecked(rules.single_touch_opposite)
        self.protect_last = QCheckBox(
            "On the last turn a pawn may not move where it can be attacked")
        self.protect_last.setChecked(rules.protect_last_move)
        self.tax = QCheckBox("The largest area is taxed to one point a tile")
        self.tax.setChecked(rules.tax_largest_area)
        self.bonus = QCheckBox(
            "An area matching its owner's colour scores three a tile")
        self.bonus.setChecked(rules.same_colour_bonus)
        self.captives = QCheckBox("Captured pawns return to their reserve")
        self.captives.setChecked(rules.captives_return)
        for box in (self.single_touch, self.protect_last, self.tax,
                    self.bonus, self.captives):
            opts_form.addRow(box)

        self.penalty = QSpinBox()
        self.penalty.setRange(0, 12)
        self.penalty.setValue(rules.reserve_penalty)
        self.penalty.setSuffix(" points")
        opts_form.addRow("Pawn left in the reserve", self.penalty)
        layout.addWidget(opts)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync()

    # ------------------------------------------------------------------
    def _sync(self) -> None:
        # SOLO is one player playing the two original tribes, not a 2–4 player
        # table with all seats marked human.  Pin the dialog to two tribes as
        # soon as it is selected; config() repeats that guard for callers that
        # set widgets programmatically.
        solo = self.mode.currentData() == "solo"
        if solo and self.players.currentData() != 2:
            self.players.blockSignals(True)
            self.players.setCurrentIndex(self.players.findData(2))
            self.players.blockSignals(False)
        self.players.setEnabled(not solo)
        self.level.setEnabled(not solo)
        self.seats_box.setEnabled(not solo)

        while self.seats_layout.count():
            item = self.seats_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.seat_combos = []
        n = 2 if solo else self.players.currentData()
        for i in range(n):
            combo = QComboBox()
            combo.addItem("Human", "human")
            combo.addItem("Computer", "bot")
            combo.setCurrentIndex(0 if (i == 0 or solo) else 1)
            combo.setEnabled(not solo)
            self.seats_layout.addWidget(combo)
            self.seat_combos.append(combo)

    # ------------------------------------------------------------------
    def config(self) -> Dict:
        solo = self.mode.currentData() == "solo"
        players = 2 if solo else self.players.currentData()
        seats = (["human"] * players if solo
                 else [c.currentData() for c in self.seat_combos][:players])
        human = 0 if solo else (seats.index("human") if "human" in seats else 0)
        return {
            "players": players,
            "seats": seats,
            "human": human,
            "level": self.level.currentIndex() + 1,
            "names": PLAYER_NAMES[:players],
            "rules": AnarchessRules(
                tiles_per_colour=self.tile_count.currentData(),
                solo=solo,
                checkers=self.mode.currentData() == "checkers",
                single_touch_opposite=self.single_touch.isChecked(),
                protect_last_move=self.protect_last.isChecked(),
                tax_largest_area=self.tax.isChecked(),
                same_colour_bonus=self.bonus.isChecked(),
                captives_return=self.captives.isChecked(),
                reserve_penalty=self.penalty.value()),
        }
