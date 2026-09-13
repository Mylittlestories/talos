"""The Anarchchess rulebook editor."""

from __future__ import annotations

from typing import Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QGroupBox, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

from ..variants import (ACTIVE, ANARCHY, CURATED, RULE_BOOK, AnarchRules,
                        set_active_rules)
from .theme import themed_icon

CURATED_KEYS = ("en_passant_forced", "knooks", "c4_bomb", "double_check_wins",
                "king_no_c2", "il_vaticano", "siberian_swipe",
                "vertical_castle", "knight_boost", "dismount", "queen_decay")


class QComboBoxPreset(QComboBox):
    """Tiny wrapper so the dialog can pick which rulebook it edits."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItem("Anarchchess", "anarchchess")
        self.addItem("Full anarchy", "anarchy")


PRESET_OBJECTS = {"anarchchess": CURATED, "anarchy": ANARCHY}


class AnarchyRulesDialog(QDialog):
    """Switch every anarchic rule on or off, per preset."""

    def __init__(self, parent=None, preset: str = "anarchchess"):
        super().__init__(parent)
        self.preset = preset
        self.setWindowTitle("Anarchchess rules")
        self.setModal(True)
        self.resize(560, 620)
        self.setWindowIcon(themed_icon("anarchy", "midnight"))

        layout = QVBoxLayout(self)

        head = QHBoxLayout()
        head.addWidget(QLabel("Rulebook"))
        self.preset_combo = QComboBoxPreset(self)
        self.preset_combo.currentIndexChanged.connect(self._load)
        head.addWidget(self.preset_combo, 1)
        for label, preset in (("Curated", "curated"), ("Full anarchy", "anarchy")):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, p=preset: self._apply_preset(p))
            head.addWidget(btn)
        layout.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.form = QVBoxLayout(body)
        self.boxes: Dict[str, QCheckBox] = {}
        for group, keys in (("The famous house rules", CURATED_KEYS),
                            ("Only for the brave",
                             [k for k, *_ in RULE_BOOK if k not in CURATED_KEYS])):
            box = QGroupBox(group)
            col = QVBoxLayout(box)
            for key in keys:
                text, tip = self._describe(key)
                cb = QCheckBox(text)
                cb.setToolTip(tip)
                self.boxes[key] = cb
                col.addWidget(cb)
            self.form.addWidget(box)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("dim")
        layout.addWidget(self.count_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()

    # ------------------------------------------------------------------
    @staticmethod
    def _describe(key: str):
        for name, title, tip in RULE_BOOK:
            if name == key:
                return title, tip
        return key, ""

    def _load(self) -> None:
        preset = self.preset_combo.currentData()
        rules = ACTIVE.get(preset) or PRESET_OBJECTS.get(preset) or CURATED
        for key, box in self.boxes.items():
            box.setChecked(bool(getattr(rules, key, False)))
        self._count()

    def _count(self) -> None:
        on = sum(1 for b in self.boxes.values() if b.isChecked())
        self.count_label.setText(
            f"{on} of {len(self.boxes)} rules active - "
            "the curated rulebook is the way the community plays it.")

    def _apply_preset(self, which: str) -> None:
        source = CURATED if which == "curated" else ANARCHY
        for key, box in self.boxes.items():
            box.setChecked(bool(getattr(source, key, False)))
        self._count()

    def _accept(self) -> None:
        preset = self.preset_combo.currentData()
        data = {key: box.isChecked() for key, box in self.boxes.items()}
        set_active_rules(preset, AnarchRules(**data))
        self.accept()




class AnarchyRulesBrowser(QDialog):
    """A read-only explanation of every rule, for the curious."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Anarchchess - the rules")
        self.resize(620, 560)
        view = QTextBrowser()
        rows = "".join(
            f"<tr><td style='padding:6px 10px'><b>{title}</b></td>"
            f"<td style='padding:6px 10px; color:#98a1b5'>{tip}</td></tr>"
            for _key, title, tip in RULE_BOOK)
        view.setHtml(
            "<h2 style='color:#f0b429'>Anarchchess</h2>"
            "<p style='color:#98a1b5'>The house rules the community plays, "
            "collected from r/AnarchyChess, anarchychess.org and the "
            "Anarchchess bots. Everything here is a switch: turn it off and "
            "the rule simply does not exist.</p>"
            f"<table cellspacing='0'>{rows}</table>"
            "<h3 style='color:#f0b429'>How the pieces move</h3>"
            "<p style='color:#98a1b5'>Exactly as in chess, with these "
            "additions:<br><br>"
            "<b>Knook</b> - a knight fused with a friendly rook. It moves as "
            "either one, and is drawn with an amber badge.<br>"
            "<b>Il Vaticano</b> - two friendly bishops three squares apart on "
            "a diagonal swap places and take everything between them.<br>"
            "<b>Siberian Swipe</b> - an unmoved rook takes the enemy rook "
            "across the board on the same file, jumping the pieces between.<br>"
            "<b>Vertical castling</b> - the king and a rook on its file trade "
            "places along the file.</p>")
        layout = QVBoxLayout(self)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
