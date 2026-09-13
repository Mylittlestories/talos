"""
Side panels: clocks, evaluation bar, engine lines, move list, eval graph,
captured material.  All of them are plain Qt widgets fed by the controller.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import chess

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout,
                             QHeaderView, QLabel, QProgressBar, QSizePolicy,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .pieces import PiecePainter


# --------------------------------------------------------------------------
# clocks
# --------------------------------------------------------------------------

class ClockWidget(QFrame):
    """A digital clock with a thin progress bar for the remaining time."""

    clicked = pyqtSignal()

    def __init__(self, name: str = "White", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.name = name
        self.active = False
        self.remaining_ms = 0
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(6, 4, 6, 4)
        self.layout.setSpacing(1)
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet("font-weight: 600;")
        self.time_label = QLabel("--:--")
        font = QFont("Monospace")
        font.setPixelSize(22)
        self.time_label.setFont(font)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setMaximum(1000)
        self.layout.addWidget(self.name_label)
        self.layout.addWidget(self.time_label)
        self.layout.addWidget(self.bar)

    def set_name(self, name: str) -> None:
        self.name = name
        self.name_label.setText(name)

    def set_time(self, ms: Optional[int], total_ms: int = 0) -> None:
        from ..core.game import format_clock
        if ms is None:
            self.time_label.setText("--:--")
            self.bar.setValue(0)
            return
        self.remaining_ms = ms
        self.time_label.setText(format_clock(ms))
        if total_ms > 0:
            self.bar.setValue(int(max(0, min(1000, ms / total_ms * 1000))))
        if ms < 15000:
            self.time_label.setStyleSheet("color: #e5484d; font-weight: 700;")
        else:
            self.time_label.setStyleSheet("")

    def set_active(self, active: bool) -> None:
        self.active = active
        self.setStyleSheet(
            "ClockWidget { border: 2px solid %s; border-radius: 6px; }"
            % ("#4aa3ff" if active else "transparent"))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)


# --------------------------------------------------------------------------
# evaluation bar
# --------------------------------------------------------------------------

class EvalBar(QWidget):
    """Vertical evaluation bar: white on top, black at the bottom."""

    def __init__(self, parent=None, width: int = 26):
        super().__init__(parent)
        self.score = 0.0
        self.mate: Optional[int] = None
        self.setFixedWidth(width)
        self.setMinimumHeight(120)
        self._display = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._animate)
        self._timer.start()

    def set_score(self, score: float, mate: Optional[int] = None) -> None:
        self.score = score
        self.mate = mate
        self.update()

    def _animate(self) -> None:
        target = self.score
        if abs(target - self._display) < 1.0:
            if self._display != target:
                self._display = target
                self.update()
            return
        self._display += (target - self._display) * 0.25
        self.update()

    @staticmethod
    def _to_ratio(score: float) -> float:
        """Centipawns -> 0..1 (1 = completely winning for white)."""
        return 1.0 / (1.0 + math.exp(-score / 320.0))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            w, h = self.width(), self.height()
            painter.fillRect(self.rect(), QColor("#2b2f38"))
            ratio = 1.0 if self.mate else self._to_ratio(self._display)
            white_h = int(h * ratio)
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0, QColor("#f5f1e8"))
            grad.setColorAt(1, QColor("#20242c"))
            painter.fillRect(0, 0, w, h, QBrush(grad))
            painter.fillRect(0, h - white_h, w, white_h, QColor(255, 255, 255, 45))
            painter.setPen(QPen(QColor("#7dd3fc"), 2))
            painter.drawLine(0, h - white_h, w, h - white_h)
            painter.setPen(QPen(QColor("#111827"), 1))
            painter.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
            if self.mate:
                painter.setPen(QColor("#fde047"))
                painter.setFont(QFont("Sans", 9, QFont.Weight.Bold))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"#{self.mate}")
        finally:
            painter.end()


# --------------------------------------------------------------------------
# engine lines
# --------------------------------------------------------------------------

class EngineLines(QWidget):
    """MultiPV output: clickable candidate moves with score and depth."""

    moveClicked = pyqtSignal(object)

    def __init__(self, parent=None, lines: int = 3):
        super().__init__(parent)
        self.lines = lines
        self.rows: List[Tuple[str, str, object]] = []
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self.labels: List[QLabel] = []
        for _ in range(lines):
            lab = QLabel("–")
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            lab.setStyleSheet(
                "QLabel { padding: 3px 6px; background: #262b33; border-radius: 4px; }"
                "QLabel:hover { background: #313842; }")
            lab.setCursor(Qt.CursorShape.PointingHandCursor)
            lab.mousePressEvent = self._make_click(lab)
            self.labels.append(lab)
            self.layout.addWidget(lab)
        self.layout.addStretch(1)

    def _make_click(self, lab: QLabel):
        def handler(event):
            for score, text, move in self.rows:
                if lab.text().endswith(text) or lab.toolTip() == text:
                    if move is not None:
                        self.moveClicked.emit(move)
                    break
        return handler

    def set_lines(self, results: Sequence[object], board: Optional[chess.Board] = None) -> None:
        self.rows = []
        for i, lab in enumerate(self.labels):
            if i >= len(results):
                lab.setText("")
                lab.setToolTip("")
                continue
            res = results[i]
            try:
                tmp = board.copy() if board is not None else None
                pv: List[str] = []
                first_move = None
                for j, mv in enumerate(res.pv):
                    if tmp is not None:
                        if mv not in tmp.legal_moves:
                            break
                        pv.append(tmp.san(mv))
                        tmp.push(mv)
                        if j == 0:
                            first_move = mv
                    else:
                        pv.append(mv.uci())
                text = " ".join(pv[:8])
            except Exception:
                text = " ".join(m.uci() for m in res.pv[:8])
                first_move = res.bestmove
            score = f"#{res.mate}" if res.mate else f"{res.score / 100:+.2f}"
            lab.setText(f"{score}  {text}")
            lab.setToolTip(text)
            self.rows.append((score, text, first_move or res.bestmove))
        self.update()


class EngineInfoPanel(QWidget):
    """Depth / nodes / speed plus the MultiPV list."""

    moveClicked = pyqtSignal(object)

    def __init__(self, parent=None, lines: int = 3):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.status = QLabel("Engine idle")
        self.status.setStyleSheet("color: #9ca3af; font-size: 11px;")
        self.lines_widget = EngineLines(lines=lines)
        self.lines_widget.moveClicked.connect(self.moveClicked)
        self.layout.addWidget(self.status)
        self.layout.addWidget(self.lines_widget)
        self.layout.addStretch(1)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_lines(self, results, board=None) -> None:
        self.lines_widget.set_lines(results, board)


# --------------------------------------------------------------------------
# captured material
# --------------------------------------------------------------------------

class MaterialWidget(QWidget):
    """Shows captured pieces and the current material balance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(46)
        self.white: List[chess.Piece] = []
        self.black: List[chess.Piece] = []
        self.balance = 0

    def set_captures(self, white: List[chess.Piece], black: List[chess.Piece],
                     balance: int = 0) -> None:
        self.white = list(white)
        self.black = list(black)
        self.balance = balance
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            w, h = self.width(), self.height()
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            size = min(20, int(h * 0.5))
            x = 6
            for piece in sorted(self.white, key=lambda p: -_value(p)):
                painter.drawPixmap(x, 4, PiecePainter.pixmap(piece, size))
                x += size - 6
            x = 6
            for piece in sorted(self.black, key=lambda p: -_value(p)):
                painter.drawPixmap(x, h - size - 4, PiecePainter.pixmap(piece, size))
                x += size - 6
            if self.balance:
                painter.setPen(QColor("#e5e7eb"))
                painter.setFont(QFont("Sans", 10))
                text = f"+{abs(self.balance)}" if self.balance > 0 else f"-{abs(self.balance)}"
                painter.drawText(w - 52, h // 2 + 4, text)
        finally:
            painter.end()


def _value(piece: chess.Piece) -> int:
    return {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
            chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}.get(piece.piece_type, 0)


# --------------------------------------------------------------------------
# move list
# --------------------------------------------------------------------------

class PocketStrip(QWidget):
    """Crazyhouse: the pieces you hold in hand, click one to drop it."""

    pieceClicked = pyqtSignal(int)

    def __init__(self, parent=None, color: chess.Color = chess.WHITE):
        super().__init__(parent)
        self.color = color
        self.counts: Dict[int, int] = {}
        self.selected: Optional[int] = None
        self.setFixedHeight(40)
        self.order = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]

    def set_counts(self, counts: Dict[int, int]) -> None:
        self.counts = dict(counts)
        if self.selected is not None and not self.counts.get(self.selected):
            self.selected = None
        self.update()

    def set_selected(self, piece_type: Optional[int]) -> None:
        self.selected = piece_type
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        x = event.position().x() if hasattr(event, "position") else event.x()
        index = int(x // 42)
        shown = [pt for pt in self.order if self.counts.get(pt)]
        if 0 <= index < len(shown):
            pt = shown[index]
            self.selected = None if self.selected == pt else pt
            self.pieceClicked.emit(self.selected or 0)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            shown = [pt for pt in self.order if self.counts.get(pt)]
            if not shown:
                painter.setPen(QColor("#6b7280"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "empty pocket")
                return
            for i, pt in enumerate(shown):
                rect = QRectF(i * 42, 2, 40, 36)
                if self.selected == pt:
                    painter.setBrush(QColor("#4aa3ff"))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRoundedRect(rect, 5, 5)
                painter.drawPixmap(int(rect.x()) + 2, int(rect.y()) + 2,
                                   PiecePainter.pixmap(chess.Piece(pt, self.color), 32))
                count = self.counts[pt]
                painter.setPen(QColor("#e5e7eb"))
                painter.setFont(QFont("Sans", 9, QFont.Weight.Bold))
                painter.drawText(QRectF(rect.x() + 20, rect.y() + 20, 18, 14),
                                 Qt.AlignmentFlag.AlignRight, f"\u00d7{count}")
        finally:
            painter.end()


class MoveListWidget(QTableWidget):
    """Two-column move list; clicking a ply navigates to that position."""

    plyClicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["White", "Black"])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setStyleSheet("QTableWidget::item { padding: 2px 6px; }")
        self.cellClicked.connect(lambda r, c: self._on_cell(r, c))
        self.nav_target: Optional[int] = None

    def _on_cell(self, row: int, col: int) -> None:
        ply = row * 2 + col
        self.plyClicked.emit(ply)

    def set_moves(self, sans: Sequence[str], comments: Optional[Dict[int, str]] = None) -> None:
        comments = comments or {}
        rows = (len(sans) + 1) // 2
        self.setRowCount(rows)
        self.setVerticalHeaderLabels([f"{i + 1}." for i in range(rows)])
        self.verticalHeader().setVisible(True)
        for i, san in enumerate(sans):
            row, col = divmod(i, 2)
            item = QTableWidgetItem(("" if col == 0 else " ") + san)
            cmt = comments.get(i)
            if cmt:
                item.setToolTip(cmt)
                item.setBackground(QColor("#3b4252"))
            self.setItem(row, col, item)
        self.scrollToBottom()

    def highlight_ply(self, ply: int) -> None:
        self.clearSelection()
        if ply < 0:
            return
        row, col = divmod(ply, 2)
        if row < self.rowCount():
            item = self.item(row, col)
            if item is not None:
                item.setSelected(True)
                self.scrollToItem(item)


# --------------------------------------------------------------------------
# evaluation graph
# --------------------------------------------------------------------------

class EvalGraph(QWidget):
    """Evaluation per move, drawn as a filled curve."""

    plyClicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.scores: List[Tuple[int, float, Optional[int]]] = []   # ply, cp, mate
        self.current_ply = -1
        self.setMouseTracking(True)

    def set_scores(self, scores: Sequence[Tuple[int, float, Optional[int]]]) -> None:
        self.scores = list(scores)
        self.update()

    def clear(self) -> None:
        self.scores = []
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self.scores:
            return
        w = self.width()
        idx = int((event.position().x() if hasattr(event, "position") else event.x())
                  / max(1, w) * max(1, len(self.scores) - 1))
        idx = max(0, min(len(self.scores) - 1, idx))
        ply = self.scores[idx][0]
        self.plyClicked.emit(ply)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            w, h = self.width(), self.height()
            painter.fillRect(self.rect(), QColor("#1b1f27"))
            painter.fillRect(0, h // 2, w, 1, QColor("#374151"))
            if len(self.scores) < 2:
                painter.setPen(QColor("#6b7280"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                                 "evaluation graph")
                return
            n = len(self.scores)
            pts = []
            for i, (ply, score, mate) in enumerate(self.scores):
                x = i / (n - 1) * (w - 2) + 1
                value = 8.0 if mate else max(-8.0, min(8.0, score / 100.0))
                y = h / 2 - (value / 8.0) * (h / 2 - 6)
                pts.append((x, y))
            path = QPainterPath = None  # noqa: F841
            from PyQt6.QtGui import QPainterPath as _QP
            poly = _QP()
            poly.moveTo(pts[0][0], h / 2)
            for x, y in pts:
                poly.lineTo(x, y)
            poly.lineTo(pts[-1][0], h / 2)
            poly.closeSubpath()
            painter.setBrush(QColor(122, 162, 247, 90))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(poly)
            painter.setPen(QPen(QColor("#7aa2f7"), 2))
            for i in range(1, len(pts)):
                painter.drawLine(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
        finally:
            painter.end()
