"""
Dialogs: new game, engine management, preferences, training selection,
promotion, about.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import chess

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
                             QProgressBar, QPushButton, QSpinBox, QTabWidget, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.engine import DEFAULT_LEVELS, Level
from ..core.game import TimeControl, VARIANTS
from ..core.players import BuiltInPlayer
from ..core.uci import find_engines
from .board_view import THEMES
from .theme import app_logo
from .pieces import STYLES


# --------------------------------------------------------------------------
# new game
# --------------------------------------------------------------------------

class PlayerConfig(QGroupBox):
    """One side's player setup."""

    def __init__(self, title: str, engines: List[str], default_side: str = "white"):
        super().__init__(title)
        self.engines = engines
        self.layout = QVBoxLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(["Human", "Built-in engine", "UCI engine"])
        self.level = QComboBox()
        self.level.addItems([f"{lv.name} ({lv.elo})" for lv in DEFAULT_LEVELS])
        self.level.setCurrentIndex(6)
        self.personality = QComboBox()
        self.personality.addItems(list(BuiltInPlayer.PERSONALITIES))
        self.engine_combo = QComboBox()
        self.engine_combo.addItems([os.path.basename(p) for p in engines] or ["(none)"])
        self.engine_combo.setToolTip("\n".join(engines) if engines else "No UCI engine found")
        self.limit = QDoubleSpinBox()
        self.limit.setRange(0.05, 300.0)
        self.limit.setValue(1.0)
        self.limit.setSuffix(" s")
        self.depth = QSpinBox()
        self.depth.setRange(0, 40)
        self.depth.setValue(0)
        self.depth.setSpecialValueText("auto")
        self.skill = QSpinBox()
        self.skill.setRange(-1, 20)
        self.skill.setValue(-1)
        self.skill.setSpecialValueText("max")
        self.elo = QSpinBox()
        self.elo.setRange(0, 3400)
        self.elo.setValue(0)
        self.elo.setSpecialValueText("off")
        self.name = QLineEdit("You" if default_side == "white" else "Lucas Club")

        form = QFormLayout()
        form.addRow("Type", self.kind)
        form.addRow("Name", self.name)
        form.addRow("Level", self.level)
        form.addRow("Style", self.personality)
        form.addRow("Engine", self.engine_combo)
        form.addRow("Time/move", self.limit)
        form.addRow("Depth", self.depth)
        form.addRow("Skill", self.skill)
        form.addRow("UCI Elo", self.elo)
        self.layout.addLayout(form)
        self.kind.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        idx = self.kind.currentIndex()
        builtin = idx == 1
        uci = idx == 2
        self.level.setEnabled(builtin)
        self.personality.setEnabled(builtin)
        self.engine_combo.setEnabled(uci)
        self.depth.setEnabled(builtin or uci)
        self.skill.setEnabled(uci)
        self.elo.setEnabled(uci)
        self.limit.setEnabled(True)

    def config(self) -> Dict:
        idx = self.kind.currentIndex()
        return {
            "type": ["human", "builtin", "uci"][idx],
            "name": self.name.text().strip() or ("Human" if idx == 0 else "Engine"),
            "level": self.level.currentText().split(" (")[0],
            "personality": self.personality.currentText(),
            "engine_index": self.engine_combo.currentIndex(),
            "limit_ms": int(self.limit.value() * 1000),
            "depth": self.depth.value(),
            "skill": None if self.skill.value() < 0 else self.skill.value(),
            "elo": 0 if self.elo.value() == 0 else self.elo.value(),
        }

    def set_config(self, cfg: Dict) -> None:
        self.kind.setCurrentIndex({"human": 0, "builtin": 1, "uci": 2}[cfg.get("type", "human")])
        self.name.setText(cfg.get("name", ""))
        for i, lv in enumerate(DEFAULT_LEVELS):
            if lv.name == cfg.get("level"):
                self.level.setCurrentIndex(i)
        self.personality.setCurrentText(cfg.get("personality", "Balanced"))
        self.limit.setValue(cfg.get("limit_ms", 1000) / 1000.0)
        self.depth.setValue(cfg.get("depth", 0))
        self.skill.setValue(-1 if cfg.get("skill") is None else cfg["skill"])
        self.elo.setValue(cfg.get("elo", 0))
        self._sync()


class NewGameDialog(QDialog):
    def __init__(self, parent=None, engines: Optional[List[str]] = None,
                 current: Optional[Dict] = None):
        super().__init__(parent)
        self.setWindowTitle("New game")
        self.engines = engines or find_engines()
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # --- players tab
        players = QWidget()
        pl = QHBoxLayout(players)
        self.white_cfg = PlayerConfig("White", self.engines, "white")
        self.black_cfg = PlayerConfig("Black", self.engines, "black")
        self.black_cfg.kind.setCurrentIndex(1)      # play the engine by default
        self.black_cfg.name.setText("Lucas Club")
        pl.addWidget(self.white_cfg)
        pl.addWidget(self.black_cfg)
        tabs.addTab(players, "Players")

        # --- variant tab
        variant_tab = QWidget()
        vl = QFormLayout(variant_tab)
        self.variant = QComboBox()
        for key, spec in VARIANTS.items():
            self.variant.addItem(spec["label"], key)
        self.variant_label = QLabel(VARIANTS["standard"]["desc"])
        self.variant.currentIndexChanged.connect(self._variant_changed)
        self.fen_edit = QLineEdit()
        self.fen_edit.setPlaceholderText("Optional: start from a FEN position")
        self.chess960 = QSpinBox()
        self.chess960.setRange(0, 959)
        self.chess960.setValue(518)
        self.orientation = QComboBox()
        self.orientation.addItems(["White at the bottom", "Black at the bottom",
                                   "Match the human side"])
        vl.addRow("Variant", self.variant)
        vl.addRow("", self.variant_label)
        vl.addRow("Start FEN", self.fen_edit)
        vl.addRow("Chess960 position", self.chess960)
        vl.addRow("Board", self.orientation)
        tabs.addTab(variant_tab, "Variant")

        # --- clock tab
        clock_tab = QWidget()
        cl = QFormLayout(clock_tab)
        self.preset = QComboBox()
        self.preset.addItems(["Unlimited", "1 min", "3 min", "5 min", "10 min", "15 min",
                              "30 min", "3+2", "5+3", "10+5", "15+10", "30+20",
                              "5 s/move", "10 s/move", "30 s/move", "Custom"])
        self.preset.currentTextChanged.connect(self._preset_changed)
        self.base = QDoubleSpinBox()
        self.base.setRange(0, 240); self.base.setValue(5); self.base.setSuffix(" min")
        self.inc = QDoubleSpinBox()
        self.inc.setRange(0, 120); self.inc.setValue(3); self.inc.setSuffix(" s")
        self.movestogo = QSpinBox()
        self.movestogo.setRange(0, 60)
        self.per_move = QDoubleSpinBox()
        self.per_move.setRange(0, 300); self.per_move.setSuffix(" s/move")
        cl.addRow("Preset", self.preset)
        cl.addRow("Base time", self.base)
        cl.addRow("Increment", self.inc)
        cl.addRow("Moves to go", self.movestogo)
        cl.addRow("Fixed time per move", self.per_move)
        tabs.addTab(clock_tab, "Clock")

        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._preset_changed(self.preset.currentText())
        if current:
            self.white_cfg.set_config(current.get("white", {}))
            self.black_cfg.set_config(current.get("black", {}))

    def _variant_changed(self) -> None:
        key = self.variant.currentData()
        self.variant_label.setText(VARIANTS.get(key, {}).get("desc", ""))
        self.chess960.setEnabled(key == "chess960")

    def _preset_changed(self, text: str) -> None:
        presets = {
            "1 min": (1, 0), "3 min": (3, 0), "5 min": (5, 0), "10 min": (10, 0),
            "15 min": (15, 0), "30 min": (30, 0), "3+2": (3, 2), "5+3": (5, 3),
            "10+5": (10, 5), "15+10": (15, 10), "30+20": (30, 20),
        }
        unlimited = text == "Unlimited"
        self.per_move.setValue(0)
        if unlimited:
            self.base.setValue(0); self.inc.setValue(0)
        elif text.endswith("/move"):
            try:
                self.per_move.setValue(float(text.split()[0]))
            except Exception:
                pass
        elif text in presets:
            self.base.setValue(presets[text][0])
            self.inc.setValue(presets[text][1])

    def config(self) -> Dict:
        unlimited = self.preset.currentText() == "Unlimited"
        return {
            "white": self.white_cfg.config(),
            "black": self.black_cfg.config(),
            "variant": self.variant.currentData(),
            "fen": self.fen_edit.text().strip() or None,
            "chess960": self.chess960.value(),
            "orientation": self.orientation.currentIndex(),
            "tc": TimeControl(base_minutes=self.base.value(),
                              increment_seconds=self.inc.value(),
                              movestogo=self.movestogo.value(),
                              per_move_seconds=self.per_move.value(),
                              unlimited=unlimited),
        }


# --------------------------------------------------------------------------
# engine management
# --------------------------------------------------------------------------

class EngineManagerDialog(QDialog):
    def __init__(self, parent=None, engines: Optional[List[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("Engines")
        self.setMinimumWidth(620)
        self.engines = list(engines or [])
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        for path in self.engines:
            self.list.addItem(path)
        layout.addWidget(QLabel("UCI engines known to the program:"))
        layout.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton("Add…")
        add.clicked.connect(self._add)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        scan = QPushButton("Scan again")
        scan.clicked.connect(self._scan)
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(scan)
        row.addStretch(1)
        layout.addLayout(row)
        self.status = QLabel("")
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select a UCI engine executable")
        if path and path not in self.engines:
            self.engines.append(path)
            self.list.addItem(path)
            os.chmod(path, 0o755) if os.name != "nt" else None

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self.engines.pop(row)

    def _scan(self) -> None:
        found = find_engines()
        for path in found:
            if path not in self.engines:
                self.engines.append(path)
                self.list.addItem(path)
        self.status.setText(f"Scan complete: {len(found)} engine(s) found")

    def result_paths(self) -> List[str]:
        return self.engines


# --------------------------------------------------------------------------
# preferences
# --------------------------------------------------------------------------

class PreferencesDialog(QDialog):
    def __init__(self, parent=None, settings: Optional[Dict] = None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        s = dict(settings or {})
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.board_theme = QComboBox()
        self.board_theme.addItems(list(THEMES))
        self.board_theme.setCurrentText(s.get("board_theme", "wood"))
        self.piece_style = QComboBox()
        self.piece_style.addItems(list(STYLES))
        self.piece_style.setCurrentText(s.get("piece_style", "classic"))
        self.animate = QCheckBox()
        self.animate.setChecked(bool(s.get("animate", True)))
        self.coords = QCheckBox()
        self.coords.setChecked(bool(s.get("coords", True)))
        self.legal = QCheckBox()
        self.legal.setChecked(bool(s.get("legal_moves", True)))
        self.sound = QCheckBox()
        self.sound.setChecked(bool(s.get("sound", True)))
        self.volume = QSpinBox()
        self.volume.setRange(0, 100)
        self.volume.setValue(int(s.get("volume", 80)))
        self.auto_queen = QCheckBox()
        self.auto_queen.setChecked(bool(s.get("auto_queen", True)))
        self.auto_save = QCheckBox()
        self.auto_save.setChecked(bool(s.get("auto_save", True)))
        self.show_eval = QCheckBox()
        self.show_eval.setChecked(bool(s.get("show_eval", True)))
        self.battle_on_capture = QCheckBox("Animate captures in battle mode")
        self.battle_on_capture.setChecked(bool(s.get("battle_captures", True)))
        self.battle_quality = QComboBox()
        self.battle_quality.addItems(["Low", "Medium", "High", "Ultra"])
        self.battle_quality.setCurrentText(s.get("battle_quality", "High"))
        self.battle_camera = QComboBox()
        self.battle_camera.addItems(["Classic", "Cinematic", "Top-down"])
        self.battle_camera.setCurrentText(s.get("battle_camera", "Cinematic"))
        form.addRow("Board theme", self.board_theme)
        form.addRow("Piece set", self.piece_style)
        form.addRow("Animate moves", self.animate)
        form.addRow("Show coordinates", self.coords)
        form.addRow("Show legal moves", self.legal)
        form.addRow("Sound", self.sound)
        form.addRow("Volume %", self.volume)
        form.addRow("Promote to queen automatically", self.auto_queen)
        form.addRow("Save games automatically", self.auto_save)
        form.addRow("Show evaluation", self.show_eval)
        self.duels_button = QPushButton("How the pieces move and die…")
        self.duels_button.setToolTip(
            "Six ways to walk and thirty duels: a different animation for "
            "every capture, as in the 1988 original.")
        self.duels_button.clicked.connect(self._show_duels)
        form.addRow("Battle quality", self.battle_quality)
        form.addRow("Battle camera", self.battle_camera)
        form.addRow("", self.battle_on_capture)
        form.addRow("", self.duels_button)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_duels(self) -> None:
        DuelsDialog(self).exec()

    def settings(self) -> Dict:
        return {
            "board_theme": self.board_theme.currentText(),
            "piece_style": self.piece_style.currentText(),
            "animate": self.animate.isChecked(),
            "coords": self.coords.isChecked(),
            "legal_moves": self.legal.isChecked(),
            "sound": self.sound.isChecked(),
            "volume": self.volume.value(),
            "auto_queen": self.auto_queen.isChecked(),
            "auto_save": self.auto_save.isChecked(),
            "show_eval": self.show_eval.isChecked(),
            "battle_captures": self.battle_on_capture.isChecked(),
            "battle_quality": self.battle_quality.currentText(),
            "battle_camera": self.battle_camera.currentText(),
        }


# --------------------------------------------------------------------------
# the thirty duels
# --------------------------------------------------------------------------

class DuelsDialog(QDialog):
    """How the pieces move, and how they die.

    Six ways to walk and thirty duels, as the 1988 original had them: one
    animation for every permutation of attacker and victim. This is also the
    checklist for "a different animation for each".
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("How the pieces move and die")
        self.resize(660, 560)
        layout = QVBoxLayout(self)
        from ..battle.duels import duel_rows
        from ..battle.gaits import gait_rows

        layout.addWidget(QLabel("<b>Six ways to walk</b> — each rank crosses "
                                "the board in its own way."))
        walks = QTreeWidget()
        walks.setHeaderLabels(["Piece", "Walk", "How it goes"])
        walks.setRootIsDecorated(False)
        walks.setAlternatingRowColors(True)
        for piece, name, line in gait_rows():
            QTreeWidgetItem(walks, [piece, name, line])
        walks.resizeColumnToContents(0)
        walks.setColumnWidth(1, 90)
        walks.setColumnWidth(2, 360)
        layout.addWidget(walks, 1)

        layout.addWidget(QLabel(
            "<b>Thirty duels</b> — every capture is its own animation. Six "
            "pieces can take, five can be taken (a king never is), and no two "
            "of the thirty are the same."))
        table = QTreeWidget()
        table.setHeaderLabels(["Capture", "Duel", "What happens"])
        table.setRootIsDecorated(False)
        table.setAlternatingRowColors(True)
        for key, name, line in duel_rows():
            QTreeWidgetItem(table, [key, name, line])
        table.resizeColumnToContents(0)
        table.setColumnWidth(1, 130)
        table.setColumnWidth(2, 330)
        layout.addWidget(table, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


# --------------------------------------------------------------------------
# training set picker
# --------------------------------------------------------------------------

class TrainingPickerDialog(QDialog):
    """Pick a training set from the imported Lucas Chess data."""

    def __init__(self, parent=None, sets: Optional[List[tuple]] = None,
                 title: str = "Choose a training set"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(560, 420)
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Set", "Items", "Source"])
        self.tree.setAlternatingRowColors(True)
        groups: Dict[str, QTreeWidgetItem] = {}
        for set_id, kind, name, source, count in sets or []:
            group = groups.get(kind)
            if group is None:
                group = QTreeWidgetItem([kind.capitalize(), "", ""])
                groups[kind] = group
                self.tree.addTopLevelItem(group)
            item = QTreeWidgetItem([name, str(count), source])
            item.setData(0, Qt.ItemDataRole.UserRole, set_id)
            group.addChild(item)
        self.tree.expandAll()
        layout.addWidget(self.tree)
        self.tree.itemDoubleClicked.connect(self._accept_item)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_item(self, item, column) -> None:
        if item.data(0, Qt.ItemDataRole.UserRole) is not None:
            self.accept()

    def selected(self) -> Optional[int]:
        item = self.tree.currentItem()
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return data if data is not None else None


# --------------------------------------------------------------------------
# promotion / position / about
# --------------------------------------------------------------------------

class PromotionDialog(QDialog):
    def __init__(self, parent=None, color: chess.Color = chess.WHITE):
        super().__init__(parent)
        self.setWindowTitle("Promotion")
        self.choice = chess.QUEEN
        layout = QHBoxLayout(self)
        for pt, label in ((chess.QUEEN, "Queen"), (chess.ROOK, "Rook"),
                          (chess.BISHOP, "Bishop"), (chess.KNIGHT, "Knight")):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, pt=pt: self._pick(pt))
            layout.addWidget(button)

    def _pick(self, pt: int) -> None:
        self.choice = pt
        self.accept()


class PositionDialog(QDialog):
    """Edit a FEN / set up a position."""

    def __init__(self, parent=None, fen: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Position")
        layout = QVBoxLayout(self)
        self.edit = QPlainTextEdit(fen)
        layout.addWidget(self.edit)
        self.status = QLabel("")
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        fen = self.edit.toPlainText().strip()
        try:
            board = chess.Board(fen)
            board.status()
            self.accept()
        except Exception as exc:
            self.status.setText(f"Invalid FEN: {exc}")

    def fen(self) -> str:
        return self.edit.toPlainText().strip()


def about_dialog(parent=None) -> QMessageBox:
    """About TALOS: the mark, the version and what is actually in the box."""
    from .. import APP_NAME, APP_TAGLINE, APP_VERSION

    from ..core.engine import DEFAULT_LEVELS
    from ..core.game import VARIANTS
    try:
        from ..core.players import BuiltInPlayer
        styles = len(BuiltInPlayer.PERSONALITIES)
    except Exception:                                    # pragma: no cover
        styles = 7
    levels = len(DEFAULT_LEVELS)
    elo_lo = min(lv.elo for lv in DEFAULT_LEVELS)
    elo_hi = max(lv.elo for lv in DEFAULT_LEVELS)
    variants = len([v for v in VARIANTS if str(v).lower() != "standard"])

    box = QMessageBox(parent)
    box.setWindowTitle(f"About {APP_NAME}")
    logo = app_logo(96)
    if not logo.isNull():
        box.setIconPixmap(logo)
    box.setText(
        f"<h2>{APP_NAME}</h2>"
        f"<p><b>{APP_TAGLINE}</b> &mdash; version {APP_VERSION}</p>"
        "<p>A local chess studio: play, train, analyse, or fight. Everything runs "
        "on your own machine &mdash; no accounts, no servers, no telemetry.</p>"
        "<ul>"
        f"<li><b>Play</b> standard chess and {variants} variants, against "
        f"{levels} engine levels from {elo_lo} to {elo_hi} Elo with {styles} "
        "personalities, or against any UCI engine you install (Stockfish "
        "downloads on demand)</li>"
        "<li><b>Train</b> on the real Lucas Chess data: tactics, STS, mates and "
        "endgames, with a learning coach that tracks what you get wrong and "
        "brings it back when it is due</li>"
        "<li><b>Battle Chess</b> &mdash; capture a piece and a procedurally "
        "generated 3D fight plays out. Turn it on or off at will; it is a "
        "feature, not the identity</li>"
        "<li><b>Anarchess</b>, the land-building board game for two to four "
        "players, and <b>Anarchchess</b>, chess with the rules you choose</li>"
        "<li>Analysis with an evaluation graph, MultiPV and blunder detection</li>"
        "</ul>"
        "<p style='color:#9ca3af'>Tactics and training content come from the "
        "Lucas Chess project (GPLv2+). Battle Chess visuals are procedural: no "
        "third-party art and no sound samples.</p>")
    box.exec()
    return box
