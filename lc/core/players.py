"""
Players: humans and engines behind one small interface.

    Player
      ├─ HumanPlayer
      ├─ BuiltInPlayer   (LCEngine, with level / personality)
      └─ UCIPlayer       (Stockfish & friends, with UCI options)

Players are driven asynchronously: `think()` returns immediately and the
`finished` signal (a Qt signal, because the UI is Qt) carries a SearchResult.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

import chess

from PyQt6.QtCore import QObject, pyqtSignal

from .engine import DEFAULT_LEVELS, Level, LCEngine, SearchResult, level_by_name
from .thinker import ThinkThread
from .uci import UCIEngine, EngineInfo


class Player(QObject):
    """Base class.  Subclasses implement `_search(board, limit)`."""

    finished = pyqtSignal(object)      # SearchResult
    info = pyqtSignal(object)          # SearchResult (partial)
    failed = pyqtSignal(str)

    def __init__(self, name: str = "Player", human: bool = False):
        super().__init__()
        self.name = name
        self.human = human
        self._thread: Optional[ThinkThread] = None
        # Every asynchronous search owns a generation. A cancelled worker can
        # still post a queued Qt signal, but it must never play into a new game.
        self._think_token = 0
        self._retired_threads = []

    # -- identification ---------------------------------------------------
    def describe(self) -> str:
        return self.name

    def is_engine(self) -> bool:
        return not self.human

    # -- async ------------------------------------------------------------
    def think(self, board: chess.Board, limit=None, multipv: int = 1) -> None:
        self.stop()
        token = self._think_token
        thread = ThinkThread(self._search, board, limit, multipv)
        self._thread = thread
        thread.result.connect(lambda result, t=token: self._on_result(t, result))
        thread.progress.connect(lambda result, t=token: self._on_progress(t, result))
        thread.failed.connect(lambda message, t=token: self._on_failed(t, message))
        thread.finished.connect(lambda th=thread: self._retire_thread(th))
        thread.start()

    def _on_result(self, token: int, res: SearchResult) -> None:
        if token != self._think_token:
            return
        self._thread = None
        self.finished.emit(res)

    def _on_progress(self, token: int, res: SearchResult) -> None:
        if token == self._think_token:
            self.info.emit(res)

    def _on_failed(self, token: int, message: str) -> None:
        if token == self._think_token:
            self._thread = None
            self.failed.emit(message)

    def _retire_thread(self, thread: ThinkThread) -> None:
        """Release an interrupted worker only after Qt confirms it stopped."""
        try:
            self._retired_threads.remove(thread)
        except ValueError:
            pass
        # ThinkThread keeps its own finished-object registry until the next
        # worker reaps it. Do not call deleteLater here: that would leave the
        # registry holding an invalid PyQt wrapper.

    def stop(self) -> None:
        self._think_token += 1
        thread = self._thread
        self._thread = None
        if thread is not None:
            # Keep a Python reference until QThread has actually stopped;
            # otherwise replacing it for the next move can destroy a running
            # thread. Its callbacks are already invalidated by the token.
            self._retired_threads.append(thread)
            try:
                thread.request_stop()
            except Exception:
                pass

    def thinking(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def quit(self) -> None:
        self.stop()

    # -- to implement -----------------------------------------------------
    def _search(self, board: chess.Board, limit, multipv: int) -> SearchResult:
        raise NotImplementedError

    def analyse_sync(self, board: chess.Board, limit=None, multipv: int = 1) -> SearchResult:
        """Blocking search, used by analysis and training validation."""
        return self._search(board, limit, multipv)


class HumanPlayer(Player):
    def __init__(self, name: str = "You"):
        super().__init__(name, human=True)

    def _search(self, board, limit, multipv=1) -> SearchResult:
        return SearchResult()


class BuiltInPlayer(Player):
    """The built-in LCEngine with an Elo-ish level and personality."""

    PERSONALITIES = {
        "Balanced":    dict(aggression=1.0, positional=1.0),
        "Aggressive":  dict(aggression=1.45, positional=0.85),
        "Defensive":   dict(aggression=0.60, positional=1.10),
        "Positional":  dict(aggression=0.90, positional=1.40),
        "Tactical":    dict(aggression=1.25, positional=0.75),
        "Solid":       dict(aggression=0.80, positional=1.20),
        "Wild":        dict(aggression=1.60, positional=0.60),
    }

    def __init__(self, level: Optional[Level] = None, personality: str = "Balanced",
                 name: Optional[str] = None):
        self.level = level or DEFAULT_LEVELS[6]
        self.personality = personality
        self.apply_personality()
        super().__init__(name or f"Lucas {self.level.name}", human=False)
        self.engine = LCEngine(self.level)

    def apply_personality(self) -> None:
        traits = self.PERSONALITIES.get(self.personality, self.PERSONALITIES["Balanced"])
        self.level.aggression = traits["aggression"]
        self.level.positional = traits["positional"]

    def set_level(self, level: Level) -> None:
        self.level = level
        self.apply_personality()
        self.engine.set_level(self.level)
        self.name = f"Lucas {level.name}"

    def set_personality(self, personality: str) -> None:
        self.personality = personality
        self.apply_personality()

    def describe(self) -> str:
        return f"{self.name} ({self.level.elo} Elo, {self.personality})"

    def _search(self, board, limit, multipv=1) -> SearchResult:
        from .uci import Limit as ULimit
        limit = limit or ULimit(movetime_ms=self.level.movetime_ms,
                                depth=self.level.max_depth)
        mt = getattr(limit, "movetime_ms", None) or self.level.movetime_ms
        depth = getattr(limit, "depth", None) or self.level.max_depth
        self.engine = LCEngine(self.level)
        return self.engine.search(board, movetime_ms=mt, max_depth=depth)

    def stop(self) -> None:
        super().stop()
        try:
            self.engine.stop()
        except Exception:
            pass


class UCIPlayer(Player):
    """Any external UCI engine (Stockfish by default)."""

    def __init__(self, path: str, options: Optional[Dict] = None, name: Optional[str] = None,
                 limit_ms: int = 1000, limit_depth: int = 0, skill: Optional[int] = None,
                 elo: Optional[int] = None):
        super().__init__(name or os.path.basename(path), human=False)
        self.path = path
        self.options = dict(options or {})
        self.limit_ms = limit_ms
        self.limit_depth = limit_depth
        self.skill = skill
        self.elo = elo
        self.engine = UCIEngine(path, self.options, name=self.name)
        self.info_engine: Optional[EngineInfo] = None

    def start(self) -> EngineInfo:
        if self.info_engine is None:
            self.info_engine = self.engine.start()
            self.name = self.info_engine.name
            self.apply_strength()
        return self.info_engine

    def apply_strength(self) -> None:
        if not self.engine._started:
            return
        opts = self.engine.info.options
        if self.elo and "UCI_Elo" in opts:
            self.engine.set_option("UCI_LimitStrength", True)
            self.engine.set_option("UCI_Elo", max(int(opts["UCI_Elo"].get("min", 1320)),
                                                  min(int(opts["UCI_Elo"].get("max", 3190)), self.elo)))
        elif self.skill is not None and "Skill Level" in opts:
            self.engine.set_option("UCI_LimitStrength", False)
            self.engine.set_option("Skill Level", self.skill)

    def describe(self) -> str:
        extra = []
        if self.elo:
            extra.append(f"{self.elo} Elo")
        elif self.skill is not None:
            extra.append(f"skill {self.skill}")
        if self.limit_ms:
            extra.append(f"{self.limit_ms} ms")
        return f"{self.name}" + (f" ({', '.join(extra)})" if extra else "")

    def _search(self, board, limit, multipv=1) -> SearchResult:
        self.start()
        from .uci import Limit as ULimit
        if limit is None:
            limit = ULimit(movetime_ms=self.limit_ms,
                           depth=self.limit_depth or None)
        return self.engine.analyse(board, limit, multipv=multipv,
                                   on_info=self._thread_guard if False else None)

    def _thread_guard(self, res):  # pragma: no cover - placeholder
        pass

    def stop(self) -> None:
        super().stop()
        try:
            self.engine.stop()
        except Exception:
            pass

    def quit(self) -> None:
        self.stop()
        try:
            self.engine.quit()
        except Exception:
            pass


def built_in_levels():
    return list(DEFAULT_LEVELS)


def make_builtin(level_name: str, personality: str = "Balanced") -> BuiltInPlayer:
    return BuiltInPlayer(level_by_name(level_name), personality)
