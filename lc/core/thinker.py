"""Worker threads that keep the UI responsive while engines think."""

from __future__ import annotations

from typing import Callable, Optional

import chess

from PyQt6.QtCore import QThread, pyqtSignal

from .engine import SearchResult

# Strong references: a QThread must never be destroyed while it is running,
# otherwise Qt aborts the process.  Finished threads are dropped lazily.
_LIVE_THREADS: set = set()


def reap_threads() -> None:
    """Drop threads that have finished (a running thread must be kept alive)."""
    for thread in list(_LIVE_THREADS):
        if thread.isFinished():
            _LIVE_THREADS.discard(thread)


class ThinkThread(QThread):
    """Runs a search callable in a background thread."""

    result = pyqtSignal(object)
    progress = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable, board: chess.Board, limit=None, multipv: int = 1,
                 parent=None):
        super().__init__(parent)
        self.fn = fn
        self.board = board.copy(stack=True)
        self.limit = limit
        self.multipv = multipv
        self._stop = False
        self._carrier: Optional[object] = None
        _LIVE_THREADS.add(self)
        reap_threads()

    def request_stop(self) -> None:
        self._stop = True
        carrier = self._carrier
        if carrier is not None:
            for attr in ("stop",):
                fn = getattr(carrier, attr, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
        self.wait(1500)

    def set_carrier(self, obj) -> None:
        """Attach the object that can be asked to stop (engine / uci client)."""
        self._carrier = obj

    def run(self) -> None:  # pragma: no cover - threaded
        try:
            out = self.fn(self.board, self.limit, self.multipv)
            if out is None:
                out = SearchResult()
            if not self._stop:
                self.result.emit(out)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            _LIVE_THREADS.add(self)


class AnalysisThread(QThread):
    """Continuous analysis of a position (used by the analysis panel)."""

    line = pyqtSignal(object)
    finished_line = pyqtSignal(object)

    def __init__(self, player, board: chess.Board, limit=None, multipv: int = 3, parent=None):
        super().__init__(parent)
        self.player = player
        self.board = board.copy(stack=True)
        self.limit = limit
        self.multipv = multipv
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        try:
            self.player.stop()
        except Exception:
            pass
        self.wait(4000)

    def run(self) -> None:  # pragma: no cover - threaded
        try:
            res = self.player.analyse_sync(self.board, self.limit, self.multipv)
            if not self._stop:
                self.finished_line.emit(res)
        except Exception as exc:
            self.failed_line = str(exc)
