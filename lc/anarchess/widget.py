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

from PyQt6.QtCore import (QLineF, QPoint, QRect, QRectF, QSize, Qt,
                          pyqtSignal)
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

    #: Largest cell we are willing to draw. The land scales up to it, so a
    #: small land fills the window instead of floating in the void.
    MAX_CELL = 96

    def __init__(self, game: AnarchessGame, cell: int = 96, parent=None):
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

    #: An almost empty land still reads as a board rather than as a speck.
    MIN_EXTENT = 8

    def _grid(self) -> Tuple[int, int]:
        """Columns and rows the view must show, margins included."""
        x0, x1, y0, y1 = self.game.bounds()
        cols = (x1 - x0 + 1) + 2 * self.margin
        rows = (y1 - y0 + 1) + 2 * self.margin
        return max(cols, self.MIN_EXTENT), max(rows, self.MIN_EXTENT)

    def visible_range(self) -> Tuple[int, int, int, int]:
        """The cell window on show: the land, then as much empty board as the
        widget can hold.

        The land is unbounded, so the empty part of the window is not "off the
        board" - it is somewhere a tile could still go. Drawing it (and
        clipping it to the widget) is what stops the view looking like fog.
        """
        x0, x1, y0, y1 = self.game.bounds()
        cols, rows = self._grid()
        nat_cols = (x1 - x0 + 1) + 2 * self.margin
        nat_rows = (y1 - y0 + 1) + 2 * self.margin
        pad_x = (cols - nat_cols) // 2
        pad_y = (rows - nat_rows) // 2
        left = x0 - self.margin - pad_x
        right = left + cols - 1
        bottom = y0 - self.margin - pad_y
        top = bottom + rows - 1
        cell = self.fit_cell()
        if cell > 0:
            grow_x = int(self.width() / cell - cols) // 2 + 1
            grow_y = int(self.height() / cell - rows) // 2 + 1
            left -= grow_x
            right += grow_x
            bottom -= grow_y
            top += grow_y
        return left, right, bottom, top

    def fit_cell(self) -> int:
        """Cell size that keeps the whole land on screen.

        The canvas sits in a scroll area with ``widgetResizable`` set, so Qt
        forces it to the viewport size and ignores its size hint. With a fixed
        cell size the land was therefore clipped as soon as it outgrew the
        window and there were no scrollbars to reach the missing part - the
        board looked like a fog of war. Scale the land to fit instead; the
        wheel sets the largest size we are willing to draw.
        """
        cols, rows = self._grid()
        avail_w = max(160, self.width() - 34)
        avail_h = max(160, self.height() - 34)
        return max(10, min(self.cell_size, self.MAX_CELL,
                           int(min(avail_w / cols, avail_h / rows))))

    def _origin(self) -> Tuple[float, float]:
        left, right, bottom, top = self.visible_range()
        s = self.fit_cell()
        # centre the *drawn window* (which is wider than the land), so the
        # empty board runs off every edge instead of piling up on one side
        ox = (self.width() - (right - left + 1) * s) / 2.0
        oy = (self.height() - (top - bottom + 1) * s) / 2.0
        return ox - left * s, oy + (top + 1) * s

    def rect_for(self, cellx: int, celly: int) -> QRectF:
        ox, oy = self._origin()
        s = self.fit_cell()
        return QRectF(ox + cellx * s, oy - (celly + 1) * s, s, s)

    def cell_at(self, pos: QPoint) -> Optional[Tuple[int, int]]:
        ox, oy = self._origin()
        s = self.fit_cell()
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
    def _area_segments(self, group) -> List[QLineF]:
        """The outline of an area, as the sides that face no neighbour of the
        same colour.  Drawing only those sides is what makes an area read as
        one shape instead of as a pile of squares."""
        cells = set(group)
        out: List[QLineF] = []
        for cell in cells:
            r = self.rect_for(*cell).adjusted(1, 1, -1, -1)
            x, y, w, h = r.x(), r.y(), r.width(), r.height()
            cx, cy = cell
            if (cx, cy + 1) not in cells:
                out.append(QLineF(x, y, x + w, y))
            if (cx, cy - 1) not in cells:
                out.append(QLineF(x, y + h, x + w, y + h))
            if (cx - 1, cy) not in cells:
                out.append(QLineF(x, y, x, y + h))
            if (cx + 1, cy) not in cells:
                out.append(QLineF(x + w, y, x + w, y + h))
        return out

    def paintEvent(self, event) -> None:  # noqa: N802
        game = self.game
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), VOID)
        s = self.fit_cell()

        # ---- the empty land, drawn as a grid
        # Without it the unexplored part of an unbounded board is just black,
        # which reads as fog rather than as somewhere you could lay a tile.
        left, right, bottom, top = self.visible_range()
        painter.setPen(QPen(QColor(86, 95, 116, 105), 1))
        for cx in range(left, right + 1):
            for cy in range(bottom, top + 1):
                if (cx, cy) in game.tiles:
                    continue
                painter.drawRect(self.rect_for(cx, cy).adjusted(1, 1, -1, -1))

        # ---- areas: tint, then an outline, then what each one is worth
        groups = game.areas()
        largest = max((len(g) for g in groups), default=0)
        labels: List[Tuple[QRectF, str, QColor]] = []
        if self.show_areas:
            for group in groups:
                if len(group) < game.rules.min_area:
                    continue
                owner = game.area_control(group)
                if owner is not None:
                    tint = _player_colour(owner, 42)
                    for cell in group:
                        r = self.rect_for(*cell).adjusted(1, 1, -1, -1)
                        painter.fillRect(r, tint)
                taxed = (game.rules.tax_largest_area and len(group) == largest
                         and len(group) >= game.rules.min_area)
                contested = owner is None and any(
                    c in game.pawns for c in group)
                if owner is not None:
                    edge = _player_colour(owner, 235)
                    width = 3.0
                else:
                    edge = QColor(160, 172, 196, 170)
                    width = 1.8
                pen = QPen(edge, width)
                if taxed:
                    # the largest area is the one the rulebook taxes down to
                    # one point a tile, so it wears a broken outline
                    pen.setStyle(Qt.PenStyle.DashLine)
                elif contested:
                    pen.setStyle(Qt.PenStyle.DotLine)
                painter.setPen(pen)
                for line in self._area_segments(group):
                    painter.drawLine(line)

                # a label on the tile nearest the middle of the area
                rate = game.area_tile_rate(
                    group, game.current if owner is None else owner, largest)
                text = (f"{len(group)}x{rate}" if owner is not None
                        else f"{len(group)}")
                cxs = [c[0] for c in group]
                cys = [c[1] for c in group]
                mid = ((min(cxs) + max(cxs)) / 2, (min(cys) + max(cys)) / 2)
                anchor = min(group, key=lambda c: (c[0] - mid[0]) ** 2
                            + (c[1] - mid[1]) ** 2)
                r = self.rect_for(*anchor)
                labels.append((QRectF(r.center().x() - s * 0.34,
                                      r.bottom() - s * 0.42,
                                      s * 0.68, s * 0.30),
                               text,
                               edge if owner is not None
                               else QColor(200, 208, 224)))

        # ---- tiles
        for cell, colour in game.tiles.items():
            r = self.rect_for(*cell).adjusted(1, 1, -1, -1)
            painter.fillRect(r, TILE_LIGHT if colour else TILE_DARK)
            painter.setPen(QPen(TILE_EDGE, 1))
            painter.drawRect(r)
            if cell == self.last_cell:
                # Under the published rules a pawn may only be settled onto
                # the tile that was just laid, so it gets a ring you can see
                # from across the room.
                painter.setPen(QPen(QColor("#f0b429"), 3.2))
                painter.drawRect(r.adjusted(1.5, 1.5, -1.5, -1.5))
                if game.placed_tile and self.settle_cells:
                    painter.setPen(QPen(QColor("#f0b429"), 1.6,
                                        Qt.PenStyle.DotLine))
                    painter.drawRect(r.adjusted(-3, -3, 3, 3))

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

        # ---- what each area scores, last so nothing covers it
        for box, text, colour in labels:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(12, 14, 20, 190)))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(QPen(colour, 1))
            painter.setFont(QFont("Sans", max(7, int(s * 0.17))))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

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
        cols, rows = self._grid()
        s = self.fit_cell()
        return self.minimumSize().expandedTo(QSize(cols * s + 30, rows * s + 30))

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
            self.cell_size = max(22, min(self.MAX_CELL,
                                         self.cell_size + (6 if delta > 0 else -6)))
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
                           self.canvas.fit_cell(), self.canvas.fit_cell())
