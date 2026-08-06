from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from core.calculations import range_percent
from core.constants import ReadingQuality
from core.models import SensorReading


class SensorCard(QFrame):
    def __init__(self, title: str, unit: str, lower: float, upper: float, decimals: int = 2):
        super().__init__()
        self.setObjectName("card")
        self.unit = unit
        self.lower = lower
        self.upper = upper
        self.decimals = decimals
        self.minimum: float | None = None
        self.maximum: float | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(17, 14, 17, 14)
        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        self.status_label = QLabel("Sem dados")
        self.status_label.setObjectName("pillNeutral")
        header.addWidget(title_label)
        header.addStretch()
        header.addWidget(self.status_label)
        layout.addLayout(header)

        value_row = QHBoxLayout()
        self.value_label = QLabel("—")
        self.value_label.setObjectName("sensorValue")
        unit_label = QLabel(unit)
        unit_label.setObjectName("sensorUnit")
        unit_label.setAlignment(Qt.AlignmentFlag.AlignBottom)
        value_row.addWidget(self.value_label)
        value_row.addWidget(unit_label)
        value_row.addStretch()
        layout.addLayout(value_row)

        self.range_bar = QProgressBar()
        self.range_bar.setRange(0, 100)
        self.range_bar.setTextVisible(False)
        self.range_bar.setValue(0)
        layout.addWidget(self.range_bar)

        details = QGridLayout()
        self.current_label = QLabel("— mA")
        self.percent_label = QLabel("— %")
        self.min_label = QLabel("—")
        self.max_label = QLabel("—")
        for text, row, col in [
            ("Corrente", 0, 0), ("Faixa", 0, 2), ("Mínimo", 2, 0), ("Máximo", 2, 2)
        ]:
            label = QLabel(text)
            label.setObjectName("muted")
            details.addWidget(label, row, col)
        details.addWidget(self.current_label, 1, 0)
        details.addWidget(self.percent_label, 1, 2)
        details.addWidget(self.min_label, 3, 0)
        details.addWidget(self.max_label, 3, 2)
        details.setColumnStretch(1, 1)
        layout.addLayout(details)

    def update_reading(self, reading: SensorReading, include_statistics: bool = True) -> None:
        if reading.value is None:
            self.value_label.setText("—")
        else:
            self.value_label.setText(f"{reading.value:.{self.decimals}f}")
            if include_statistics and reading.quality not in (
                ReadingQuality.INVALID, ReadingQuality.MISSING
            ):
                self.minimum = reading.value if self.minimum is None else min(self.minimum, reading.value)
                self.maximum = reading.value if self.maximum is None else max(self.maximum, reading.value)
        self.current_label.setText(
            f"{reading.current_ma:.2f} mA" if reading.current_ma is not None else "— mA"
        )
        percent = range_percent(reading.value, self.lower, self.upper)
        self.percent_label.setText(f"{percent:.1f} %" if percent is not None else "— %")
        self.range_bar.setValue(round(percent or 0))
        self.min_label.setText(f"{self.minimum:.{self.decimals}f}" if self.minimum is not None else "—")
        self.max_label.setText(f"{self.maximum:.{self.decimals}f}" if self.maximum is not None else "—")
        style = {
            ReadingQuality.VALID: "pillGood",
            ReadingQuality.SIMULATED: "pillWarn",
            ReadingQuality.WARNING: "pillWarn",
            ReadingQuality.INVALID: "pillBad",
            ReadingQuality.MISSING: "pillNeutral",
        }[reading.quality]
        self.status_label.setObjectName(style)
        self.status_label.setText(reading.quality.value.capitalize())
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def reset_statistics(self) -> None:
        self.minimum = self.maximum = None
        self.min_label.setText("—")
        self.max_label.setText("—")
