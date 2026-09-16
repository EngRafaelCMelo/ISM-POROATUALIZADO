from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class StatusBadge(QLabel):
    """Badge textual: o símbolo e o texto tornam o estado independente da cor."""

    SYMBOLS = {"good": "●", "warn": "▲", "bad": "■", "neutral": "○", "info": "◆"}

    def __init__(self, text: str, state: str = "neutral", parent: QWidget | None = None):
        super().__init__(parent)
        self.set_state(text, state)

    def set_state(self, text: str, state: str) -> None:
        self.setProperty("state", state)
        self.setText(f"{self.SYMBOLS.get(state, '○')}  {text}")
        self.style().unpolish(self)
        self.style().polish(self)


class SectionHeader(QWidget):
    def __init__(self, title: str, description: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        box = QVBoxLayout(); box.setSpacing(2)
        heading = QLabel(title); heading.setObjectName("sectionTitle"); box.addWidget(heading)
        if description:
            subtitle = QLabel(description); subtitle.setObjectName("muted"); box.addWidget(subtitle)
        layout.addLayout(box); layout.addStretch()


class EmptyState(QFrame):
    def __init__(self, title: str, description: str, parent: QWidget | None = None):
        super().__init__(parent); self.setObjectName("emptyState")
        layout = QVBoxLayout(self); layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        symbol = QLabel("◇"); symbol.setObjectName("emptySymbol"); symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = QLabel(title); heading.setObjectName("sectionTitle"); heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail = QLabel(description); detail.setObjectName("muted"); detail.setWordWrap(True); detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(symbol); layout.addWidget(heading); layout.addWidget(detail)
