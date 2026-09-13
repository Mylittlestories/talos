"""
Anarchess board widget.

A tile-laying game needs a board that grows, so this is not the chess board
view: the land lives on an unbounded integer grid, the canvas resizes as the
land spreads and the view keeps the action centred.

Interaction is a strict two-step turn, matching the rules:

* step 1 - click an empty cell touching the land to lay a tile in the colour
  picked in the side panel;
* step 2 - click one of your pawns and then a highlighted target to settle,
  step or attack; press **Skip** (or click the pawn again) to take no action.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QMouseEvent
from PyQt6.QtWidgets import (QFrame, QScrollArea, QSizePolicy, QVBoxLayout,
                             QWidget)

from .rules import (DARK, LIGHT, PLAYER_COLOURS, AnarchessAction,
                    AnarchessGame, neighbours)

TILE_LIGHT = QColor("#efe4cd")
TILE_DARK = QColor("#8d6a48")
TILE_EDGE = QColor("#5d4632")
VOID = QColor("#12141a")


def _player_colour(index: int, alpha: int = 255) -> QColor:
    c = QColor(PLAYER_COLOURS[index % len(PLAYER_COLOURS)])
    c.setAlpha(alpha)
    return c


class AnarchessCanvas(QWidget):
    """Draws the land and handles mouse interaction."""

    cellClicked = pyqtSignal(int, int)
    hoverChanged = pyqtSignal(object)          # Optional[(x, y)]
    statusTip = pyqtSignal(str)

    def __init__(self, game: AnarchessGame, cell: int = 58, parent=None):
        super().__init__(parent)
        self.game = game
        self.cell_size = cell
        self.margin = 2                        # cells of breathing room
        self.selected_colour = LIGHT

        self.hover: Optional[Tuple[int, int]] = None
        self.legal_cells: List[Tuple[int, int]] = []
        self.selected_pawn: Optional[Tuple[int, int]] = None
        self.targets: Dict[Tuple[int, int], str] = {}
        self.settle_cells: List[Tuple[int, int]] = []
        self.last_cell: Optional[Tuple[int, int]] = None
        self.show_areas = True

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumSize(420, 340)

    # ------------------------------------------------------------------
    # geometry
    # ------------------------------------------------------------------
    def set_game(self, game: AnarchessGame) -> None:
        self.game = game
        self._refresh()

    def set_colour(self, colour: bool) -> None:
        self.selected_colour = colour
        self.update()

    def _origin(self) -> Tuple[float, float]:
        x0, x1, y0, y1 = self.game.bounds()
        width = (x1 - x0 + 1 + 2 * self.margin) * self.cell_size
        height = (y1 - y0 + 1 + 2 * self.margin) * self.cell_size
        ox = (self.width() - width) / 2.0
        oy = (self.height() - height) / 2.0
        return ox + (self.margin - x0) * self.cell_size, \
            oy + (y1 + self.margin) * self.cell_size

    def rect_for(self, cellx: int, celly: int) -> QRectF:
        ox, oy = self._origin()
        s = self.cell_size
        return QRectF(ox + cellx * s, oy - (celly + 1) * s, s, s)

    def cell_at(self, pos: QPoint) -> Optional[Tuple[int, int]]:
        ox, oy = self._origin()
        s = self.cell_size
        cx = int((pos.x() - ox) // s)
        cy = int((oy - pos.y()) // s)
        return (cx, cy)

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        self.update()
        self.updateGeometry()

    def set_hints(self, legal: Sequence[Tuple[int, int]],
                  selected: Optional[Tuple[int, int]],
                  targets: Dict[Tuple[int, int], str],
                  settle: Sequence[Tuple[int, int]]) -> None:
        self.legal_cells = list(legal)
        self.selected_pawn = selected
        self.targets = dict(targets)
        self.settle_cells = list(settle)
        self.update()

    # ------------------------------------------------------------------
    # painting
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        game = self.game
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), VOID)
        s = self.cell_size

        # ---- area ownership tint
        if self.show_areas:
            for group in game.areas():
                if len(group) < game.rules.min_area:
                    continue
                owner = game.area_control(group)
                if owner is None:
                    continue
                colour = _player_colour(owner, 42)
                for cell in group:
                    r = self.rect_for(*cell).adjusted(1, 1, -1, -1)
                    painter.fillRect(r, colour)

        # ---- tiles
        for cell, colour in game.tiles.items():
            r = self.rect_for(*cell).adjusted(1, 1, -1, -1)
            painter.fillRect(r, TILE_LIGHT if colour else TILE_DARK)
            painter.setPen(QPen(TILE_EDGE, 1))
            painter.drawRect(r)
            if cell == self.last_cell:
                painter.setPen(QPen(QColor("#f0b429"), 2.5))
                painter.drawRect(r.adjusted(1.5, 1.5, -1.5, -1.5))

        # ---- legal placements
        if self.legal_cells:
            painter.setPen(QPen(QColor("#4cc2ff"), 1.4, Qt.PenStyle.DotLine))
            for cell in self.legal_cells:
                r = self.rect_for(*cell).adjusted(6, 6, -6, -6)
                painter.drawRoundedRect(r, 5, 5)

        # ---- ghost tile under the cursor
        if self.hover in set(self.legal_cells):
            r = self.rect_for(*self.hover).adjusted(1, 1, -1, -1)
            ghost = QColor(TILE_LIGHT if self.selected_colour else TILE_DARK)
            ghost.setAlpha(150)
            painter.fillRect(r, ghost)
            painter.setPen(QPen(QColor("#ffffff"), 1.6))
            painter.drawRect(r)

        # ---- settle targets
        for cell in self.settle_cells:
            r = self.rect_for(*cell)
            painter.setPen(QPen(QColor("#4ade80"), 2, Qt.PenStyle.DashLine))
            painter.drawEllipse(r.adjusted(s * 0.3, s * 0.3, -s * 0.3, -s * 0.3))

        # ---- move / attack targets
        for cell, kind in self.targets.items():
            r = self.rect_for(*cell)
            colour = QColor("#f87171") if kind == "attack" else QColor("#4ade80")
            painter.setPen(QPen(colour, 2.4))
            painter.drawEllipse(r.adjusted(s * 0.18, s * 0.18, -s * 0.18, -s * 0.18))
            painter.setPen(QPen(colour, 1))
            painter.drawEllipse(r.adjusted(s * 0.34, s * 0.34, -s * 0.34, -s * 0.34))

        # ---- pawns
        font = QFont("Sans", max(8, int(s * 0.24)))
        painter.setFont(font)
        for cell, owner in game.pawns.items():
            r = self.rect_for(*cell)
            cx = r.center()
            radius = s * 0.31
            body = _player_colour(owner)
            edge = QColor(20, 22, 28, 220)
            painter.setPen(QPen(edge, 2))
            painter.setBrush(QBrush(body))
            painter.drawEllipse(cx, radius, radius)
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1.5))
            painter.drawEllipse(QRectF(cx.x() - radius * 0.55,
                                       cx.y() - radius * 0.55,
                                       radius * 0.7, radius * 0.5))
            if self.selected_pawn == cell:
                painter.setPen(QPen(QColor("#f0b429"), 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(cx, radius + 5, radius + 5)
            painter.setPen(QColor(20, 22, 28))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, str(owner + 1))

        # ---- coordinate hints
        painter.setPen(QColor("#3a4356"))
        x0, x1, y0, y1 = game.bounds()
        small = QFont("Sans", 8)
        painter.setFont(small)
        for cx in range(x0, x1 + 1):
            r = self.rect_for(cx, y0)
            painter.drawText(QRectF(r.x(), r.bottom() + 2, s, 14),
                             Qt.AlignmentFlag.AlignCenter,
                             "abcdefghijklmnopqrstuvwxyz"[cx % 26])
        for cy in range(y0, y1 + 1):
            r = self.rect_for(x0, cy)
            painter.drawText(QRectF(r.x() - 22, r.y(), 18, s),
                             Qt.AlignmentFlag.AlignVCenter |
                             Qt.AlignmentFlag.AlignRight, str(cy + 1))
        painter.end()

    def sizeHint(self):  # noqa: N802
        x0, x1, y0, y1 = self.game.bounds()
        w = (x1 - x0 + 1 + 2 * self.margin) * self.cell_size + 30
        h = (y1 - y0 + 1 + 2 * self.margin) * self.cell_size + 30
        return self.minimumSize().expandedTo(QSize(w, h))

    # ------------------------------------------------------------------
    # input
    # ------------------------------------------------------------------
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        cell = self.cell_at(event.position().toPoint())
        if cell != self.hover:
            self.hover = cell
            self.hoverChanged.emit(cell)
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.hover = None
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        cell = self.cell_at(event.position().toPoint())
        if cell is not None:
            self.cellClicked.emit(cell[0], cell[1])

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self.cell_size = max(22, min(96, self.cell_size + (6 if delta > 0 else -6)))
            self._refresh()


class AnarchessBoard(QScrollArea):
    """Scrollable container that keeps the freshly laid tile visible."""

    def __init__(self, game: AnarchessGame, parent=None):
        super().__init__(parent)
        self.canvas = AnarchessCanvas(game)
        self.setWidget(self.canvas)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QScrollArea { background: #12141a; border: none; }")

    def centre_on(self, cellx: int, celly: int) -> None:
        rect = self.canvas.rect_for(cellx, celly)
        self.ensureVisible(int(rect.center().x()), int(rect.center().y()),
                           self.canvas.cell_size, self.canvas.cell_size)
