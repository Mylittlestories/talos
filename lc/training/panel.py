"""The training side panel: task text, help grades, points and controls."""

from __future__ import annotations

from typing import Optional

import chess

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QGroupBox, QHBoxLayout, QLabel, QProgressBar,
                             QPushButton, QTextEdit, QVBoxLayout, QWidget)


class TrainingPanel(QFrame):
    """Shows the current training task and exposes the help/controls."""

    hintRequested = pyqtSignal()
    solutionRequested = pyqtSignal()
    retryRequested = pyqtSignal()
    nextRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    answerLight = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.title = QLabel("No training running")
        self.title.setStyleSheet("font-weight: 700; font-size: 14px;")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.task_label = QLabel("")
        self.task_label.setWordWrap(True)
        self.task_label.setStyleSheet("color: #d1d5db;")
        layout.addWidget(self.task_label)

        self.feedback = QTextEdit()
        self.feedback.setReadOnly(True)
        self.feedback.setMaximumHeight(120)
        self.feedback.setStyleSheet(
            "QTextEdit { background: #1b1f27; color: #e5e7eb; border: 1px solid #374151;"
            " border-radius: 4px; padding: 4px; }")
        layout.addWidget(self.feedback)

        stats = QGroupBox("Score")
        stats_layout = QHBoxLayout(stats)
        self.points_label = QLabel("0")
        self.solved_label = QLabel("0 / 0")
        self.streak_label = QLabel("streak 0")
        for label, widget in (("Points", self.points_label), ("Solved", self.solved_label),
                              ("", self.streak_label)):
            col = QVBoxLayout()
            lab = QLabel(label)
            lab.setStyleSheet("color:#9ca3af; font-size: 10px;")
            widget.setStyleSheet("font-weight: 700;")
            col.addWidget(lab)
            col.addWidget(widget)
            stats_layout.addLayout(col)
        stats_layout.addStretch(1)
        layout.addWidget(stats)

        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        row1 = QHBoxLayout()
        self.hint_button = QPushButton("Help")
        self.hint_button.setToolTip("Progressive help: piece, then square, then the move")
        self.hint_button.clicked.connect(self.hintRequested.emit)
        self.solution_button = QPushButton("Solution")
        self.solution_button.clicked.connect(self.solutionRequested.emit)
        row1.addWidget(self.hint_button)
        row1.addWidget(self.solution_button)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self.retryRequested.emit)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.nextRequested.emit)
        row2.addWidget(self.retry_button)
        row2.addWidget(self.next_button)
        layout.addLayout(row2)

        self.answer_row = QHBoxLayout()
        self.light_button = QPushButton("Light square")
        self.light_button.clicked.connect(lambda: self.answerLight.emit(True))
        self.dark_button = QPushButton("Dark square")
        self.dark_button.clicked.connect(lambda: self.answerLight.emit(False))
        self.answer_row.addWidget(self.light_button)
        self.answer_row.addWidget(self.dark_button)
        layout.addLayout(self.answer_row)

        self.stop_button = QPushButton("Stop training")
        self.stop_button.clicked.connect(self.stopRequested.emit)
        layout.addWidget(self.stop_button)
        layout.addStretch(1)
        self.set_mode("none")

    def set_mode(self, mode: str) -> None:
        is_colour = mode == "colour"
        self.light_button.setVisible(is_colour)
        self.dark_button.setVisible(is_colour)
        self.solution_button.setVisible(mode in ("solve", "tactics", "mates", "guess",
                                                 "positional", "openings", "sts"))
        self.hint_button.setVisible(mode != "none")
        self.retry_button.setVisible(mode != "none")

    def set_task(self, task) -> None:
        if task is None:
            self.title.setText("No training running")
            self.task_label.setText("")
            self.set_mode("none")
            return
        self.title.setText(task.kind.capitalize() if task.kind else "Training")
        self.task_label.setText(task.label or "")
        self.set_mode(task.kind)

    def set_feedback(self, text: str, ok: Optional[bool] = None) -> None:
        color = "#e5e7eb"
        if ok is True:
            color = "#86efac"
        elif ok is False:
            color = "#fca5a5"
        self.feedback.append(f'<span style="color:{color}">{text}</span>')
        cursor = self.feedback.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.feedback.setTextCursor(cursor)

    def clear_feedback(self) -> None:
        self.feedback.clear()

    def set_stats(self, points: int, solved: int, failed: int, streak: int,
                  progress: float = 0.0) -> None:
        self.points_label.setText(str(points))
        self.solved_label.setText(f"{solved} / {solved + failed}")
        self.streak_label.setText(f"streak {streak}")
        self.progress.setValue(int(max(0, min(100, progress * 100))))

    def set_title(self, text: str) -> None:
        self.title.setText(text)
