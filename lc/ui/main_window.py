"""
The main window: menus, panels and the controller that glues everything
together (play, engines, clocks, analysis, training, database, battle mode).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Dict, List, Optional, Sequence, Tuple

import chess
import chess.pgn
import io as _io

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QPixmap
from PyQt6.QtWidgets import QSizePolicy
from PyQt6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QHBoxLayout,
                             QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox,
                             QProgressBar, QPushButton, QSplitter, QStackedWidget,
                             QStatusBar, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from .. import APP_FULL_NAME, APP_NAME, APP_TAGLINE, window_title
from .theme import PALETTE_NAMES, themed_icon

from ..core.engine import DEFAULT_LEVELS, Level, level_by_name
from ..core.game import Clock, Game, TimeControl, VARIANTS, format_clock
from ..core.players import BuiltInPlayer, HumanPlayer, Player, UCIPlayer
from ..core.uci import Limit, find_engines
from ..training import sessions
from ..training.panel import TrainingPanel
from .board_view import Arrow, BoardView, Marker, THEMES
from .dialogs import (EngineManagerDialog, NewGameDialog, PositionDialog,
                      PreferencesDialog, PromotionDialog, TrainingPickerDialog,
                      about_dialog)
from .panels import (ClockWidget, EngineInfoPanel, EvalBar, EvalGraph, MaterialWidget,
                     MoveListWidget, PocketStrip)
from .pieces import STYLES, PiecePainter
from .sounds import SoundBank

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data")


class MainWindow(QMainWindow):
    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_FULL_NAME)
        self.resize(1280, 860)

        self.settings_path = os.path.join(DATA_DIR, "settings.json")
        self.settings = self._load_settings()
        self.db = self._open_db()
        try:
            from ..training.learning import Learner
            self.learner = Learner(self.db)
        except Exception:
            self.learner = None
        self.engines: List[str] = find_engines()
        self.sounds = SoundBank(self.settings.get("sound", True),
                                self.settings.get("volume", 80) / 100.0)

        self.game = Game()
        self._uci_cache: Dict[str, Player] = {}
        self._retired: List[Player] = []
        self.game_cfg: Optional[Dict] = None
        self.pending_move: Optional[chess.Move] = None
        self.training_session = None
        self.training_kind: Optional[str] = None
        self.analysis_running = False
        self.analysis_player: Optional[Player] = None
        self.eval_history: List[Tuple[int, float, Optional[int]]] = []
        self.last_eval: Tuple[float, Optional[int]] = (0.0, None)
        self.hint_level = 0
        self.show_solution = False
        self._pending_reply: Optional[chess.Move] = None
        self.blindfold_counter = 0

        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._connect()
        self._apply_settings()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(200)
        self._clock_timer.timeout.connect(self._tick_clocks)
        self._clock_timer.start()
        self.new_game(interactive=False)

    # -- settings / db --------------------------------------------------
    def _load_settings(self) -> Dict:
        defaults = {
            "board_theme": "wood", "piece_style": "classic", "animate": True,
            "coords": True, "legal_moves": True, "sound": True, "volume": 80,
            "auto_queen": True, "auto_save": True, "show_eval": True,
            "battle_captures": True, "battle_quality": "High", "battle_camera": "Cinematic",
            "battle_gore": "Classic", "ui_theme": "midnight",
            "analysis_depth_ms": 1200, "multipv": 3,
            "engines": [], "last_white": {}, "last_black": {},
            "variant": "standard", "tc": {},
        }
        try:
            with open(self.settings_path) as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                defaults.update(loaded)
        except Exception:
            pass
        # older builds stored the gore level as a boolean
        gore = defaults.get("battle_gore", "Classic")
        if gore is True or gore == "On":
            gore = "Classic"
        elif gore is False or gore in ("Off", "None", ""):
            gore = "Arcade"
        if gore not in ("Classic", "Arcade"):
            gore = "Classic"
        defaults["battle_gore"] = gore
        if defaults.get("ui_theme") not in ("midnight", "slate", "parchment"):
            defaults["ui_theme"] = "midnight"
        return defaults

    def save_settings(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(self.settings_path, "w") as fh:
                json.dump(self.settings, fh, indent=1)
        except Exception:
            pass

    def _open_db(self) -> sqlite3.Connection:
        path = os.path.join(DATA_DIR, "lucas.db")
        os.makedirs(DATA_DIR, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "puzzles" not in tables:
            # fresh/empty database: create the schema so everything still runs
            from ..data.importer import SCHEMA
            conn.executescript(SCHEMA)
            conn.commit()
        return conn

    # ------------------------------------------------------------------
    # ui construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        board_column = QWidget()
        board_layout = QVBoxLayout(board_column)
        board_layout.setContentsMargins(0, 0, 0, 0)
        board_layout.setSpacing(2)
        self.stack = QStackedWidget()
        self.board = BoardView(theme=self.settings.get("board_theme", "wood"),
                               piece_style=self.settings.get("piece_style", "classic"))
        self.stack.addWidget(self.board)
        self.battle_widget = None          # created on demand
        self.anarchess = None              # created on demand
        self.ui_theme = self.settings.get("ui_theme", "midnight")
        board_layout.addWidget(self.stack, 1)
        # crazyhouse pockets (hidden unless the variant uses them)
        self.black_pocket = PocketStrip(color=chess.BLACK)
        self.white_pocket = PocketStrip(color=chess.WHITE)
        self.black_pocket.setVisible(False)
        self.white_pocket.setVisible(False)
        self.black_pocket.pieceClicked.connect(self.on_pocket_clicked)
        self.white_pocket.pieceClicked.connect(self.on_pocket_clicked)
        board_layout.addWidget(self.black_pocket)
        board_layout.addWidget(self.white_pocket)
        layout.addWidget(board_column, 1)

        # --- right side
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right.setFixedWidth(320)

        self.black_clock = ClockWidget("Black")
        self.white_clock = ClockWidget("White")
        right_layout.addWidget(self.black_clock)
        right_layout.addWidget(self.white_clock)

        self.material = MaterialWidget()
        right_layout.addWidget(self.material)

        eval_row = QHBoxLayout()
        self.eval_bar = EvalBar()
        self.engine_panel = EngineInfoPanel(lines=self.settings.get("multipv", 3))
        eval_row.addWidget(self.eval_bar)
        eval_row.addWidget(self.engine_panel, 1)
        right_layout.addLayout(eval_row, 1)

        self.eval_graph = EvalGraph()
        self.eval_graph.plyClicked.connect(self.goto_ply)
        right_layout.addWidget(self.eval_graph)

        self.tabs = QTabWidget()
        self.move_list = MoveListWidget()
        self.move_list.plyClicked.connect(self.goto_ply)
        self.training_panel = TrainingPanel()
        self.tabs.addTab(self.move_list, "Moves")
        self.tabs.addTab(self.training_panel, "Training")
        right_layout.addWidget(self.tabs, 2)
        layout.addWidget(right, 0)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("Ready")
        self.status.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(120)
        self.progress.setVisible(False)
        self.status.addPermanentWidget(self.progress)

    def _build_menus(self) -> None:
        menu = self.menuBar()

        # ---- Game
        game_menu = menu.addMenu("&Game")
        act = self._action("&New game…", self.new_game, "Ctrl+N", game_menu)
        act = self._action("New game with same settings", lambda: self.new_game(interactive=False,
                                                                                reuse=True),
                           "Ctrl+Shift+N", game_menu)
        self.variant_menu = game_menu.addMenu("&Variant")
        group = QActionGroup(self.variant_menu)
        for key, spec in VARIANTS.items():
            a = QAction(spec["label"], self)
            a.setCheckable(True)
            a.setChecked(key == "standard")
            a.setData(key)
            a.triggered.connect(lambda _=False, k=key: self.set_variant(k))
            group.addAction(a)
            self.variant_menu.addAction(a)
        game_menu.addSeparator()
        self._action("Set up &position…", self.setup_position, "Ctrl+Shift+P", game_menu)
        self._action("&Takeback", self.takeback, "Ctrl+Z", game_menu)
        self._action("&Resign", self.resign, "Ctrl+R", game_menu)
        self._action("&Flip board", self.board.flip, "F", game_menu)
        game_menu.addSeparator()
        self._action("&Save game to database", self.save_game, "Ctrl+S", game_menu)
        self._action("Export &PGN…", self.export_pgn, "Ctrl+E", game_menu)
        self._action("&Import PGN…", self.import_pgn, "Ctrl+O", game_menu)
        game_menu.addSeparator()
        self._action("&Quit", self.close, "Ctrl+Q", game_menu)

        # ---- Train
        train_menu = menu.addMenu("&Train")
        items = [
            ("Tactics & mates (solve the line)", "solve"),
            ("Strategy (STS)", "sts"),
            ("Endgame technique", "endings"),
            ("Guess the move (real games)", "guess"),
            ("Openings", "openings"),
            ("Everest ladder", "everest"),
            ("Resistance", "resistance"),
            ("Estimate your Elo", "micelo"),
            ("Blindfold game", "blindfold"),
            ("Turn on the lights (memory)", "lights"),
            ("Routes (piece navigation)", "routes"),
            ("Square colours", "colours"),
        ]
        for label, key in items:
            a = QAction(label, self)
            a.triggered.connect(lambda _=False, k=key: self.start_training(k))
            train_menu.addAction(a)
        train_menu.addSeparator()
        self._action("Stop training", self.stop_training, "Esc", train_menu)

        # ---- Analyse
        analyse_menu = menu.addMenu("&Analyse")
        self.analyse_action = QAction("Continuous analysis", self)
        self.analyse_action.setCheckable(True)
        self.analyse_action.triggered.connect(self.toggle_analysis)
        analyse_menu.addAction(self.analyse_action)
        self._action("Analyse the whole game", self.analyse_game, "Ctrl+A", analyse_menu)
        self._action("Show best move (hint)", self.show_hint, "Ctrl+H", analyse_menu)
        self._action("Clear arrows and marks", self.board.clear_overlays, "", analyse_menu)

        # ---- Database
        db_menu = menu.addMenu("&Database")
        self._action("Browse saved games…", self.browse_games, "", db_menu)
        self._action("Browse the master game database…", self.browse_database, "", db_menu)
        self._action("Opening explorer…", self.opening_explorer, "", db_menu)

        # ---- Battle
        battle_menu = menu.addMenu("&Battle")
        self.battle_action = QAction("Battle Chess mode", self)
        self.battle_action.setCheckable(True)
        self.battle_action.setShortcut("Ctrl+B")
        self.battle_action.triggered.connect(self.toggle_battle)
        battle_menu.addAction(self.battle_action)
        battle_menu.addSeparator()
        for label, key in (("Camera: classic", "Classic"), ("Camera: cinematic", "Cinematic"),
                           ("Camera: top-down", "Top-down")):
            a = QAction(label, self)
            a.triggered.connect(lambda _=False, k=key: self.set_battle_camera(k))
            battle_menu.addAction(a)
        battle_menu.addSeparator()
        gore_menu = battle_menu.addMenu("Gore")
        gore_group = QActionGroup(gore_menu)
        for level, tip in (("Classic", "1988 tone: decapitations, shattering, "
                                       "stylised blood spray and stains"),
                           ("Arcade", "No blood at all - dust, sparks and debris only")):
            a = QAction(level, self)
            a.setCheckable(True)
            a.setToolTip(tip)
            a.setChecked(self.settings.get("battle_gore", "Classic") == level)
            a.triggered.connect(lambda _=False, k=level: self.set_gore(k))
            gore_group.addAction(a)
            gore_menu.addAction(a)

        self._action("Learning coach…", self.show_learning, "Ctrl+J", train_menu)
        self._action("Review what is due", self.review_due, "", train_menu)
        self._action("Train my weakest theme", self.train_weakest, "",
                     train_menu)
        train_menu.addSeparator()

        # ---- Anarchy
        anarchy_menu = menu.addMenu("A&narchy")
        act = self._action("Anarchess - the land before Chess…",
                           self.show_anarchess, "Ctrl+Shift+A", anarchy_menu)
        act.setIcon(themed_icon("anarchess", self.ui_theme))
        anarchy_menu.addSeparator()
        self._action("How the rules work…", self.show_anarchy_rules, "",
                     anarchy_menu)
        self._action("Choose the rules…", self.edit_anarchy_rules, "",
                     anarchy_menu)
        anarchy_menu.addSeparator()
        for label, key in (("Curated rulebook", "anarchchess"),
                           ("Full anarchy", "anarchy")):
            a = QAction(label, self)
            a.triggered.connect(lambda _=False, k=key: self.set_variant(k))
            anarchy_menu.addAction(a)

        # ---- View
        view_menu = menu.addMenu("&View")
        ui_menu = view_menu.addMenu("Interface theme")
        ui_group = QActionGroup(ui_menu)
        for name in PALETTE_NAMES:
            a = QAction(name.capitalize(), self)
            a.setCheckable(True)
            a.setChecked(name == self.ui_theme)
            a.triggered.connect(lambda _=False, n=name: self.set_ui_theme(n))
            ui_group.addAction(a)
            ui_menu.addAction(a)
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("Board theme")
        group = QActionGroup(theme_menu)
        for name in THEMES:
            a = QAction(name.capitalize(), self)
            a.setCheckable(True)
            a.setChecked(name == self.settings.get("board_theme"))
            a.triggered.connect(lambda _=False, n=name: self.set_theme(n))
            group.addAction(a)
            theme_menu.addAction(a)
        piece_menu = view_menu.addMenu("Piece set")
        group = QActionGroup(piece_menu)
        for name in STYLES:
            a = QAction(name.capitalize(), self)
            a.setCheckable(True)
            a.setChecked(name == self.settings.get("piece_style"))
            a.triggered.connect(lambda _=False, n=name: self.set_piece_style(n))
            group.addAction(a)
            piece_menu.addAction(a)
        view_menu.addSeparator()
        self.coords_action = QAction("Coordinates", self)
        self.coords_action.setCheckable(True)
        self.coords_action.setChecked(self.settings.get("coords", True))
        self.coords_action.triggered.connect(self.toggle_coords)
        view_menu.addAction(self.coords_action)
        self.legal_action = QAction("Legal move markers", self)
        self.legal_action.setCheckable(True)
        self.legal_action.setChecked(self.settings.get("legal_moves", True))
        self.legal_action.triggered.connect(self.toggle_legal)
        view_menu.addAction(self.legal_action)
        self.sound_action = QAction("Sound", self)
        self.sound_action.setCheckable(True)
        self.sound_action.setChecked(self.settings.get("sound", True))
        self.sound_action.triggered.connect(self.toggle_sound)
        view_menu.addAction(self.sound_action)
        self._action("Preferences…", self.preferences, "Ctrl+,", view_menu)

        # ---- Engines
        engine_menu = menu.addMenu("&Engines")
        self._action("Manage engines…", self.manage_engines, "", engine_menu)
        self._action("Install Stockfish…", self.install_stockfish, "", engine_menu)
        engine_menu.addSeparator()
        self.level_menu = engine_menu.addMenu("Built-in level")
        group = QActionGroup(self.level_menu)
        for lv in DEFAULT_LEVELS:
            a = QAction(f"{lv.name} ({lv.elo})", self)
            a.setCheckable(True)
            a.setChecked(lv.name == "Club")
            a.triggered.connect(lambda _=False, n=lv.name: self.set_engine_level(n))
            group.addAction(a)
            self.level_menu.addAction(a)
        self.personality_menu = engine_menu.addMenu("Personality")
        for name in BuiltInPlayer.PERSONALITIES:
            a = QAction(name, self)
            a.triggered.connect(lambda _=False, n=name: self.set_personality(n))
            self.personality_menu.addAction(a)

        # ---- Help
        help_menu = menu.addMenu("&Help")
        self._action("Keyboard shortcuts", self.show_shortcuts, "F1", help_menu)
        self._action("About", lambda: about_dialog(self), "", help_menu)

    def _action(self, text, slot, shortcut=None, parent=None) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        (parent or self).addAction(action)
        if isinstance(parent, QMenu):
            parent.addAction(action)
        return action

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.setIconSize(QSize(20, 20))
        self.addToolBar(bar)
        for text, slot, tip, icon in (
                ("New", self.new_game, "Start a new game (Ctrl+N)", "new"),
                ("Train", lambda: self.start_training("solve"),
                 "Open the training centre", "train"),
                ("Takeback", self.takeback, "Undo the last move (Ctrl+Z)", "undo"),
                ("Hint", self.show_hint, "Show the engine's best move (Ctrl+H)", "hint"),
                ("Flip", self.board.flip, "Flip the board (F)", "flip"),
                ("Save", self.save_game, "Save to the database (Ctrl+S)", "save"),
                ("Analyse", self.toggle_analysis, "Continuous analysis", "analyse"),
                ("Battle", self.toggle_battle, "Battle Chess 3D mode (Ctrl+B)", "battle"),
                ("Anarchess", self.show_anarchess,
                 "Play Anarchess, the land before Chess", "anarchess")):
            action = QAction(themed_icon(icon, self.ui_theme, 40), text, self)
            action.triggered.connect(slot)
            action.setToolTip(tip)
            bar.addAction(action)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self.brand_label = QLabel(f"  {APP_NAME}  ")
        self.brand_label.setStyleSheet(
            "color: #f0b429; font-weight: 800; letter-spacing: 2px;")
        bar.addWidget(self.brand_label)

    def _connect(self) -> None:
        self.board.moveRequested.connect(self.on_human_move)
        self.board.illegalMove.connect(lambda _: self.sounds.play("error"))
        self.board.squareRightClicked.connect(self.on_square_right_click)
        self.engine_panel.moveClicked.connect(self.on_engine_line_clicked)
        self.training_panel.hintRequested.connect(self.training_hint)
        self.training_panel.solutionRequested.connect(self.training_solution)
        self.training_panel.retryRequested.connect(self.training_retry)
        self.training_panel.nextRequested.connect(self.training_next)
        self.training_panel.stopRequested.connect(self.stop_training)
        self.training_panel.answerLight.connect(self.training_answer_colour)
        self.black_clock.clicked.connect(self.board.flip)
        self.white_clock.clicked.connect(self.board.flip)

    def _normalise_settings(self) -> None:
        """Repair settings written by older builds (gore used to be a bool)."""
        gore = self.settings.get("battle_gore", "Classic")
        if gore is True or gore == "On":
            gore = "Classic"
        elif gore is False or gore in ("Off", "None", ""):
            gore = "Arcade"
        if gore not in ("Classic", "Arcade"):
            gore = "Classic"
        self.settings["battle_gore"] = gore
        if self.settings.get("ui_theme") not in ("midnight", "slate", "parchment"):
            self.settings["ui_theme"] = "midnight"
        self.ui_theme = self.settings["ui_theme"]

    def _apply_settings(self) -> None:
        self.board.show_coords = self.settings.get("coords", True)
        self.board.show_legal = self.settings.get("legal_moves", True)
        self.board.animate = self.settings.get("animate", True)
        self.board.set_theme(self.settings.get("board_theme", "wood"))
        self.board.set_piece_style(self.settings.get("piece_style", "classic"))

    # ------------------------------------------------------------------
    # game setup
    # ------------------------------------------------------------------
    def new_game(self, interactive: bool = True, reuse: bool = False) -> None:
        cfg = self.game_cfg
        if interactive or cfg is None or not reuse:
            dialog = NewGameDialog(self, self.engines, cfg)
            if interactive:
                if not dialog.exec():
                    if cfg is None:
                        cfg = NewGameDialog(self, self.engines).config()
                    else:
                        return
            cfg = dialog.config()
        self.game_cfg = cfg
        self.settings["last_white"] = cfg["white"]
        self.settings["last_black"] = cfg["black"]
        self.save_settings()

        self._retire_players()
        variant = cfg.get("variant", "standard")
        self.game = Game(variant=variant, fen=cfg.get("fen"), tc=cfg.get("tc"))
        self.game.set_player(chess.WHITE, self._make_player(cfg["white"], chess.WHITE))
        self.game.set_player(chess.BLACK, self._make_player(cfg["black"], chess.BLACK))
        orientation = cfg.get("orientation", 2)
        if orientation == 0:
            self.board.set_orientation(chess.WHITE)
        elif orientation == 1:
            self.board.set_orientation(chess.BLACK)
        else:
            self.board.set_orientation(self._human_side())
        self.eval_history = []
        self.eval_graph.clear()
        self.eval_bar.set_score(0, None)
        self.engine_panel.set_lines([])
        self.move_list.set_moves([])
        self.stop_training(silent=True)
        self.game.positionChanged.connect(self.refresh)
        self.game.gameOver.connect(self.on_game_over)
        self.game.clock.start_for(self.game.turn())
        self.refresh()
        self.sounds.play("start")
        self.status_label.setText(f"{variant} · {self.game.tc.label()}")
        self.maybe_engine_move()

    def _retire_players(self) -> None:
        """Stop thinking threads of the previous game but keep UCI processes."""
        for color in (chess.WHITE, chess.BLACK):
            player = self.game.players.get(color) if hasattr(self, "game") else None
            if player is None:
                continue
            try:
                player.stop()
            except Exception:
                pass
            self._retired.append(player)
        self._retired = self._retired[-12:]
        self._prune_retired()

    def _prune_retired(self) -> None:
        self._retired = [p for p in self._retired if p.thinking()]

    def _human_side(self) -> chess.Color:
        if self.game.players[chess.WHITE].human:
            return chess.WHITE
        return chess.BLACK

    def _make_player(self, cfg: Dict, color: chess.Color) -> Player:
        kind = cfg.get("type", "human")
        if kind == "human":
            return HumanPlayer(cfg.get("name") or ("White" if color == chess.WHITE else "Black"))
        if kind == "builtin":
            player = BuiltInPlayer(level_by_name(cfg.get("level", "Club")),
                                   cfg.get("personality", "Balanced"))
            player.name = cfg.get("name") or player.name
            level = player.level.copy()
            limit = cfg.get("limit_ms")
            if limit:
                level.movetime_ms = limit
            if cfg.get("depth"):
                level.max_depth = cfg["depth"]
            player.set_level(level)
            return player
        # UCI
        paths = self.engines or find_engines()
        if not paths:
            self.status_label.setText("No UCI engine found - using the built-in engine")
            return BuiltInPlayer(level_by_name(cfg.get("level", "Club")), "Balanced")
        index = min(cfg.get("engine_index", 0), len(paths) - 1)
        path = paths[max(0, index)]
        player = self._uci_cache.get(path)
        if player is None:
            player = UCIPlayer(path)
            try:
                player.start()
            except Exception as exc:
                self.status_label.setText(f"Could not start {path}: {exc}")
                return BuiltInPlayer(level_by_name(cfg.get("level", "Club")), "Balanced")
            self._uci_cache[path] = player
        player.limit_ms = cfg.get("limit_ms", 1000)
        player.limit_depth = cfg.get("depth", 0)
        player.skill = cfg.get("skill")
        player.elo = cfg.get("elo") or None
        if cfg.get("name"):
            player.name = cfg["name"]
        player.apply_strength()
        if not getattr(player, "_attached", False):
            self._attach_player(player)
            player._attached = True
        return player

    def _attach_player(self, player: Player) -> None:
        player.finished.connect(lambda res: self.on_engine_result(player, res))
        player.failed.connect(lambda msg: self.on_engine_failed(msg))

    def set_variant(self, key: str) -> None:
        if self.game_cfg is None:
            self.game_cfg = NewGameDialog(self, self.engines).config()
        self.game_cfg["variant"] = key
        self.new_game(interactive=False, reuse=True)

    def setup_position(self) -> None:
        dialog = PositionDialog(self, self.game.board.fen())
        if dialog.exec():
            fen = dialog.fen()
            if self.game_cfg is None:
                self.game_cfg = NewGameDialog(self, self.engines).config()
            self.game_cfg["fen"] = fen
            self.new_game(interactive=False, reuse=True)

    # ------------------------------------------------------------------
    # move handling
    # ------------------------------------------------------------------
    def on_pocket_clicked(self, piece_type: int) -> None:
        """Crazyhouse: select a captured piece to drop it on the board."""
        side = self.game.turn()
        strip = self.white_pocket if side == chess.WHITE else self.black_pocket
        other = self.black_pocket if side == chess.WHITE else self.white_pocket
        other.set_selected(None)
        if not piece_type or strip.selected == piece_type:
            strip.set_selected(None)
            self.board.drop_piece = None
            self.status_label.setText("Drop cancelled.")
        else:
            strip.set_selected(piece_type)
            self.board.drop_piece = piece_type
            self.status_label.setText(
                f"Click an empty square to drop the {chess.piece_name(piece_type)}.")
        self.update()

    def _update_pockets(self) -> None:
        crazy = self.game.variant == "crazyhouse" and hasattr(self.game.board, "pockets")
        self.black_pocket.setVisible(crazy)
        self.white_pocket.setVisible(crazy)
        if not crazy:
            return
        for color, strip in ((chess.WHITE, self.white_pocket), (chess.BLACK, self.black_pocket)):
            pocket = self.game.board.pockets[color]
            strip.set_counts({pt: pocket.count(pt) for pt in
                              (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN)})

    def on_human_move(self, move: chess.Move) -> None:
        if self._pending_reply is not None:
            # the training line's reply is still queued: play it first so the
            # board always matches the position the user is looking at
            self._flush_reply()
        if self.game.is_over():
            return
        player = self.game.current_player()
        if not player.human and self.training_session is None:
            return
        if self.training_session is not None:
            self.training_move(move)
            return
        self.do_move(move)

    def do_move(self, move: chess.Move, comment: str = "") -> bool:
        if self.pending_move is not None:
            return False
        piece = self.game.board.piece_at(move.from_square)
        if piece and piece.piece_type == chess.PAWN and move.promotion and \
                self.settings.get("auto_queen", True) is False:
            dialog = PromotionDialog(self, piece.color)
            if dialog.exec():
                move = chess.Move(move.from_square, move.to_square, promotion=dialog.choice)
        record = self.game.push(move, comment)
        if record is None:
            self.sounds.play("error")
            return False
        self.pending_move = move
        self._play_move_sound(record)
        if self.battle_widget is not None and self.stack.currentWidget() is self.battle_widget:
            self.battle_widget.play_move(record)
        elif self.battle_widget is not None:
            self.battle_widget.sync_position(self.game.board)
        else:
            self.board.play_animation(piece or chess.Piece(chess.PAWN, chess.WHITE),
                                      move.from_square, move.to_square)
        self.pending_move = None
        self.board.drop_piece = None
        self.white_pocket.set_selected(None)
        self.black_pocket.set_selected(None)
        self.after_move(record)
        return True

    def _play_move_sound(self, record) -> None:
        if record.capture is not None:
            self.sounds.play("capture")
        elif record.is_castle:
            self.sounds.play("castle")
        else:
            self.sounds.play("move")
        if record.is_promotion:
            self.sounds.play("promote")
        elif record.check:
            self.sounds.play("check")

    def after_move(self, record) -> None:
        self.refresh()
        if self.game.is_over():
            return
        if self.analysis_running:
            self.start_analysis()
        self.maybe_engine_move()

    def maybe_engine_move(self) -> None:
        if self.game.is_over():
            return
        player = self.game.current_player()
        if player.human:
            return
        self.status_label.setText(f"{player.name} is thinking…")
        limit = None
        if isinstance(player, UCIPlayer):
            clocks = self.game.clock.poll()
            limit = Limit(movetime_ms=player.limit_ms, depth=player.limit_depth or None,
                          wtime_ms=clocks[chess.WHITE] or None,
                          btime_ms=clocks[chess.BLACK] or None,
                          winc_ms=int(self.game.tc.increment_seconds * 1000) or None,
                          binc_ms=int(self.game.tc.increment_seconds * 1000) or None)
        else:
            level = player.level
            limit = Limit(movetime_ms=level.movetime_ms, depth=level.max_depth or None)
        self._attach_player_once(player)
        player.think(self.game.board, limit)

    def _attach_player_once(self, player: Player) -> None:
        if getattr(player, "_attached", False):
            return
        player._attached = True
        self._attach_player(player)

    def on_engine_result(self, player: Player, result) -> None:
        if result is None or result.bestmove is None:
            return
        if self.game.current_player() is not player:
            return
        move = result.bestmove
        if move not in self.game.board.legal_moves:
            return
        self._last_engine_result = result
        self.do_move(move)

    def on_engine_failed(self, message: str) -> None:
        self.status_label.setText(f"Engine error: {message}")

    def on_game_over(self, result: str, reason: str) -> None:
        self.sounds.play("win" if result != "0-1" else "lose")
        names = f"{self.game.players[chess.WHITE].name} vs {self.game.players[chess.BLACK].name}"
        text = f"{result}  ·  {reason}\n{names}"
        # only interrupt the user when they were actually involved: engine vs
        # engine games and training rounds just report in the status bar
        human_involved = any(player.human for player in self.game.players.values())
        if human_involved and self.training_session is None and \
                self.settings.get("show_result_dialog", True):
            QMessageBox.information(self, "Game over", text)
        else:
            self.status_label.setText(f"Game over: {result} · {reason}")
        if self.settings.get("auto_save", True) and len(self.game.records) > 4:
            self.save_game(silent=True)
        if self.training_session is not None:
            self.training_game_over(result, reason)

    # ------------------------------------------------------------------
    # refresh / display
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        board = self.game.board
        last = self.game.records[-1].move if self.game.records else None
        self.board.set_board(board, last)
        self.board.last_move = last
        if self.battle_widget is not None:
            self.battle_widget.sync_position(board)
        sans = [r.san for r in self.game.records]
        comments = {i: r.comment for i, r in enumerate(self.game.records) if r.comment}
        self.move_list.set_moves(sans, comments)
        self.move_list.highlight_ply(len(sans) - 1)
        self._update_material()
        self._update_clocks()
        self._update_names()
        self._update_pockets()
        self._prune_retired()

    def _update_names(self) -> None:
        w = self.game.players[chess.WHITE]
        b = self.game.players[chess.BLACK]
        self.white_clock.set_name(w.name)
        self.black_clock.set_name(b.name)

    def _update_clocks(self) -> None:
        clocks = self.game.clock.poll()
        total = self.game.tc.initial_ms() or 1
        self.white_clock.set_time(clocks[chess.WHITE] if not self.game.tc.unlimited else None,
                                  total if not self.game.tc.per_move_seconds else
                                  int(self.game.tc.per_move_seconds * 1000))
        self.black_clock.set_time(clocks[chess.BLACK] if not self.game.tc.unlimited else None,
                                  total if not self.game.tc.per_move_seconds else
                                  int(self.game.tc.per_move_seconds * 1000))
        self.white_clock.set_active(self.game.turn() == chess.WHITE and not self.game.is_over())
        self.black_clock.set_active(self.game.turn() == chess.BLACK and not self.game.is_over())

    def _tick_clocks(self) -> None:
        if self.game.tc.unlimited:
            return
        self._update_clocks()
        for color in (chess.WHITE, chess.BLACK):
            ms = self.game.clock.poll()[color]
            if 0 < ms < 11000 and int(ms / 1000) != getattr(self, f"_last_tick_{color}", -1):
                setattr(self, f"_last_tick_{color}", int(ms / 1000))
                self.sounds.play("tick")
        self.game._check_end()

    def _update_material(self) -> None:
        board = self.game.board
        start_counts = {chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2,
                        chess.ROOK: 2, chess.QUEEN: 1}
        white_lost: List[chess.Piece] = []
        black_lost: List[chess.Piece] = []
        for color, lost in ((chess.WHITE, white_lost), (chess.BLACK, black_lost)):
            for pt, n in start_counts.items():
                have = chess.popcount(board.pieces_mask(pt, color))
                lost.extend([chess.Piece(pt, color)] * max(0, n - have))
        values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                  chess.ROOK: 5, chess.QUEEN: 9}
        balance = sum(values.get(p.piece_type, 0) for p in black_lost) - \
            sum(values.get(p.piece_type, 0) for p in white_lost)
        self.material.set_captures(black_lost, white_lost, balance)

    def takeback(self) -> None:
        record = self.game.undo()
        if record is None:
            return
        self.game.undo()          # also take back the opponent's reply
        self.refresh()
        if self.battle_widget is not None:
            self.battle_widget.sync_position(self.game.board)
        self.maybe_engine_move()

    def resign(self) -> None:
        if self.game.is_over():
            return
        loser = self.game.turn()
        self.game.result = "0-1" if loser == chess.WHITE else "1-0"
        self.game.reason = "Resignation"
        self.game.gameOver.emit(self.game.result, self.game.reason)

    def goto_ply(self, ply: int) -> None:
        self.game.goto_ply(ply)
        self.refresh()

    # ------------------------------------------------------------------
    # analysis
    # ------------------------------------------------------------------
    def toggle_analysis(self, *_args) -> None:
        self.analysis_running = not self.analysis_running
        self.analyse_action.setChecked(self.analysis_running)
        if self.analysis_running:
            self.start_analysis()
        else:
            self.engine_panel.set_status("Engine idle")

    def start_analysis(self) -> None:
        board = self.game.board
        if board.is_game_over():
            return
        player = self._analysis_player()
        if player is None:
            return
        self.engine_panel.set_status("Analysing…")
        self._attach_player_once(player)
        self._analysis_player_ref = player
        if not getattr(player, "_analysis_connected", False):
            player.finished.connect(self._on_analysis_result)
            player._analysis_connected = True
        player.think(board, Limit(movetime_ms=self.settings.get("analysis_depth_ms", 1200)),
                     multipv=self.settings.get("multipv", 3))

    def _analysis_player(self) -> Optional[Player]:
        if self.analysis_player is None:
            player: Optional[Player] = None
            for path in self.engines or find_engines():
                try:
                    candidate = UCIPlayer(path, limit_ms=1200)
                    candidate.start()
                    player = candidate
                    break
                except Exception:
                    continue      # one broken engine must not disable analysis
            self.analysis_player = player or BuiltInPlayer(
                DEFAULT_LEVELS[9], "Balanced")
        return self.analysis_player

    def _on_analysis_result(self, result) -> None:
        try:
            self._analysis_player_ref.finished.disconnect(self._on_analysis_result)
        except Exception:
            pass
        if result is None:
            return
        board = self.game.board
        lines = result.multipv or [result]
        self.engine_panel.set_lines(lines, board)
        if lines and lines[0].bestmove is not None:
            score = lines[0].score
            mate = lines[0].mate
            if board.turn == chess.BLACK:
                score = -score
                if mate:
                    mate = -mate
            self.eval_bar.set_score(score, mate)
            self.last_eval = (score, mate)
            self.record_eval(score, mate)
            if self.settings.get("show_eval", True):
                arrow = Arrow(lines[0].bestmove.from_square, lines[0].bestmove.to_square,
                              "#1f7ae0")
                self.board.set_arrows([arrow])
        self.engine_panel.set_status(
            f"depth {result.depth} · {result.nodes} nodes · {result.time_ms} ms")

    def record_eval(self, score: float, mate: Optional[int]) -> None:
        ply = len(self.game.records)
        if self.eval_history and self.eval_history[-1][0] == ply:
            self.eval_history[-1] = (ply, score, mate)
        else:
            self.eval_history.append((ply, score, mate))
        self.eval_graph.set_scores(self.eval_history)

    def show_hint(self) -> None:
        """Grade-based hint: destination square, then the piece, then the move."""
        player = BuiltInPlayer(DEFAULT_LEVELS[8], "Balanced")
        self.status_label.setText("Looking for the best move…")
        result = player.analyse_sync(self.game.board,
                                     Limit(movetime_ms=self.settings.get("analysis_depth_ms", 1200)))
        if result is None or result.bestmove is None:
            return
        move = result.bestmove
        self.hint_level = (self.hint_level + 1) % 3
        if self.hint_level == 0:
            self.board.set_markers([Marker(move.to_square, "square", "#4aa3ff")])
            self.status_label.setText("Hint: this is the square to aim at.")
        elif self.hint_level == 1:
            self.board.set_markers([Marker(move.from_square, "circle", "#f6f06a"),
                                    Marker(move.to_square, "square", "#4aa3ff")])
            self.status_label.setText("Hint: this piece, to that square.")
        else:
            self.board.set_arrows([Arrow(move.from_square, move.to_square, "#f6f06a")])
            self.status_label.setText(f"Hint: {self.game.board.san(move)} ({result.score_text})")

    def on_engine_line_clicked(self, move: chess.Move) -> None:
        if move in self.game.board.legal_moves:
            self.board.set_arrows([Arrow(move.from_square, move.to_square, "#22c55e")])
            self.board.set_markers([Marker(move.from_square, "circle", "#22c55e"),
                                    Marker(move.to_square, "circle", "#22c55e")])

    def on_square_right_click(self, square: chess.Square, _pos) -> None:
        self.board.user_markers.append(Marker(square, "circle", "#e07a1f"))
        self.board.update()

    def analyse_game(self) -> None:
        """Analyse every move of the game, add evaluations and mark mistakes.

        For each position we search the best move, then compare it with the
        move that was actually played: the difference is the centipawn loss,
        which drives the NAG annotations (?, ??, !, !!) shown in the PGN.
        """
        if not self.game.records:
            return
        evaluator = BuiltInPlayer(DEFAULT_LEVELS[9], "Balanced")
        self.progress.setVisible(True)
        self.progress.setRange(0, len(self.game.records))
        blunders = 0
        mistakes = 0
        for i, record in enumerate(self.game.records):
            before = chess.Board(record.fen_before)
            after = chess.Board(record.fen_after)
            best = evaluator.analyse_sync(before, Limit(movetime_ms=320, depth=5))
            best_score = best.score if before.turn == chess.WHITE else -best.score
            if best.mate is not None:
                best_score = 10000 if best.mate > 0 else -10000
            played = evaluator.analyse_sync(after, Limit(movetime_ms=220, depth=4))
            played_score = played.score if after.turn == chess.WHITE else -played.score
            if played.mate is not None:
                played_score = 10000 if played.mate > 0 else -10000
            loss = max(0, best_score - played_score)
            record.comment = f"{played_score / 100:+.2f} (loss {loss})"
            record.nags = []
            if loss >= 300:
                record.nags = [4]        # $4 = ??
                blunders += 1
            elif loss >= 120:
                record.nags = [2]        # $2 = ?
                mistakes += 1
            elif loss <= 10 and best_score - played_score >= -5 and best.bestmove == record.move:
                record.nags = [3]        # $3 = !!
            self.progress.setValue(i + 1)
            QApplication.processEvents()
        self.progress.setVisible(False)
        self.refresh()
        self.status_label.setText(
            f"Analysis finished: {mistakes} inaccuracies, {blunders} blunders. "
            "Comments and NAGs are stored with the moves.")

    # ------------------------------------------------------------------
    # training
    # ------------------------------------------------------------------
    def start_training(self, kind: str) -> None:
        self.stop_training(silent=True)
        set_id = None
        session = None
        db = self.db
        if kind in ("solve", "sts", "endings", "positional", "tactics", "mates"):
            kinds = {"solve": None, "sts": "sts", "endings": "endings",
                     "positional": "positional", "tactics": "tactics", "mates": "mates"}[kind]
            rows = sessions.available_sets(db)
            if kinds:
                rows = [r for r in rows if r[1] == kinds]
            dialog = TrainingPickerDialog(self, rows, "Choose a training set")
            if not dialog.exec():
                return
            set_id = dialog.selected()
            if set_id is None:
                return
            row = db.execute("SELECT kind FROM sets WHERE id=?", (set_id,)).fetchone()
            actual = row[0] if row else "tactics"
            factory = sessions.SESSION_FACTORIES.get(actual, sessions.SESSION_FACTORIES["tactics"])
            session = factory(db, set_id, self)
        else:
            factory = sessions.SESSION_FACTORIES.get(kind)
            if factory is None:
                return
            session = factory(db, None, self)
        if session is None:
            QMessageBox.warning(self, "Training", "No data available for this mode.")
            return
        session.learner = getattr(self, "learner", None)
        self.training_session = session
        self.training_kind = kind
        self.tabs.setCurrentWidget(self.training_panel)
        self.training_panel.clear_feedback()
        session.taskChanged.connect(self.on_training_task)
        self.setup_training_game(session.start_task())
        self.status_label.setText(f"Training: {session.name}")

    def setup_training_game(self, task) -> None:
        if task is None:
            self.training_panel.set_task(None)
            self.status_label.setText("Training finished")
            return
        session = self.training_session
        self.training_panel.set_task(task)
        self.training_panel.clear_feedback()
        variant = "standard"
        self.game = Game(variant=variant, fen=task.fen, tc=TimeControl(unlimited=True))
        human = HumanPlayer("You")
        engine_level = task.meta.get("level", "Club")
        opponent: Player = BuiltInPlayer(level_by_name(engine_level), "Balanced")
        user_side = task.side
        self.game.set_player(user_side, human)
        self.game.set_player(not user_side, opponent)
        self.game.positionChanged.connect(self.refresh)
        self.game.gameOver.connect(self.on_game_over)
        self.board.set_orientation(user_side)
        self.board.clear_overlays()
        self.board.blindfold = bool(task.meta.get("blindfold"))
        self.blindfold_counter = 0
        self.refresh()
        self.eval_graph.clear()
        self.engine_panel.set_lines([])
        if user_side != self.game.turn():
            self.maybe_engine_move()
        if task.kind == "squares":
            self.board.set_markers([Marker(s, "square", "#f6f06a") for s in task.meta["squares"]])
            QTimer.singleShot(2200, self._hide_training_squares)

    def _hide_training_squares(self) -> None:
        session = self.training_session
        if session is None or session.task is None:
            return
        if session.task.kind != "squares":
            return
        session.hide()
        self.board.set_markers([])
        self.training_panel.set_feedback("Now click the squares you remember.", None)

    def on_training_task(self, task) -> None:
        self.setup_training_game(task)

    def training_move(self, move: chess.Move) -> None:
        session = self.training_session
        board = self.game.board
        if move not in board.legal_moves:
            self.sounds.play("error")
            return
        if hasattr(session, "add_loss"):
            self._measure_loss(board, move)
        result = session.validate(board, move)
        self.training_panel.set_feedback(result.message or ("OK" if result.ok else ""), result.ok)
        self.training_panel.set_stats(session.points, session.solved, session.failed,
                                      session.streak)
        if not result.ok and not result.done:
            self.sounds.play("error")
            return
        record = self.game.push(move)
        if record is not None:
            self._play_move_sound(record)
            if self.battle_widget is not None:
                self.battle_widget.play_move(record)
        if session.task and session.task.meta.get("blindfold"):
            self.blindfold_counter += 1
            if self.blindfold_counter >= int(session.task.meta["blindfold"]):
                self.board.blindfold = True
                self.board.update()
        if result.done:
            self.sounds.play("win" if result.solved else "lose")
            QTimer.singleShot(900, self.training_next)
            return
        if result.reply is not None and result.reply in self.game.board.legal_moves:
            self._pending_reply = result.reply
            QTimer.singleShot(420, self._flush_reply)
        else:
            self.maybe_engine_move()

    def _flush_reply(self) -> None:
        move = self._pending_reply
        self._pending_reply = None
        if move is None or self.game.is_over():
            return
        if move in self.game.board.legal_moves:
            self._training_reply(move)

    def _measure_loss(self, board: chess.Board, move: chess.Move) -> None:
        """Centipawn loss of a played move, used by the Elo estimator."""
        session = self.training_session
        try:
            evaluator = BuiltInPlayer(DEFAULT_LEVELS[9], "Balanced")
            best = evaluator.analyse_sync(board, Limit(movetime_ms=260, depth=5))
            best_score = best.score if board.turn == chess.WHITE else -best.score
            after = board.copy()
            after.push(move)
            played = evaluator.analyse_sync(after, Limit(movetime_ms=180, depth=4))
            played_score = played.score if after.turn == chess.WHITE else -played.score
            session.add_loss(max(0, best_score - played_score))
            estimate = session.estimate() if hasattr(session, "estimate") else None
            if estimate:
                self.training_panel.set_title(f"{session.name} - about {estimate} Elo")
        except Exception:
            pass

    def _training_reply(self, move: chess.Move) -> None:
        if self.game.is_over():
            return
        self._pending_reply = None
        record = self.game.push(move)
        if record is not None:
            self._play_move_sound(record)
            if self.battle_widget is not None:
                self.battle_widget.play_move(record)

    def training_hint(self) -> None:
        session = self.training_session
        if session is None:
            return
        hint = session.hint(self.game.board)
        if hint.arrows or hint.markers:
            self.board.set_arrows(hint.arrows)
            self.board.set_markers(hint.markers)
        if hint.text:
            self.training_panel.set_feedback(hint.text, None)
        self.training_panel.set_stats(session.points, session.solved, session.failed,
                                      session.streak)

    def training_solution(self) -> None:
        session = self.training_session
        if session is None or session.task is None:
            return
        task = session.task
        if task.solution:
            san = task.meta.get("san") or " ".join(m.uci() for m in task.solution)
            self.training_panel.set_feedback(f"Solution: {san}", None)
            self.board.set_arrows([Arrow(task.solution[0].from_square,
                                         task.solution[0].to_square, "#f6f06a")])
        elif task.kind in ("openings",):
            hint = session.hint(self.game.board)
            self.board.set_arrows(hint.arrows)

    def training_retry(self) -> None:
        session = self.training_session
        if session is None or session.task is None:
            return
        task = session.task
        self.setup_training_game(task)

    def training_next(self) -> None:
        session = self.training_session
        if session is None:
            return
        task = session.start_task()
        if task is None:
            summary = session.finish()
            self.training_panel.set_feedback(
                f"Finished: {summary['points']} points, {summary['solved']} solved, "
                f"{summary['failed']} failed.", True)
            self.stop_training(silent=True)
            return
        self.setup_training_game(task)

    def training_answer_colour(self, light: bool) -> None:
        session = self.training_session
        if session is None or not hasattr(session, "answer"):
            return
        result = session.answer(light)
        self.training_panel.set_feedback(result.message, result.ok)
        self.training_panel.set_stats(session.points, session.solved, session.failed,
                                      session.streak)
        if result.done:
            QTimer.singleShot(700, self.training_next)

    def training_game_over(self, result: str, reason: str) -> None:
        session = self.training_session
        if session is None or not hasattr(session, "evaluate_result"):
            return
        ok, message = session.evaluate_result(self.game)
        self.training_panel.set_feedback(message, ok)
        self.training_panel.set_stats(session.points, session.solved, session.failed,
                                      session.streak)
        QTimer.singleShot(1200, self.training_next)

    def stop_training(self, silent: bool = False) -> None:
        if self.training_session is None:
            if not silent:
                self.training_panel.set_feedback("No training running.", None)
            return
        session = self.training_session
        self.training_session = None
        self.training_kind = None
        self.training_panel.set_task(None)
        self.board.blindfold = False
        self.board.clear_overlays()
        if not silent:
            summary = session.summary()
            self.training_panel.set_feedback(
                f"{session.name}: {summary['points']} points, {summary['solved']} solved.", True)

    # ------------------------------------------------------------------
    # battle mode
    # ------------------------------------------------------------------
    def toggle_battle(self, *_args) -> None:
        enabled = self.battle_action.isChecked()
        if enabled:
            self._ensure_battle()
            if self.battle_widget is None:
                self.battle_action.setChecked(False)
                return
            self.stack.setCurrentWidget(self.battle_widget)
            self.battle_widget.sync_position(self.game.board)
        else:
            self.stack.setCurrentWidget(self.board)
        self.status_label.setText("Battle Chess mode " + ("on" if enabled else "off"))

    def _ensure_battle(self) -> None:
        if self.battle_widget is not None:
            return
        try:
            from ..battle.battle_widget import BattleBoardWidget
        except Exception as exc:
            self._battle_error = str(exc)
            QMessageBox.warning(
                self, "Battle Chess",
                "The 3D battle board could not be started.\n\n"
                f"{exc}\n\nThe 2D board keeps all the game features.")
            return
        try:
            self.battle_widget = BattleBoardWidget(self, self.settings)
            self.battle_widget.moveRequested.connect(self.on_human_move)
            self.battle_widget.glFailed.connect(self._battle_failed)
            self.stack.addWidget(self.battle_widget)
        except Exception as exc:
            self.battle_widget = None
            QMessageBox.warning(self, "Battle Chess",
                                f"3D acceleration unavailable: {exc}")

    def _battle_failed(self, detail: str) -> None:
        """The 3D board stopped drawing: go back to the 2D board, once.

        Drawing errors used to repeat every frame, which buried the window in
        error dialogs. Report the first one and carry on in 2D.
        """
        self.battle_action.setChecked(False)
        self.stack.setCurrentWidget(self.board)
        self.status_label.setText("Battle Chess off - 3D drawing failed")
        tail = (detail or "unknown error").strip().splitlines()
        QMessageBox.warning(
            self, "Battle Chess",
            "The 3D board stopped drawing, so the game switched back to the\n"
            "flat board. Every other feature is unaffected.\n\n"
            + "\n".join(tail[-6:]))

    def set_gore(self, level: str) -> None:
        self.settings["battle_gore"] = level
        self.save_settings()
        if self.battle_widget is not None:
            self.battle_widget.apply_settings(self.settings)
        self.status_label.setText(f"Battle Chess gore: {level}")

    def set_battle_camera(self, mode: str) -> None:
        self.settings["battle_camera"] = mode
        self.save_settings()
        if self.battle_widget is not None:
            self.battle_widget.set_camera_mode(mode)

    # ------------------------------------------------------------------
    # the anarchy wing: Anarchess and Anarchchess
    # ------------------------------------------------------------------
    def show_anarchess(self) -> None:
        self._ensure_anarchess()
        if self.anarchess is None:
            return
        self.stack.setCurrentWidget(self.anarchess)
        self.status_label.setText(
            "Anarchess - lay a tile, then settle, move or fight with a pawn")

    def _ensure_anarchess(self) -> None:
        if self.anarchess is not None:
            return
        try:
            from ..anarchess.view import AnarchessView, default_config
        except Exception as exc:
            QMessageBox.warning(self, "Anarchess",
                                f"Anarchess could not be started:\n{exc}")
            return
        try:
            view = AnarchessView(self)
            view.start(default_config())
            view.statusChanged.connect(self.status_label.setText)
            self.stack.addWidget(view)
            self.anarchess = view
        except Exception as exc:
            QMessageBox.warning(self, "Anarchess",
                                f"Anarchess could not be started:\n{exc}")

    def show_anarchy_rules(self) -> None:
        from .anarchy_dialog import AnarchyRulesBrowser
        AnarchyRulesBrowser(self).exec()

    def edit_anarchy_rules(self) -> None:
        from .anarchy_dialog import AnarchyRulesDialog
        dialog = AnarchyRulesDialog(self)
        if dialog.exec() and self.game.variant in ("anarchchess", "anarchy"):
            self.new_game(interactive=False, reuse=True)

    # ------------------------------------------------------------------
    # learning coach
    # ------------------------------------------------------------------
    def show_learning(self) -> None:
        if self.learner is None:
            QMessageBox.information(self, "Learning coach",
                                    "The learning database is not available.")
            return
        from .learning_dialog import LearningDialog
        dialog = LearningDialog(self.learner, self, on_review=self.review_due,
                                on_weakest=self.train_weakest)
        dialog.exec()

    def review_due(self) -> None:
        """Train exactly the drills whose review date has arrived."""
        if self.learner is None:
            return
        plan = self.learner.plan(24)
        if not plan:
            QMessageBox.information(
                self, "Nothing due",
                "No reviews are due right now. Train a set to add material, "
                "or come back tomorrow.")
            return
        from ..training import sessions
        session = sessions.ReviewSession(self.db, plan[0][0], self, items=plan)
        if not session.rows:
            QMessageBox.information(self, "Nothing due",
                                    "The due drills are no longer in the database.")
            return
        self._start_session(session, "review")

    def train_weakest(self) -> None:
        """Open the training mode that matches the weakest theme."""
        if self.learner is None:
            return
        weak = self.learner.weakest_skills(1)
        skill = weak[0][0] if weak else "tactics"
        kind = {"mates": "mates", "endgames": "endings", "strategy": "sts",
                "openings": "openings", "calculation": "guess",
                "visualisation": "squares"}.get(skill, "tactics")
        self.start_training(kind)

    def _start_session(self, session, kind: str) -> None:
        self.stop_training(silent=True)
        session.learner = getattr(self, "learner", None)
        self.training_session = session
        self.training_kind = kind
        self.tabs.setCurrentWidget(self.training_panel)
        self.training_panel.clear_feedback()
        session.taskChanged.connect(self.on_training_task)
        self.setup_training_game(session.start_task())
        self.status_label.setText(f"Training: {session.name}")

    def set_ui_theme(self, name: str) -> None:
        from .theme import apply as apply_theme
        self.ui_theme = name
        self.settings["ui_theme"] = name
        apply_theme(name)
        self.save_settings()
        self.status_label.setText(f"Interface theme: {name}")
        self._recolor_toolbar()

    def _recolor_toolbar(self) -> None:
        icons = {"New": "new", "Train": "train", "Takeback": "undo",
                 "Hint": "hint", "Flip": "flip", "Save": "save",
                 "Analyse": "analyse", "Battle": "battle",
                 "Anarchess": "anarchess"}
        for action in self.findChildren(QAction):
            name = icons.get(action.text())
            if name:
                action.setIcon(themed_icon(name, self.ui_theme, 40))

    # ------------------------------------------------------------------
    # database / pgn
    # ------------------------------------------------------------------
    def save_game(self, silent: bool = False) -> None:
        pgn = self.game.to_pgn()
        title = f"{self.game.players[chess.WHITE].name} vs {self.game.players[chess.BLACK].name}"
        try:
            self.db.execute(
                "INSERT INTO saved_games(title, pgn, variant, created, result)"
                " VALUES(?,?,?,?,?)",
                (title, pgn, self.game.variant, int(time.time()), self.game.result or "*"))
            self.db.commit()
            if not silent:
                self.status_label.setText("Game saved to the database.")
        except Exception as exc:
            self.status_label.setText(f"Could not save: {exc}")

    def export_pgn(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export PGN", "game.pgn",
                                              "PGN files (*.pgn)")
        if not path:
            return
        with open(path, "w") as fh:
            fh.write(self.game.to_pgn() + "\n\n")
        self.status_label.setText(f"Exported to {path}")

    def import_pgn(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import PGN", "", "PGN files (*.pgn)")
        if not path:
            return
        with open(path) as fh:
            text = fh.read()
        game = chess.pgn.read_game(_io.StringIO(text))
        if game is None:
            QMessageBox.warning(self, "Import", "No game found in that file.")
            return
        self.game.load_pgn(str(game))
        self.refresh()
        self.status_label.setText(f"Imported {os.path.basename(path)}")

    def browse_games(self) -> None:
        rows = self.db.execute("SELECT id, title, created, result FROM saved_games"
                               " ORDER BY created DESC LIMIT 500").fetchall()
        self._show_game_list("Saved games", rows)

    def browse_database(self) -> None:
        rows = self.db.execute(
            "SELECT id, white || ' - ' || black || '  (' || eco || ')', 0, result"
            " FROM games LIMIT 500").fetchall()
        self._show_game_list("Master game database", rows, master=True)

    def _show_game_list(self, title: str, rows, master: bool = False) -> None:
        from PyQt6.QtWidgets import QListWidget, QVBoxLayout, QDialog, QDialogButtonBox
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(620, 460)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for row in rows:
            listing.addItem(f"{row[0]}: {row[1]}")
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open |
                                   QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if not dialog.exec():
            return
        item = listing.currentItem()
        if item is None:
            return
        game_id = int(item.text().split(":")[0])
        if master:
            row = self.db.execute("SELECT moves, fen FROM games WHERE id=?", (game_id,)).fetchone()
            if not row:
                return
            board = chess.Board(row[1] or chess.STARTING_FEN)
            sans = []
            for u in row[0].split():
                try:
                    mv = chess.Move.from_uci(u)
                except Exception:
                    break
                if mv not in board.legal_moves:
                    break
                sans.append(board.san(mv))
                board.push(mv)
            self._load_replay(sans, title)
        else:
            row = self.db.execute("SELECT pgn FROM saved_games WHERE id=?", (game_id,)).fetchone()
            if not row:
                return
            self.game.load_pgn(row[0])
            self.refresh()

    def _load_replay(self, sans: Sequence[str], title: str) -> None:
        board = chess.Board()
        moves = []
        for san in sans:
            try:
                mv = board.parse_san(san)
            except Exception:
                break
            moves.append(mv)
            board.push(mv)
        self.stop_training(silent=True)
        self.game = Game()
        self.game.set_player(chess.WHITE, HumanPlayer("White"))
        self.game.set_player(chess.BLACK, HumanPlayer("Black"))
        self.game.positionChanged.connect(self.refresh)
        self.game.gameOver.connect(self.on_game_over)
        self.refresh()
        for mv in moves:
            self.game.push(mv)
        self.refresh()
        self.status_label.setText(f"Replaying: {title} - click the move list to navigate")

    def opening_explorer(self) -> None:
        from ..data.openings import explore
        explore(self.db, self.game.board, self)

    # ------------------------------------------------------------------
    # view / engines / help
    # ------------------------------------------------------------------
    def set_theme(self, name: str) -> None:
        self.settings["board_theme"] = name
        self.board.set_theme(name)
        self.save_settings()

    def set_piece_style(self, name: str) -> None:
        self.settings["piece_style"] = name
        self.board.set_piece_style(name)
        self.save_settings()

    def toggle_coords(self) -> None:
        self.board.show_coords = self.coords_action.isChecked()
        self.settings["coords"] = self.board.show_coords
        self.board.update()
        self.save_settings()

    def toggle_legal(self) -> None:
        self.board.show_legal = self.legal_action.isChecked()
        self.settings["legal_moves"] = self.board.show_legal
        self.board.update()
        self.save_settings()

    def toggle_sound(self) -> None:
        self.sounds.set_enabled(self.sound_action.isChecked())
        self.settings["sound"] = self.sound_action.isChecked()
        self.save_settings()

    def preferences(self) -> None:
        dialog = PreferencesDialog(self, self.settings)
        if dialog.exec():
            self.settings.update(dialog.settings())
            self.save_settings()
            self._apply_settings()
            self.sounds.set_enabled(self.settings.get("sound", True))
            self.sounds.set_volume(self.settings.get("volume", 80) / 100.0)
            if self.battle_widget is not None:
                self.battle_widget.apply_settings(self.settings)

    def manage_engines(self) -> None:
        dialog = EngineManagerDialog(self, self.engines)
        if dialog.exec():
            self.engines = dialog.result_paths()
            self.settings["engines"] = self.engines
            self.save_settings()
            self.analysis_player = None

    def install_stockfish(self) -> None:
        from ..data.stockfish import install_stockfish
        install_stockfish(self)

    def set_engine_level(self, name: str) -> None:
        for color in (chess.WHITE, chess.BLACK):
            player = self.game.players[color]
            if isinstance(player, BuiltInPlayer):
                player.set_level(level_by_name(name))
                self.refresh()
                self.status_label.setText(f"Engine level: {name}")

    def set_personality(self, name: str) -> None:
        for color in (chess.WHITE, chess.BLACK):
            player = self.game.players[color]
            if isinstance(player, BuiltInPlayer):
                player.set_personality(name)
                self.status_label.setText(f"Personality: {name}")

    def show_shortcuts(self) -> None:
        QMessageBox.information(
            self, "Shortcuts",
            "Ctrl+N new game\nCtrl+Shift+N repeat last settings\nCtrl+Z takeback\n"
            "Ctrl+R resign\nCtrl+H hint\nCtrl+B battle mode\nCtrl+A analyse the game\n"
            "Ctrl+S save\nCtrl+O import PGN\nCtrl+E export PGN\nF flip board\n"
            "Esc stop training / clear marks\nRight-drag draw arrows, right-click mark squares")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.save_settings()
        for color in (chess.WHITE, chess.BLACK):
            try:
                self.game.players[color].quit()
            except Exception:
                pass
        if self.analysis_player is not None:
            try:
                self.analysis_player.quit()
            except Exception:
                pass
        for player in self._uci_cache.values():
            try:
                player.quit()
            except Exception:
                pass
        super().closeEvent(event)
