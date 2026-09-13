"""
UCI engine driver: talks to Stockfish (or any UCI / USI style engine).

The engine runs in its own process; callers normally use this from a worker
thread (see lc.core.thinker).  It supports:

  * go depth / movetime / nodes / infinite + stop
  * multipv analysis
  * UCI options (Skill Level, UCI_Elo, UCI_LimitStrength, Threads, Hash, ...)
  * chess960 and, when the engine understands it, UCI_Chess960
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import chess

from .engine import MATE, SearchResult


@dataclass
class EngineInfo:
    name: str = "Unknown"
    author: str = ""
    path: str = ""
    options: Dict[str, dict] = field(default_factory=dict)
    variant_ok: bool = True
    error: str = ""


@dataclass
class Limit:
    depth: Optional[int] = None
    movetime_ms: Optional[int] = None
    nodes: Optional[int] = None
    mate: Optional[int] = None
    infinite: bool = False
    wtime_ms: Optional[int] = None
    btime_ms: Optional[int] = None
    winc_ms: Optional[int] = None
    binc_ms: Optional[int] = None
    movestogo: Optional[int] = None


class UCIEngine:
    """A thin, robust UCI client."""

    def __init__(self, path: str, options: Optional[Dict[str, object]] = None,
                 name: Optional[str] = None):
        self.path = path
        self.options = dict(options or {})
        self.name = name or os.path.basename(path)
        self.proc: Optional[subprocess.Popen] = None
        self.info = EngineInfo(name=self.name, path=path)
        self._lock = threading.Lock()
        self._started = False
        self._stop_sent = False
        self._searching = False

    # -- lifecycle --------------------------------------------------------
    def start(self, timeout: float = 8.0) -> EngineInfo:
        if self._started:
            return self.info
        if not os.path.exists(self.path):
            self.info.error = f"engine not found: {self.path}"
            raise FileNotFoundError(self.info.error)
        argv = [self.path]
        if not os.access(self.path, os.X_OK) and self.path.endswith(".py"):
            # a python script without the executable bit set
            argv = [sys.executable, self.path]
        try:
            self.proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
        except Exception as exc:  # pragma: no cover
            self.info.error = f"cannot launch: {exc}"
            raise
        self._started = True
        self._send("uci")
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self._readline(timeout=max(0.2, deadline - time.time()))
            if line is None:
                break
            if line == "uciok":
                break
            self._parse_info_line(line)
        self.is_ready()
        for key, value in self.options.items():
            self.set_option(key, value)
        return self.info

    def is_ready(self, timeout: float = 8.0) -> bool:
        self._send("isready")
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self._readline(timeout=max(0.2, deadline - time.time()))
            if line is None:
                return False
            if line.strip() == "readyok":
                return True
        return False

    def new_game(self) -> None:
        if not self._started:
            return
        try:
            self._send("ucinewgame")
            self.is_ready()
        except Exception:
            pass

    def quit(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self._send("quit")
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None
        self._started = False

    def __del__(self):  # pragma: no cover
        try:
            self.quit()
        except Exception:
            pass

    # -- options ----------------------------------------------------------
    def set_option(self, name: str, value) -> None:
        if not self._started:
            return
        if name in self.info.options:
            spec = self.info.options[name]
            kind = spec.get("type", "string")
            if kind == "check":
                value = "true" if value in (True, 1, "1", "true", "True") else "false"
            elif kind == "spin":
                try:
                    value = int(value)
                except Exception:
                    return
                lo = int(spec.get("min", -10 ** 9))
                hi = int(spec.get("max", 10 ** 9))
                value = max(lo, min(hi, value))
            else:
                value = str(value)
        self._send(f"setoption name {name} value {value}")

    def _parse_info_line(self, line: str) -> None:
        if line.startswith("id name "):
            self.info.name = line[len("id name "):].strip()
        elif line.startswith("id author "):
            self.info.author = line[len("id author "):].strip()
        elif line.startswith("option "):
            body = line[len("option "):]
            m = re.match(r"name\s+(.*?)\s+type\s+(\w+)", body)
            if m:
                spec = {"type": m.group(2)}
                for extra in ("min", "max", "default"):
                    mm = re.search(rf"\b{extra}\s+(\S+)", body)
                    if mm:
                        spec[extra] = mm.group(1)
                # combos
                vv = re.search(r"var\s+(.*)$", body)
                if vv:
                    spec["vars"] = vv.group(1).split()
                self.info.options[m.group(1)] = spec

    # -- io ---------------------------------------------------------------
    def _send(self, cmd: str) -> None:
        if not self.proc or self.proc.stdin is None:
            raise RuntimeError("engine not running")
        try:
            self.proc.stdin.write(cmd + "\n")
            self.proc.stdin.flush()
        except Exception:
            raise RuntimeError("engine pipe broken")

    def _readline(self, timeout: Optional[float] = None) -> Optional[str]:
        if not self.proc or self.proc.stdout is None:
            return None
        if timeout is None:
            line = self.proc.stdout.readline()
            return None if not line else line.rstrip("\n")
        # portable timeout read
        result: List[Optional[str]] = [None]

        def target():
            try:
                result[0] = self.proc.stdout.readline()
            except Exception:
                result[0] = None

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout)
        if result[0] is None or t.is_alive():
            return None
        return result[0].rstrip("\n")

    # -- search -----------------------------------------------------------
    def analyse(self, board: chess.Board, limit: Limit,
                multipv: int = 1, root_moves=None,
                on_info=None) -> SearchResult:
        if not self._started:
            self.start()
        self._stop_sent = False
        moves = self._position_cmd(board)
        self._send(moves)
        if multipv > 1:
            self.set_option("MultiPV", multipv)
        else:
            try:
                self.set_option("MultiPV", 1)
            except Exception:
                pass
        self._send("go " + self._limit_cmd(limit))
        self._searching = True

        best: Dict[int, SearchResult] = {}
        last_line: Optional[SearchResult] = None
        started = time.time()
        hard_deadline = None
        if not limit.infinite and limit.movetime_ms:
            hard_deadline = started + limit.movetime_ms / 1000.0 + 3.0
        elif not limit.infinite and limit.depth:
            hard_deadline = started + 120.0

        while True:
            if hard_deadline and time.time() > hard_deadline:
                try:
                    self._send("stop")
                except Exception:
                    pass
            line = self._readline(timeout=0.05)
            if line is None:
                if self.proc is None or self.proc.poll() is not None:
                    break
                continue
            if line.startswith("info "):
                res = self._parse_uci_info(line, board)
                if res is None:
                    continue
                idx = res[0]
                sr = res[1]
                best[idx] = sr
                last_line = sr
                if on_info:
                    try:
                        on_info(sr)
                    except Exception:
                        pass
            elif line.startswith("bestmove"):
                self._searching = False
                parts = line.split()
                mv = None
                ponder = None
                if len(parts) >= 2 and parts[1] not in ("(none)", "0000", None):
                    try:
                        mv = chess.Move.from_uci(parts[1])
                    except Exception:
                        mv = None
                if len(parts) >= 4 and parts[2] == "ponder":
                    try:
                        ponder = chess.Move.from_uci(parts[3])
                    except Exception:
                        ponder = None
                if mv is not None and mv in best:
                    out = best[1] if mv == best.get(1).bestmove else None
                    for sr in best.values():
                        if sr.bestmove == mv:
                            out = sr
                            break
                    if out is None:
                        out = SearchResult(bestmove=mv, ponder=ponder)
                elif last_line is not None:
                    out = last_line
                    out.bestmove = mv or out.bestmove
                    out.ponder = ponder or out.ponder
                else:
                    out = SearchResult(bestmove=mv, ponder=ponder)
                out.time_ms = int((time.time() - started) * 1000)
                if multipv > 1:
                    out.multipv = [best[i] for i in sorted(best)]
                return out
        out = last_line or SearchResult()
        out.time_ms = int((time.time() - started) * 1000)
        if multipv > 1:
            out.multipv = [best[i] for i in sorted(best)]
        return out

    def stop(self) -> None:
        """Ask the engine to stop - real engines ignore `stop` when idle."""
        if self._started and self._searching and not self._stop_sent:
            try:
                self._send("stop")
                self._stop_sent = True
            except Exception:
                pass

    @staticmethod
    def _position_cmd(board: chess.Board) -> str:
        """`position fen <start> moves <...>` - the start FEN is the root of
        the move stack, otherwise the moves would be applied twice."""
        try:
            fen = board.root().fen()
        except Exception:
            try:
                probe = board.copy(stack=True)
                while probe.move_stack:
                    probe.pop()
                fen = probe.fen()
            except Exception:
                fen = board.fen()
        moves = [mv.uci() for mv in board.move_stack]
        cmd = f"position fen {fen}"
        if moves:
            cmd += " moves " + " ".join(moves)
        return cmd

    @staticmethod
    def _limit_cmd(limit: Limit) -> str:
        parts: List[str] = []
        if limit.infinite:
            parts.append("infinite")
        if limit.depth:
            parts.append(f"depth {int(limit.depth)}")
        if limit.movetime_ms:
            parts.append(f"movetime {int(limit.movetime_ms)}")
        if limit.nodes:
            parts.append(f"nodes {int(limit.nodes)}")
        if limit.mate:
            parts.append(f"mate {int(limit.mate)}")
        if limit.wtime_ms is not None:
            parts.append(f"wtime {int(limit.wtime_ms)}")
        if limit.btime_ms is not None:
            parts.append(f"btime {int(limit.btime_ms)}")
        if limit.winc_ms is not None:
            parts.append(f"winc {int(limit.winc_ms)}")
        if limit.binc_ms is not None:
            parts.append(f"binc {int(limit.binc_ms)}")
        if limit.movestogo:
            parts.append(f"movestogo {int(limit.movestogo)}")
        if not parts:
            parts.append("movetime 1000")
        return " ".join(parts)

    @staticmethod
    def _parse_uci_info(line: str, board: chess.Board):
        """Return (multipv_index, SearchResult) or None."""
        tokens = line.split()
        if len(tokens) < 2:
            return None
        res = SearchResult()
        idx = 1
        pv_uci: List[str] = []
        i = 1
        while i < len(tokens):
            t = tokens[i]
            if t == "depth" and i + 1 < len(tokens):
                res.depth = int(tokens[i + 1]); i += 2
            elif t == "nodes" and i + 1 < len(tokens):
                res.nodes = int(tokens[i + 1]); i += 2
            elif t == "nps" and i + 1 < len(tokens):
                i += 2
            elif t == "time" and i + 1 < len(tokens):
                res.time_ms = int(tokens[i + 1]); i += 2
            elif t == "multipv" and i + 1 < len(tokens):
                idx = int(tokens[i + 1]); i += 2
            elif t == "score" and i + 2 < len(tokens):
                kind = tokens[i + 1]
                if kind == "cp":
                    res.score = int(tokens[i + 2])
                    res.mate = None
                elif kind == "mate":
                    res.mate = int(tokens[i + 2])
                    res.score = (MATE - abs(res.mate) * 2) * (1 if res.mate > 0 else -1)
                i += 3
            elif t == "pv":
                pv_uci = tokens[i + 1:]
                break
            else:
                i += 1
        if not pv_uci:
            return None
        tmp = board.copy(stack=False)
        pv: List[chess.Move] = []
        for u in pv_uci:
            try:
                mv = chess.Move.from_uci(u)
            except Exception:
                break
            if mv not in tmp.legal_moves:
                break
            pv.append(mv)
            tmp.push(mv)
        if not pv:
            return None
        res.pv = pv
        res.bestmove = pv[0]
        res.ponder = pv[1] if len(pv) > 1 else None
        return idx, res


# --------------------------------------------------------------------------
# engine discovery / stockfish helper
# --------------------------------------------------------------------------

ENGINE_NAMES = ("stockfish", "stockfish_15_x64_avx2", "stockfish_16_x64_avx2",
                "stockfish-ubuntu-x86-64-avx2", "sf", "lc0", "komodo",
                "brainfish", "asmfish", "ethereal", "demolito")


def find_engines(extra_dirs: Optional[List[str]] = None) -> List[str]:
    """Look for UCI binaries in PATH and in the usual project folders."""
    found: List[str] = []
    dirs = list(extra_dirs or [])
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dirs.append(os.path.join(here, "engines"))
    dirs.append(os.path.join(here, "Engines", "Linux64"))
    for d in dirs:
        if os.path.isdir(d):
            for entry in sorted(os.listdir(d)):
                full = os.path.join(d, entry)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    found.append(full)
    for name in ENGINE_NAMES:
        p = shutil.which(name)
        if p and p not in found:
            found.append(p)
    # de-duplicate
    out, seen = [], set()
    for p in found:
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out
