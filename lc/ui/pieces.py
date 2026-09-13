"""
Procedurally drawn chess piece sets.

Every piece is a QPainterPath drawn in a 100x100 box, so the artwork is
resolution independent (no bundled images) and can be re-coloured and
re-styled at will.  Styles shipped: classic, modern, cartoon, metal, wood,
outline (useful for blindfold / piece-recognition training).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import chess
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap, QRadialGradient)
from PyQt6.QtWidgets import QApplication

BOX = 100.0


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------

def _poly(points: List[Tuple[float, float]]) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(points[0][0], points[0][1])
    for x, y in points[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    return path


def _base(width: float = 27.0, y: float = 90.0, h: float = 9.0) -> QPainterPath:
    """The foot every piece stands on."""
    p = QPainterPath()
    p.moveTo(50 - width, y)
    p.lineTo(50 - width + 5, y - h * 0.45)
    p.quadTo(50 - width + 7, y - h, 50 - width + 12, y - h)
    p.lineTo(50 + width - 12, y - h)
    p.quadTo(50 + width - 7, y - h, 50 + width - 5, y - h * 0.45)
    p.lineTo(50 + width, y)
    p.closeSubpath()
    p.addEllipse(QPointF(50, y - h), width, h * 0.62)
    return p


def _collar(y: float, w: float = 17.0, h: float = 5.0) -> QPainterPath:
    p = QPainterPath()
    p.addEllipse(QPointF(50, y), w, h)
    return p


# --------------------------------------------------------------------------
# silhouettes
# --------------------------------------------------------------------------

def pawn_path() -> QPainterPath:
    p = _base(24)
    p.addPath(_poly([(38, 82), (62, 82), (57, 47), (43, 47)]))
    p.addPath(_collar(46, 15, 5))
    p.addEllipse(QPointF(50, 30), 13, 13)
    return p.simplified() if False else _merge(p)


def rook_path() -> QPainterPath:
    p = _base(27)
    p.addPath(_poly([(31, 81), (69, 81), (63, 34), (37, 34)]))
    p.addPath(_collar(33, 19, 5))
    p.addRect(QRectF(28, 22, 44, 10))
    for x in (28, 45.5, 63):
        p.addRect(QRectF(x, 11, 10, 12))
    return _merge(p)


def knight_path() -> QPainterPath:
    p = _base(26)
    path = p
    head = QPainterPath()
    head.moveTo(30, 82)
    head.lineTo(34, 56)
    head.quadTo(30, 44, 34, 34)          # back of the neck
    head.quadTo(38, 24, 46, 20)          # mane
    head.lineTo(44, 12)                  # left ear
    head.lineTo(52, 20)
    head.lineTo(58, 10)                  # right ear
    head.lineTo(63, 22)
    head.quadTo(72, 26, 74, 34)          # forehead
    head.quadTo(78, 40, 72, 44)          # nose
    head.quadTo(66, 47, 63, 43)          # mouth
    head.quadTo(58, 48, 56, 54)          # jaw
    head.quadTo(54, 62, 58, 70)          # chest
    head.lineTo(66, 82)
    head.closeSubpath()
    path.addPath(head)
    # eye
    eye = QPainterPath()
    eye.addEllipse(QPointF(61, 33), 2.6, 2.6)
    path.addPath(eye)
    return _merge(path)


def bishop_path() -> QPainterPath:
    p = _base(25)
    p.addPath(_poly([(34, 81), (66, 81), (60, 50), (40, 50)]))
    p.addPath(_collar(48, 15, 5))
    body = QPainterPath()
    body.moveTo(50, 12)
    body.quadTo(66, 30, 62, 46)
    body.lineTo(38, 46)
    body.quadTo(34, 30, 50, 12)
    p.addPath(body)
    # mitre slit
    slit = QPainterPath()
    slit.moveTo(52, 18)
    slit.quadTo(58, 28, 54, 38)
    slit.lineTo(50, 36)
    slit.quadTo(54, 27, 48, 19)
    slit.closeSubpath()
    p.addPath(slit)
    p.addEllipse(QPointF(50, 10), 4.5, 4.5)
    return _merge(p)


def queen_path() -> QPainterPath:
    p = _base(28)
    p.addPath(_poly([(33, 80), (67, 80), (62, 42), (38, 42)]))
    p.addPath(_collar(41, 17, 5))
    p.addPath(_poly([(36, 38), (64, 38), (70, 20), (30, 20)]))
    # crown: five spikes with pearls
    pts = [(28, 20), (34, 6), (40, 19), (46, 3), (52, 19), (58, 6), (64, 19), (70, 8), (72, 20)]
    p.addPath(_poly(pts))
    for cx, cy, r in ((30, 15, 3.4), (45, 11, 3.6), (50, 4.5, 3.8), (60, 13, 3.6), (70, 16, 3.4)):
        p.addEllipse(QPointF(cx, cy), r, r)
    return _merge(p)


def king_path() -> QPainterPath:
    p = _base(28)
    p.addPath(_poly([(33, 80), (67, 80), (62, 44), (38, 44)]))
    p.addPath(_collar(43, 17, 5))
    p.addPath(_poly([(36, 40), (64, 40), (68, 26), (32, 26)]))
    crown = QPainterPath()
    crown.moveTo(32, 26)
    crown.quadTo(36, 14, 42, 22)
    crown.quadTo(46, 10, 50, 20)
    crown.quadTo(54, 10, 58, 22)
    crown.quadTo(64, 14, 68, 26)
    crown.closeSubpath()
    p.addPath(crown)
    # cross
    p.addRect(QRectF(47, 0, 6, 16))
    p.addRect(QRectF(42, 4.5, 16, 6))
    return _merge(p)


def _merge(path: QPainterPath) -> QPainterPath:
    """Union the sub-paths so gradients and strokes look clean."""
    try:
        return path.simplified()
    except Exception:
        return path


PIECES = {
    chess.PAWN: pawn_path,
    chess.ROOK: rook_path,
    chess.KNIGHT: knight_path,
    chess.BISHOP: bishop_path,
    chess.QUEEN: queen_path,
    chess.KING: king_path,
}


# --------------------------------------------------------------------------
# styles
# --------------------------------------------------------------------------

class PieceStyle:
    """Colours and stroke settings for one piece set."""

    def __init__(self, name: str, light: Tuple[QColor, QColor], dark: Tuple[QColor, QColor],
                 outline_light: QColor, outline_dark: QColor, line: float = 2.2,
                 gloss: float = 0.55, detail: bool = True, eyes: bool = False):
        self.name = name
        self.light = light
        self.dark = dark
        self.outline_light = outline_light
        self.outline_dark = outline_dark
        self.line = line
        self.gloss = gloss
        self.detail = detail
        self.eyes = eyes

    def fill(self, white: bool) -> Tuple[QColor, QColor]:
        return self.light if white else self.dark

    def outline(self, white: bool) -> QColor:
        return self.outline_light if white else self.outline_dark


def _c(hexa: str) -> QColor:
    return QColor(hexa)


STYLES: Dict[str, PieceStyle] = {
    "classic": PieceStyle(
        "Classic", (_c("#fdfcf6"), _c("#cfc7b4")), (_c("#5c5550"), _c("#231f1d")),
        _c("#3b332c"), _c("#0f0d0c"), line=2.0, gloss=0.65),
    "modern": PieceStyle(
        "Modern", (_c("#ffffff"), _c("#c9d2dd")), (_c("#5a6474"), _c("#232a35")),
        _c("#334155"), _c("#0b1018"), line=1.6, gloss=0.35),
    "cartoon": PieceStyle(
        "Cartoon", (_c("#fff6d8"), _c("#f2c96b")), (_c("#7b5bff"), _c("#3a1f8f")),
        _c("#4a3a12"), _c("#150a3a"), line=3.4, gloss=0.8, eyes=True),
    "metal": PieceStyle(
        "Metal", (_c("#f6f8fb"), _c("#9aa7b8")), (_c("#7c8794"), _c("#2c323b")),
        _c("#5c6678"), _c("#0d1117"), line=1.4, gloss=0.95),
    "wood": PieceStyle(
        "Wood", (_c("#f3e0bb"), _c("#c69c5d")), (_c("#6f4a24"), _c("#33210f")),
        _c("#3d2711"), _c("#160d05"), line=2.0, gloss=0.4),
    "neon": PieceStyle(
        "Neon", (_c("#e8fff9"), _c("#59e3c0")), (_c("#c46bff"), _c("#5a1e8f")),
        _c("#0f766e"), _c("#2b0b45"), line=2.4, gloss=0.9),
    "outline": PieceStyle(
        "Outline", (_c("#ffffff"), _c("#ffffff")), (_c("#ffffff"), _c("#ffffff")),
        _c("#1f2937"), _c("#1f2937"), line=3.0, gloss=0.0, detail=False),
}


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

class PiecePainter:
    """Renders (and caches) piece pixmaps."""

    _cache: Dict[Tuple[str, int, str, bool, str], QPixmap] = {}

    @classmethod
    def pixmap(cls, piece: chess.Piece, size: int, style: str = "classic",
               effect: str = "") -> QPixmap:
        key = (piece.symbol(), size, style, piece.color == chess.WHITE, effect)
        cached = cls._cache.get(key)
        if cached is not None and not cached.isNull():
            return cached
        pm = cls.render(piece, size, style, effect)
        if len(cls._cache) > 600:
            cls._cache.clear()
        cls._cache[key] = pm
        return pm

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    @classmethod
    def render(cls, piece: chess.Piece, size: int, style: str = "classic",
               effect: str = "") -> QPixmap:
        size = max(8, int(size))
        pm = QPixmap(int(size * 1.15), int(size * 1.15))
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            cls.draw(painter, piece, size, style, effect)
        finally:
            painter.end()
        return pm

    @classmethod
    def draw(cls, painter: QPainter, piece: chess.Piece, size: int,
             style: str = "classic", effect: str = "") -> None:
        st = STYLES.get(style, STYLES["classic"])
        white = piece.color == chess.WHITE
        path_fn = PIECES.get(piece.piece_type)
        if path_fn is None:
            return
        path = path_fn()

        pad = size * 0.075
        scale = (size - pad * 2) / BOX
        painter.save()
        painter.translate(pad, pad)
        painter.scale(scale, scale)

        top, bottom = st.fill(white)
        if effect == "ghost":
            painter.setOpacity(0.35)
        elif effect == "dim":
            painter.setOpacity(0.65)

        grad = QLinearGradient(0, 0, 0, BOX)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        if st.gloss > 0.7:
            grad.setColorAt(0.45, top.lighter(108))
            grad.setColorAt(0.55, bottom)
        painter.setBrush(QBrush(grad))
        pen = QPen(st.outline(white), st.line / scale if scale else st.line)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(path)

        if st.gloss and effect != "ghost":
            painter.save()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            gloss = QPen(QColor(255, 255, 255, int(90 * st.gloss)), st.line * 0.9 / scale)
            gloss.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(gloss)
            clip = QPainterPath()
            clip.addRect(QRectF(0, 0, BOX / 2, BOX))
            painter.setClipPath(clip)
            painter.drawPath(path)
            painter.restore()

        if st.eyes and effect != "ghost" and piece.piece_type in (chess.PAWN, chess.KNIGHT,
                                                                  chess.KING, chess.QUEEN):
            eye = QPen(st.outline(white), st.line * 0.8 / scale)
            painter.setPen(eye)
            painter.setBrush(QBrush(st.outline(white)))
            y = 30 if piece.piece_type != chess.PAWN else 28
            for dx in (-5.5, 5.5):
                painter.drawEllipse(QPointF(50 + dx, y), 1.8, 2.4)
        painter.restore()


def style_names() -> List[str]:
    return list(STYLES)
