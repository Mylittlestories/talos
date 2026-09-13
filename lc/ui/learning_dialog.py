"""The learning coach: what you know, what you owe, and what to do next."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..training.learning import SKILL_LABELS, SKILLS, Learner
from .theme import tokens

BAR_BG = "#22262f"
GOOD = "#4ade80"
WARN = "#fbbf24"
BAD = "#f87171"


def _colour(value: float) -> str:
    return BAD if value < 35 else (WARN if value < 65 else GOOD)


class MasteryBar(QWidget):
    """One row: the theme, a filled bar and the number."""

    def __init__(self, label: str, value: float, rating: int, seen: int,
                 parent=None):
        super().__init__(parent)
        self.label = label
        self.value = max(0.0, min(100.0, value))
        self.rating = rating
        self.seen = seen
        self.setMinimumHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        painter.setPen(QColor(tokens()["textDim"]))
        font = QFont("Sans Serif")
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, 118, h), Qt.AlignmentFlag.AlignVCenter,
                         self.label)
        track = QRectF(122, h / 2 - 5, w - 200, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BAR_BG))
        painter.drawRoundedRect(track, 5, 5)
        fill = QRectF(track.x(), track.y(),
                      track.width() * self.value / 100.0, track.height())
        painter.setBrush(QColor(_colour(self.value)))
        painter.drawRoundedRect(fill, 5, 5)
        painter.setPen(QColor(tokens()["text"]))
        painter.drawText(QRectF(w - 74, 0, 74, h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         f"{self.value:.0f}%  {self.rating}")
        painter.end()


class ForecastChart(QWidget):
    """How many reviews come due on each of the next seven days."""

    def __init__(self, data: Sequence[Tuple[str, int]], parent=None):
        super().__init__(parent)
        self.data = list(data)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self.data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        top = max(1, max(n for _, n in self.data))
        slot = w / max(1, len(self.data))
        bar_w = min(38.0, slot * 0.62)
        font = QFont("Sans Serif")
        font.setPixelSize(10)
        painter.setFont(font)
        for i, (label, count) in enumerate(self.data):
            cx = slot * (i + 0.5)
            bar_h = (h - 26) * (count / top)
            rect = QRectF(cx - bar_w / 2, h - 18 - bar_h, bar_w, bar_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens()["accent"] if count else BAR_BG))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(tokens()["textDim"]))
            painter.drawText(QRectF(cx - slot / 2, h - 15, slot, 13),
                             Qt.AlignmentFlag.AlignCenter, label.split()[0])
            if count:
                painter.setPen(QColor(tokens()["text"]))
                painter.drawText(QRectF(cx - slot / 2, h - 30 - bar_h, slot, 13),
                                 Qt.AlignmentFlag.AlignCenter, str(count))
        painter.end()


class StatCard(QFrame):
    def __init__(self, title: str, value: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#card { background: #1d212c; border-radius: 10px; "
                           "padding: 8px 12px; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        top = QLabel(title.upper())
        top.setStyleSheet("color: #98a1b5; font-size: 10px; letter-spacing: 1px;")
        self.value = QLabel(value)
        self.value.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(top)
        layout.addWidget(self.value)


class LearningDialog(QDialog):
    def __init__(self, learner: Learner, parent=None,
                 on_review=None, on_weakest=None):
        super().__init__(parent)
        self.learner = learner
        self.on_review = on_review
        self.on_weakest = on_weakest
        self.setWindowTitle("Learning coach")
        self.setModal(False)
        self.resize(560, 620)

        layout = QVBoxLayout(self)
        summary = learner.summary()

        self.advice = QLabel(learner.advice())
        self.advice.setWordWrap(True)
        self.advice.setStyleSheet(
            "background: #1d212c; border-radius: 10px; padding: 12px;"
            " color: #f0b429; font-size: 13px;")
        layout.addWidget(self.advice)

        stats = QHBoxLayout()
        self.stat_cards = {}
        for title, value in (("Drills seen", str(learner.cards and
                                                 sum(c.seen for c in learner.cards.values()) or 0)),
                             ("Cards tracked", str(summary["cards"])),
                             ("Due now", str(summary["due"])),
                             ("Recent accuracy", f"{summary['retention'] * 100:.0f}%")):
            card = StatCard(title, value)
            self.stat_cards[title] = card
            stats.addWidget(card)
        layout.addLayout(stats)

        box = QFrame()
        box.setObjectName("card")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box.setStyleSheet("#card { background: #161922; border-radius: 10px; }")
        col = QVBoxLayout(box)
        head = QLabel("MASTERY BY THEME")
        head.setStyleSheet("color: #98a1b5; font-size: 10px; letter-spacing: 1px;")
        col.addWidget(head)
        self.bars: Dict[str, MasteryBar] = {}
        for key, _desc in SKILLS:
            info = summary["skills"][key]
            bar = MasteryBar(SKILL_LABELS.get(key, key.title()),
                             info["mastery"], info["rating"], info["seen"])
            self.bars[key] = bar
            col.addWidget(bar)
        layout.addWidget(box)

        chart_box = QFrame()
        chart_box.setObjectName("card")
        chart_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chart_box.setStyleSheet("#card { background: #161922; border-radius: 10px; }")
        chart_col = QVBoxLayout(chart_box)
        chart_head = QLabel("REVIEWS COMING DUE")
        chart_head.setStyleSheet("color: #98a1b5; font-size: 10px;"
                                 " letter-spacing: 1px;")
        chart_col.addWidget(chart_head)
        chart_col.addWidget(ForecastChart(summary["forecast"]))
        layout.addWidget(chart_box)

        row = QHBoxLayout()
        review = QPushButton("Review what is due now")
        review.setProperty("accent", True)
        review.clicked.connect(self._review)
        weak = QPushButton("Train my weakest theme")
        weak.clicked.connect(self._weakest)
        reset = QPushButton("Reset progress…")
        reset.clicked.connect(self._reset)
        row.addWidget(review)
        row.addWidget(weak)
        row.addWidget(reset)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    def _review(self) -> None:
        if self.on_review is not None:
            self.on_review()
            self.accept()

    def _weakest(self) -> None:
        if self.on_weakest is not None:
            self.on_weakest()
            self.accept()

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self, "Reset learning progress",
            "Forget every review interval and every skill rating?\n"
            "The training results themselves are kept.")
        if answer == QMessageBox.StandardButton.Yes:
            self.learner.reset()
            self.accept()

    def refresh(self) -> None:
        """Re-read the model (called after a training session ends)."""
        summary = self.learner.summary()
        self.advice.setText(self.learner.advice())
        for key, bar in self.bars.items():
            info = summary["skills"][key]
            bar.value = info["mastery"]
            bar.rating = info["rating"]
            bar.seen = info["seen"]
            bar.update()
        self.stat_cards["Cards tracked"].value.setText(str(summary["cards"]))
        self.stat_cards["Due now"].value.setText(str(summary["due"]))
        self.stat_cards["Recent accuracy"].value.setText(
            f"{summary['retention'] * 100:.0f}%")
