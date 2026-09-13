"""
Opening explorer: statistics for a position taken from the imported master
game database (10,000+ real games shipped with Lucas Chess).
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import chess

from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox,
                             QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)


def _games_for_position(db: sqlite3.Connection, board: chess.Board,
                        limit: int = 4000) -> List[Tuple[str, str, str, int, int]]:
    """Return (next_move_uci, result, eco, white_elo, black_elo) continuations."""
    prefix = " ".join(m.uci() for m in board.move_stack)
    rows = db.execute(
        "SELECT moves, result, eco, white_elo, black_elo FROM games"
        " WHERE moves LIKE ? LIMIT ?", (prefix + "%", limit)).fetchall()
    out: List[Tuple[str, str, str, int, int]] = []
    needed = len(prefix.split()) if prefix else 0
    for moves, result, eco, w, b in rows:
        parts = moves.split()
        if len(parts) <= needed:
            continue
        out.append((parts[needed], result or "", eco or "", w or 0, b or 0))
    return out


def stats_for(db: sqlite3.Connection, board: chess.Board) -> List[Dict]:
    data = _games_for_position(db, board)
    grouped: Dict[str, Dict] = {}
    for uci, result, eco, w, b in data:
        entry = grouped.setdefault(uci, {"games": 0, "w": 0, "d": 0, "b": 0,
                                         "elo": 0, "eco": eco})
        entry["games"] += 1
        if result == "1-0":
            entry["w"] += 1
        elif result == "0-1":
            entry["b"] += 1
        else:
            entry["d"] += 1
        entry["elo"] += (w + b) // 2 if (w or b) else 0
    total = sum(e["games"] for e in grouped.values()) or 1
    rows = []
    for uci, entry in grouped.items():
        try:
            move = chess.Move.from_uci(uci)
            san = board.san(move) if move in board.legal_moves else uci
        except Exception:
            san = uci
        rows.append({
            "uci": uci, "san": san, "games": entry["games"],
            "pct": entry["games"] / total * 100,
            "score": (entry["w"] + entry["d"] * 0.5) / max(1, entry["games"]) * 100,
            "elo": entry["elo"] // max(1, entry["games"]),
            "eco": entry["eco"],
        })
    rows.sort(key=lambda r: -r["games"])
    return rows


class OpeningExplorerDialog(QDialog):
    def __init__(self, db, board: chess.Board, parent=None, on_move=None):
        super().__init__(parent)
        self.setWindowTitle(f"Opening explorer - {board.fen()[:40]}…")
        self.resize(560, 420)
        self.on_move = on_move
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Position after {len(board.move_stack)} moves · "
                                f"{len(_games_for_position(db, board, 100000))} games"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Move", "Games", "%", "Score", "Avg Elo", "ECO"])
        self.tree.setAlternatingRowColors(True)
        self.tree.itemDoubleClicked.connect(self._play)
        for row in stats_for(db, board)[:40]:
            item = QTreeWidgetItem([row["san"], str(row["games"]), f"{row['pct']:.1f}",
                                    f"{row['score']:.0f}%", str(row["elo"] or ""),
                                    row["eco"]])
            item.setData(0, 1, row["uci"])       # Qt.UserRole == 1
            self.tree.addTopLevelItem(item)
        layout.addWidget(self.tree)
        row_widget = QHBoxLayout()
        play = QPushButton("Play this move")
        play.clicked.connect(lambda: self._play(self.tree.currentItem(), 0))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row_widget.addStretch(1)
        row_widget.addWidget(play)
        row_widget.addWidget(close)
        layout.addLayout(row_widget)

    def _play(self, item, column) -> None:
        if item is None or self.on_move is None:
            return
        uci = item.data(0, 1)
        if not uci:
            return
        try:
            move = chess.Move.from_uci(uci)
        except Exception:
            return
        self.on_move(move)
        self.accept()


def explore(db, board: chess.Board, parent=None, on_move=None) -> None:
    if not board.move_stack:
        QMessageBox.information(parent, "Opening explorer",
                                "Play a few moves first (or load a game) to explore "
                                "opening statistics for a position.")
        return
    OpeningExplorerDialog(db, board, parent, on_move).exec()
