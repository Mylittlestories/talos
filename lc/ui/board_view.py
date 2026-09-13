"""
The 2D board: painting, themes, drag & drop, arrows, hints and animations.

This widget is deliberately self contained: it is fed a chess.Board and it
emits move requests, which makes it reusable for play, analysis, database
browsing, position setup and every training mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import chess

from PyQt6.QtCore import (QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation,
                          QRect, QRectF, Qt, QTimer, pyqtProperty, pyqtSignal)
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QMouseEvent, QPainter,
                         QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient)
from PyQt6.QtWidgets import QApplication, QMenu, QSizePolicy, QWidget

from .pieces import PiecePainter, STYLES


# --------------------------------------------------------------------------
# themes
# --------------------------------------------------------------------------

@dataclass
class BoardTheme:
    name: str
    light: str
    dark: str
    border: str = "#3b2f26"
    coord: str = "#7a6a55"
    highlight: str = "#f6f06a"
    lastmove: str = "#c8e06a"
    check: str = "#ff5a4a"
    select: str = "#4aa3ff"
    arrow: str = "#1f7ae0"
    texture: bool = True

    def light_color(self) -> QColor:
        return QColor(self.light)

    def dark_color(self) -> QColor:
        return QColor(self.dark)


THEMES: Dict[str, BoardTheme] = {
    "wood":     BoardTheme("Wood",     "#f0d9b5", "#b58863"),
    "marble":   BoardTheme("Marble",   "#eaeaea", "#9aa7b4", border="#2f3640", coord="#5b6570"),
    "green":    BoardTheme("Green",    "#eeeed2", "#769656"),
    "blue":     BoardTheme("Blue",     "#dee3e6", "#7d99b0"),
    "grey":     BoardTheme("Grey",     "#e6e6e6", "#9b9b9b", border="#333333", coord="#666666"),
    "brown":    BoardTheme("Brown",    "#e8c9a0", "#a9703f"),
    "purple":   BoardTheme("Purple",   "#e9dcf5", "#9a7bb5", border="#3a2f46", coord="#6b5b7b"),
    "olive":    BoardTheme("Olive",    "#f2f0d8", "#9aa86b"),
    "nautical": BoardTheme("Nautical", "#dbe9f4", "#5a7fa6", border="#22384a", coord="#4a6478"),
    "highcontrast": BoardTheme("High contrast", "#ffffff", "#3d3d3d", border="#000000",
                              coord="#000000", highlight="#ffe600", lastmove="#b6ff00"),
}


# --------------------------------------------------------------------------
# overlay items
# --------------------------------------------------------------------------

@dataclass
class Arrow:
    from_square: chess.Square
    to_square: chess.Square
    color: str = "#1f7ae0"
    width: float = 0.28


@dataclass
class Marker:
    square: chess.Square
    kind: str = "circle"          # circle | square | triangle | cross
    color: str = "#ff3b30"


@dataclass
class AnimState:
    piece: chess.Piece
    from_square: chess.Square
    to_square: chess.Square
    t: float = 0.0
    duration: int = 220


# --------------------------------------------------------------------------
# board view
# --------------------------------------------------------------------------

class BoardView(QWidget):
    """A chess board that paints itself and emits moves."""

    moveRequested = pyqtSignal(object)         # chess.Move
    squareClicked = pyqtSignal(object)         # chess.Square
    squareRightClicked = pyqtSignal(object, object)  # square, global pos
    promotionChosen = pyqtSignal(object)
    illegalMove = pyqtSignal(object)
    userArrow = pyqtSignal(object)             # Arrow

    def __init__(self, parent=None, board: Optional[chess.Board] = None,
                 theme: str = "wood", piece_style: str = "classic"):
        super().__init__(parent)
        self.board = board or chess.Board()
        self.theme = THEMES.get(theme, THEMES["wood"])
        self.piece_style = piece_style
        self.orientation = chess.WHITE
        self.flipped = False

        self.selected: Optional[chess.Square] = None
        self.drag_from: Optional[chess.Square] = None
        self.drag_piece: Optional[chess.Piece] = None
        self.drag_pos: Optional[QPointF] = None
        self.hover_square: Optional[chess.Square] = None
        self.arrows: List[Arrow] = []
        self.markers: List[Marker] = []
        self.user_arrows: List[Arrow] = []
        self.user_markers: List[Marker] = []
        self._arrow_start: Optional[chess.Square] = None
        self.last_move: Optional[chess.Move] = None
        self.check_square: Optional[chess.Square] = None
        self.hint_move: Optional[chess.Move] = None
        self.hint_squares: List[chess.Square] = []
        self.drop_piece: Optional[int] = None      # crazyhouse: piece waiting to drop
        self.blindfold: bool = False
        self.show_coords: bool = True
        self.show_legal: bool = True
        self.animate: bool = True
        self.highlight_checks: bool = True
        self.coord_training: bool = False       # coordinates hidden, click-to-name mode
        self.animation: Optional[AnimState] = None
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_animation)
        self._anim_started = 0
        self._flash = 0.0
        self._pockets: Dict[bool, Dict[int, int]] = {}

        self.setMouseTracking(True)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    # -- geometry ---------------------------------------------------------
    def board_rect(self) -> QRect:
        size = min(self.width(), self.height())
        left = (self.width() - size) / 2
        top = (self.height() - size) / 2
        return QRect(int(left), int(top), int(size), int(size))

    def square_size(self) -> float:
        return self.board_rect().width() / 8.0

    def square_rect(self, square: chess.Square) -> QRectF:
        ss = self.square_size()
        r = self.board_rect()
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        if self.orientation == chess.WHITE:
            x = r.left() + file * ss
            y = r.top() + (7 - rank) * ss
        else:
            x = r.left() + (7 - file) * ss
            y = r.top() + rank * ss
        return QRectF(x, y, ss, ss)

    def square_at(self, pos: QPoint) -> Optional[chess.Square]:
        r = self.board_rect()
        if not r.contains(pos):
            return None
        ss = self.square_size()
        fx = int((pos.x() - r.left()) / ss)
        fy = int((pos.y() - r.top()) / ss)
        if not (0 <= fx < 8 and 0 <= fy < 8):
            return None
        if self.orientation == chess.WHITE:
            return chess.square(fx, 7 - fy)
        return chess.square(7 - fx, fy)

    # -- public api -------------------------------------------------------
    def set_board(self, board: chess.Board, last_move: Optional[chess.Move] = None) -> None:
        self.board = board
        if last_move is not None:
            self.last_move = last_move
        self.selected = None
        self.drag_from = None
        self.check_square = board.king(board.turn) if board.is_check() else None
        self._update_pockets()
        self.update()

    def _update_pockets(self) -> None:
        self._pockets = {True: {}, False: {}}
        if hasattr(self.board, "pockets"):
            for color in (chess.WHITE, chess.BLACK):
                pocket = self.board.pockets[color]
                for pt in range(1, 6):
                    n = pocket.count(pt)
                    if n:
                        self._pockets[color == chess.WHITE][pt] = n

    def set_theme(self, name: str) -> None:
        self.theme = THEMES.get(name, THEMES["wood"])
        self.update()

    def set_piece_style(self, name: str) -> None:
        if name in STYLES:
            self.piece_style = name
            PiecePainter.clear_cache()
            self.update()

    def set_orientation(self, color: chess.Color) -> None:
        self.orientation = color
        self.flipped = color == chess.BLACK
        self.update()

    def flip(self) -> None:
        self.set_orientation(chess.BLACK if self.orientation == chess.WHITE else chess.WHITE)

    def set_arrows(self, arrows: Sequence[Arrow]) -> None:
        self.arrows = list(arrows)
        self.update()

    def set_markers(self, markers: Sequence[Marker]) -> None:
        self.markers = list(markers)
        self.update()

    def clear_overlays(self) -> None:
        self.arrows.clear()
        self.markers.clear()
        self.user_arrows.clear()
        self.user_markers.clear()
        self.hint_move = None
        self.hint_squares = []
        self.update()

    def set_hint(self, move: Optional[chess.Move] = None,
                 squares: Optional[Sequence[chess.Square]] = None) -> None:
        self.hint_move = move
        self.hint_squares = list(squares or [])
        self.update()

    def play_animation(self, piece: chess.Piece, from_square: chess.Square,
                       to_square: chess.Square, duration: int = 220) -> None:
        if not self.animate or duration <= 0:
            return
        self.animation = AnimState(piece, from_square, to_square, 0.0, duration)
        self._anim_started = self._now()
        self._anim_timer.start()

    @staticmethod
    def _now() -> int:
        from PyQt6.QtCore import QElapsedTimer
        if not hasattr(BoardView, "_timer"):
            BoardView._timer = QElapsedTimer()
            BoardView._timer.start()
        return int(BoardView._timer.elapsed())

    def _tick_animation(self) -> None:
        anim = self.animation
        if anim is None:
            self._anim_timer.stop()
            return
        elapsed = self._now() - self._anim_started
        t = min(1.0, elapsed / float(anim.duration))
        # ease out cubic
        anim.t = 1 - pow(1 - t, 3)
        if t >= 1.0:
            self.animation = None
            self._anim_timer.stop()
        self.update()

    def is_animating(self) -> bool:
        return self.animation is not None

    # -- painting ---------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._paint_board(painter)
            self._paint_overlays(painter)
            self._paint_pieces(painter)
            self._paint_coords(painter)
            self._paint_drag(painter)
        finally:
            painter.end()

    def _paint_board(self, painter: QPainter) -> None:
        r = self.board_rect()
        painter.fillRect(self.rect(), QColor("#20242c"))
        painter.setPen(Qt.PenStyle.NoPen)
        light = self.theme.light_color()
        dark = self.theme.dark_color()
        for sq in chess.SQUARES:
            rect = self.square_rect(sq)
            color = light if (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1 else dark
            painter.setBrush(QBrush(color))
            painter.drawRect(rect)
        if self.theme.texture:
            self._paint_texture(painter)

        # borders / coordinates strip
        border_pen = QPen(QColor(self.theme.border), max(1.0, r.width() / 260.0))
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5))

        # last move
        if self.last_move is not None:
            c = QColor(self.theme.lastmove)
            c.setAlpha(120)
            painter.setBrush(QBrush(c))
            painter.setPen(Qt.PenStyle.NoPen)
            for sq in (self.last_move.from_square, self.last_move.to_square):
                painter.drawRect(self.square_rect(sq))

        # hint squares
        for sq in self.hint_squares:
            c = QColor(self.theme.highlight)
            c.setAlpha(110)
            painter.setBrush(QBrush(c))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(self.square_rect(sq))

        # selection
        if self.selected is not None:
            c = QColor(self.theme.select)
            c.setAlpha(120)
            painter.setBrush(QBrush(c))
            painter.setPen(QPen(QColor(self.theme.select), 2))
            painter.drawRect(self.square_rect(self.selected))

        # check
        if self.highlight_checks and self.check_square is not None:
            rect = self.square_rect(self.check_square)
            grad = QRadialGradient(rect.center(), rect.width() * 0.75)
            c = QColor(self.theme.check)
            c.setAlpha(200)
            grad.setColorAt(0, c)
            c2 = QColor(self.theme.check)
            c2.setAlpha(0)
            grad.setColorAt(1, c2)
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(rect)

        # legal targets
        if self.show_legal and self.selected is not None:
            self._paint_legal_targets(painter, self.selected)
        if self.hint_move is not None:
            self._paint_legal_targets(painter, self.hint_move.from_square,
                                      only=[self.hint_move.to_square])

    def _paint_texture(self, painter: QPainter) -> None:
        """A subtle grain so plain colours still look like a board."""
        r = self.board_rect()
        painter.save()
        painter.setOpacity(0.05)
        painter.setPen(QPen(QColor("#000000"), 1))
        step = max(3.0, r.width() / 90.0)
        y = r.top()
        while y < r.bottom():
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y + step * 0.4))
            y += step
        painter.restore()

    def _paint_legal_targets(self, painter: QPainter, square: chess.Square,
                             only: Optional[Sequence[chess.Square]] = None) -> None:
        ss = self.square_size()
        for mv in self.board.legal_moves:
            if mv.from_square != square:
                continue
            if only is not None and mv.to_square not in only:
                continue
            rect = self.square_rect(mv.to_square)
            target = self.board.piece_at(mv.to_square)
            centre = rect.center()
            if target is not None or self.board.is_en_passant(mv):
                painter.setBrush(Qt.BrushStyle.NoBrush)
                pen = QPen(QColor("#20242c"), max(1.6, ss * 0.055))
                painter.setPen(pen)
                painter.drawEllipse(centre, ss * 0.44, ss * 0.44)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                c = QColor("#101418")
                c.setAlpha(85)
                painter.setBrush(QBrush(c))
                painter.drawEllipse(centre, ss * 0.16, ss * 0.16)

    def _paint_overlays(self, painter: QPainter) -> None:
        for arrow in list(self.arrows) + list(self.user_arrows):
            self._draw_arrow(painter, arrow)
        for marker in list(self.markers) + list(self.user_markers):
            self._draw_marker(painter, marker)

    def _draw_arrow(self, painter: QPainter, arrow: Arrow) -> None:
        a = self.square_rect(arrow.from_square).center()
        b = self.square_rect(arrow.to_square).center()
        ss = self.square_size()
        color = QColor(arrow.color)
        color.setAlpha(215)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        dx, dy = b.x() - a.x(), b.y() - a.y()
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head = ss * 0.62
        half = ss * arrow.width * 0.5
        tail = ss * 0.34
        start = QPointF(a.x() + ux * tail, a.y() + uy * tail)
        base = QPointF(b.x() - ux * head * 0.55, b.y() - uy * head * 0.55)
        poly = QPolygonF([
            QPointF(start.x() + px * half, start.y() + py * half),
            QPointF(base.x() + px * half, base.y() + py * half),
            QPointF(base.x() + px * head * 0.5, base.y() + py * head * 0.5),
            QPointF(b.x(), b.y()),
            QPointF(base.x() - px * head * 0.5, base.y() - py * head * 0.5),
            QPointF(base.x() - px * half, base.y() - py * half),
            QPointF(start.x() - px * half, start.y() - py * half),
        ])
        painter.drawPolygon(poly)

    def _draw_marker(self, painter: QPainter, marker: Marker) -> None:
        rect = self.square_rect(marker.square)
        color = QColor(marker.color)
        painter.setPen(QPen(color, max(2.0, self.square_size() * 0.06)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pad = self.square_size() * 0.12
        if marker.kind == "square":
            painter.drawRect(rect.adjusted(pad, pad, -pad, -pad))
        elif marker.kind == "triangle":
            p = QPolygonF([
                QPointF(rect.center().x(), rect.top() + pad),
                QPointF(rect.right() - pad, rect.bottom() - pad),
                QPointF(rect.left() + pad, rect.bottom() - pad)])
            painter.drawPolygon(p)
        elif marker.kind == "cross":
            painter.drawLine(rect.topLeft() + QPointF(pad, pad),
                             rect.bottomRight() - QPointF(pad, pad))
            painter.drawLine(rect.topRight() + QPointF(-pad, pad),
                             rect.bottomLeft() + QPointF(pad, -pad))
        else:
            painter.drawEllipse(rect.center(), rect.width() / 2 - pad, rect.height() / 2 - pad)

    def _paint_pieces(self, painter: QPainter) -> None:
        if self.blindfold:
            return
        size = int(self.square_size())
        anim = self.animation
        knooks = getattr(self.board, "knooks", None)
        for sq in chess.SQUARES:
            if anim is not None and sq == anim.to_square and anim.piece is not None:
                continue
            if anim is not None and sq == anim.from_square:
                continue
            piece = self.board.piece_at(sq)
            if piece is None:
                continue
            rect = self.square_rect(sq)
            pm = PiecePainter.pixmap(piece, size, self.piece_style)
            painter.drawPixmap(rect.topLeft().toPoint(), pm)
            if knooks and sq in knooks:
                self._paint_knook_badge(painter, rect)
        if anim is not None and anim.piece is not None:
            a = self.square_rect(anim.from_square)
            b = self.square_rect(anim.to_square)
            x = a.x() + (b.x() - a.x()) * anim.t
            y = a.y() + (b.y() - a.y()) * anim.t
            lift = -self.square_size() * 0.18 * math.sin(math.pi * anim.t)
            pm = PiecePainter.pixmap(anim.piece, size, self.piece_style)
            painter.drawPixmap(QPointF(x, y + lift).toPoint(), pm)

    def _paint_knook_badge(self, painter: QPainter, rect: "QRectF") -> None:
        """Mark a fused knight/rook (a knook) with a small amber badge."""
        d = rect.width() * 0.30
        x = rect.right() - d - rect.width() * 0.04
        y = rect.bottom() - d - rect.height() * 0.04
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#1a1305"), max(1.0, d * 0.12)))
        painter.setBrush(QColor("#f0b429"))
        painter.drawEllipse(QRectF(x, y, d, d))
        painter.setPen(QColor("#1a1305"))
        font = QFont("Sans Serif")
        font.setPixelSize(max(6, int(d * 0.78)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(x, y, d, d), Qt.AlignmentFlag.AlignCenter, "N")
        painter.restore()

    def _paint_coords(self, painter: QPainter) -> None:
        if not self.show_coords or self.coord_training:
            return
        r = self.board_rect()
        ss = self.square_size()
        font = QFont("Sans Serif")
        font.setPixelSize(max(8, int(ss * 0.22)))
        painter.setFont(font)
        painter.setPen(QColor(self.theme.coord))
        files = "abcdefgh"
        for i in range(8):
            f = files[i if self.orientation == chess.WHITE else 7 - i]
            rank = str(8 - i if self.orientation == chess.WHITE else i + 1)
            x = r.left() + i * ss
            painter.drawText(QRectF(x + ss - ss * 0.30, r.bottom() - ss * 0.30, ss * 0.28, ss * 0.28),
                             Qt.AlignmentFlag.AlignCenter, f)
            painter.drawText(QRectF(x + ss * 0.02, r.top() + ss * 0.02, ss * 0.28, ss * 0.28),
                             Qt.AlignmentFlag.AlignCenter, rank)

    def _paint_drag(self, painter: QPainter) -> None:
        if self.drag_piece is None or self.drag_pos is None:
            return
        size = int(self.square_size())
        pm = PiecePainter.pixmap(self.drag_piece, size, self.piece_style)
        painter.setOpacity(0.92)
        painter.drawPixmap(QPointF(self.drag_pos.x() - pm.width() / 2,
                                   self.drag_pos.y() - pm.height() / 2).toPoint(), pm)
        painter.setOpacity(1.0)

    # -- interaction ------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        square = self.square_at(pos)
        if square is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._arrow_start = square
            self.squareRightClicked.emit(square, self.mapToGlobal(pos))
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.drop_piece is not None:
            move = self._make_move(square, square)
            if move is not None:
                self.drop_piece = None
                self.moveRequested.emit(move)
                return
        piece = self.board.piece_at(square)
        if self.selected is not None and square != self.selected:
            move = self._make_move(self.selected, square)
            if move is not None:
                self.selected = None
                self.moveRequested.emit(move)
                return
        if piece is not None and piece.color == self.board.turn:
            self.selected = square
            self.drag_from = square
            self.drag_piece = piece
            self.drag_pos = QPointF(pos)
        else:
            self.selected = None
        self.squareClicked.emit(square)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        self.drag_pos = QPointF(pos)
        sq = self.square_at(pos)
        if sq != self.hover_square:
            self.hover_square = sq
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if event.button() == Qt.MouseButton.RightButton:
            start = self._arrow_start
            end = self.square_at(pos)
            if start is not None and end is not None and start != end:
                self.user_arrows.append(Arrow(start, end, "#e07a1f"))
                self.userArrow.emit(self.user_arrows[-1])
            self._arrow_start = None
            self.update()
            return
        if self.drag_from is None:
            return
        target = self.square_at(pos)
        source = self.drag_from
        self.drag_from = None
        self.drag_piece = None
        self.drag_pos = None
        if target is None or target == source:
            self.update()
            return
        move = self._make_move(source, target)
        if move is not None:
            self.selected = None
            self.moveRequested.emit(move)
        else:
            piece = self.board.piece_at(target)
            if piece is not None and piece.color == self.board.turn:
                self.selected = target
            else:
                self.selected = None
                self.illegalMove.emit((source, target))
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        self.update()

    def _make_move(self, from_square: chess.Square, to_square: chess.Square) -> Optional[chess.Move]:
        if self.drop_piece is not None:
            for candidate in self.board.legal_moves:
                if candidate.drop == self.drop_piece and candidate.to_square == to_square:
                    return candidate
            return None
        piece = self.board.piece_at(from_square)
        if piece is None:
            return None
        promo = None
        if piece.piece_type == chess.PAWN and chess.square_rank(to_square) in (0, 7):
            promo = chess.QUEEN
        move = chess.Move(from_square, to_square, promotion=promo)
        if move in self.board.legal_moves:
            return move
        # castling with the rook, or promotion choice
        for candidate in self.board.legal_moves:
            if candidate.from_square == from_square and candidate.to_square == to_square:
                if candidate.promotion and candidate.promotion != chess.QUEEN:
                    continue
                return candidate
        return None

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_F:
            self.flip()
        elif event.key() == Qt.Key.Key_Escape:
            self.selected = None
            self.clear_overlays()
        else:
            super().keyPressEvent(event)

    def sizeHint(self):  # noqa: N802
        return self.minimumSizeHint() * 3
