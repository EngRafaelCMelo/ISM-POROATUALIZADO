from __future__ import annotations

from html import escape
from typing import Any

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QMessageBox,
)

from core.constants import ReadingQuality
from core.models import SensorReading
from ui.resources import resource_path

STATE_COLORS = {
    "OK": "#16834A",
    "SIMULATED": "#6D5BD0",
    "WARNING": "#D97706",
    "STALE": "#EA8C18",
    "INVALID": "#C93C37",
    "DISCONNECTED": "#64748B",
    "MISSING": "#64748B",
    "CRITICAL": "#B42318",
}


def _state(reading: SensorReading) -> str:
    return {
        ReadingQuality.VALID: "OK",
        ReadingQuality.SIMULATED: "SIMULATED",
        ReadingQuality.WARNING: "WARNING",
        ReadingQuality.STALE: "STALE",
        ReadingQuality.INVALID: "INVALID",
        ReadingQuality.DISCONNECTED: "DISCONNECTED",
        ReadingQuality.MISSING: "MISSING",
    }[reading.quality]


def _age(reading: SensorReading) -> str:
    seconds = reading.age_seconds()
    if seconds is None:
        return "Sem atualização"
    if seconds < 60:
        return f"Atualizado há {seconds:.1f} s".replace(".", ",")
    return f"Atualizado há {seconds / 60:.0f} min"


class _InstrumentItem(QGraphicsRectItem):
    def __init__(self, key: str, title: str, rect: QRectF, callback):
        super().__init__(rect)
        self.key = key
        self.callback = callback
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setBrush(QBrush(QColor("#FFFFFF")))
        self.setPen(QPen(QColor("#D8DEE6"), 2))
        self.setZValue(10)
        self.text = QGraphicsTextItem(self)
        self.text.setDefaultTextColor(QColor("#17212B"))
        self.text.setPos(rect.x() + 10, rect.y() + 7)
        self.text.setTextWidth(rect.width() - 20)
        self.set_content(title, "—", "SEM LEITURA", "#64748B")

    def set_content(
        self, title: str, value: str, detail: str, color: str, value_size: int = 17
    ) -> None:
        self.setPen(QPen(QColor(color), 3))
        self.text.setHtml(
            f"<div style='font-family:DejaVu Sans'>"
            f"<span style='font-size:10pt;font-weight:700;color:#475569'>{title}</span><br>"
            f"<span style='font-size:{value_size}pt;font-weight:700;color:#17212B'>{value}</span><br>"
            f"<span style='font-size:9pt;font-weight:600;color:{color}'>{detail}</span></div>"
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.callback(self.key)
        super().mousePressEvent(event)


class ProcessSynoptic(QGraphicsView):
    """Sinótico passivo: apresenta estados processados, sem acessar hardware."""

    instrument_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("processSynoptic")
        self.setMinimumSize(600, 285)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self._readings = {
            "flow": SensorReading(),
            "pressure": SensorReading(),
        }
        self._connections = {"flow": "DISCONNECTED", "pressure": "DISCONNECTED"}
        self._diagnostics: dict[str, dict[str, Any]] = {"flow": {}, "pressure": {}}
        self._test_state = "AGUARDANDO"
        self._sample_code = "SEM ENSAIO"
        self._sample_name = "Nenhuma amostra selecionada"
        self._elapsed = "00:00:00"
        self._samples = 0
        self._critical = False
        self._dash_offset = 0.0
        self._build_scene()
        self.animation_timer = QTimer(self)
        self.animation_timer.setInterval(80)
        self.animation_timer.timeout.connect(self._animate_flow)
        self.instrument_clicked.connect(self._show_details)

    @property
    def animation_running(self) -> bool:
        return self.animation_timer.isActive()

    def _build_scene(self) -> None:
        equipment = QGraphicsSvgItem(str(resource_path("assets", "synoptic", "permeameter.svg")))
        equipment.setZValue(0)
        self.scene.addItem(equipment)
        path = QPainterPath()
        path.moveTo(120, 245)
        path.lineTo(129, 245)
        path.moveTo(221, 245)
        path.lineTo(238, 245)
        path.moveTo(302, 245)
        path.lineTo(330, 245)
        path.moveTo(485, 245)
        path.lineTo(545, 245)
        path.moveTo(670, 245)
        path.lineTo(730, 245)
        path.moveTo(880, 245)
        path.lineTo(975, 245)
        self.pipe = QGraphicsPathItem(path)
        self.pipe.setZValue(3)
        self.scene.addItem(self.pipe)
        self.flow_arrow = self.scene.addText("▶   ▶   ▶   ▶   ▶")
        self.flow_arrow.setDefaultTextColor(QColor(STATE_COLORS["DISCONNECTED"]))
        self.flow_arrow.setPos(330, 163)
        self.flow_arrow.setZValue(4)
        self.instruments = {
            "flow": _InstrumentItem(
                "flow", "VAZÃO", QRectF(280, 18, 220, 110), self.instrument_clicked.emit
            ),
            "pressure": _InstrumentItem(
                "pressure", "PRESSÃO", QRectF(510, 18, 220, 110), self.instrument_clicked.emit
            ),
            "sample": _InstrumentItem(
                "sample",
                "ENSAIO / AMOSTRA",
                QRectF(740, 18, 230, 110),
                self.instrument_clicked.emit,
            ),
        }
        for item in self.instruments.values():
            self.scene.addItem(item)
        guides = QPainterPath()
        for x in (407, 607, 840):
            guides.moveTo(x, 128)
            guides.lineTo(x, 188)
        self.guides = QGraphicsPathItem(guides)
        self.guides.setPen(QPen(QColor("#94A3B8"), 2, Qt.PenStyle.DashLine))
        self.guides.setZValue(2)
        self.scene.addItem(self.guides)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-10, -10, 10, 10))
        self._update_pipe("DISCONNECTED")

    def _fit_scene(self) -> None:
        """Enquadra somente a área desenhada, com uma margem visual curta."""
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_scene()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit_scene()

    def update_pressure(self, reading: SensorReading) -> None:
        self._readings["pressure"] = reading
        self._update_instrument("pressure", "PRESSÃO")

    def update_flow(self, reading: SensorReading) -> None:
        self._readings["flow"] = reading
        self._update_instrument("flow", "VAZÃO")
        state = _state(reading)
        coherent = reading.valid and reading.value is not None and reading.value > 0
        self._update_pipe(state if coherent or state in {"STALE", "INVALID"} else "DISCONNECTED")
        if coherent:
            if not self.animation_timer.isActive():
                self.animation_timer.start()
        else:
            self.animation_timer.stop()

    def _update_instrument(self, key: str, title: str) -> None:
        reading = self._readings[key]
        state = _state(reading)
        value = "—"
        if reading.value is not None:
            decimals = 3 if key == "flow" else 2
            value = f"{reading.value:.{decimals}f} {reading.unit}".replace(".", ",")
        detail = f"{_age(reading)} · {state}"
        self.instruments[key].set_content(title, value, detail, STATE_COLORS[state])
        self.instruments[key].setToolTip(self._tooltip(key, reading))

    def _tooltip(self, key: str, reading: SensorReading) -> str:
        stamp = (
            reading.timestamp.isoformat(sep=" ", timespec="milliseconds")
            if reading.timestamp
            else "—"
        )
        origin = "USB–RS485 / Modbus RTU" if key == "flow" else "ESP32 / ADS1115"
        return "\n".join(
            [
                f"Valor: {reading.value if reading.value is not None else '—'} {reading.unit}",
                f"Timestamp: {stamp}",
                f"Idade: {_age(reading)}",
                f"Valor bruto: {reading.raw_value if reading.raw_value is not None else '—'}",
                f"Qualidade: {_state(reading)}",
                f"Dispositivo: {reading.device_status or self._connections[key]}",
                f"Origem: {origin}",
            ]
        )

    def set_pressure_connection(self, state: str) -> None:
        self._connections["pressure"] = state.upper()
        if state.upper() == "DISCONNECTED":
            reading = self._readings["pressure"]
            reading.quality = ReadingQuality.DISCONNECTED
            self.update_pressure(reading)

    def set_flow_connection(self, state: str) -> None:
        self._connections["flow"] = state.upper()
        if state.upper() == "DISCONNECTED":
            reading = self._readings["flow"]
            reading.quality = ReadingQuality.DISCONNECTED
            self.update_flow(reading)

    def set_test_state(self, state: str) -> None:
        self._test_state = state.upper()
        self._update_sample()

    def set_sample(self, code: str, name: str) -> None:
        self._sample_code = code or "SEM ENSAIO"
        self._sample_name = name or "Nenhuma amostra selecionada"
        self._update_sample()

    def set_runtime(self, elapsed: str, samples: int) -> None:
        self._elapsed, self._samples = elapsed, samples

    def set_diagnostics(self, instrument: str, **values: Any) -> None:
        if instrument in self._diagnostics:
            self._diagnostics[instrument].update(values)

    def set_critical_alarm(self, active: bool) -> None:
        self._critical = active
        if active:
            self._update_pipe("CRITICAL")
            self.animation_timer.stop()
        else:
            self.update_flow(self._readings["flow"])

    def _update_sample(self) -> None:
        color = STATE_COLORS["SIMULATED"] if "SIMUL" in self._test_state else STATE_COLORS["OK"]
        if self._test_state in {"AGUARDANDO", "FINALIZADO"}:
            color = STATE_COLORS["DISCONNECTED"]
        elif self._test_state == "PAUSADO":
            color = STATE_COLORS["WARNING"]
        name = self._sample_name if len(self._sample_name) <= 16 else self._sample_name[:15] + "…"
        self.instruments["sample"].set_content(
            "ENSAIO / AMOSTRA",
            f"{escape(self._sample_code)} · {escape(name)}",
            self._test_state,
            color,
            12,
        )
        self.instruments["sample"].setToolTip(
            f"Ensaio: {self._sample_code}\nAmostra: {self._sample_name}\nSituação: {self._test_state}"
        )

    def _update_pipe(self, state: str) -> None:
        color = STATE_COLORS.get(state, STATE_COLORS["DISCONNECTED"])
        pen = QPen(QColor(color), 8, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap)
        pen.setDashPattern([7, 5])
        pen.setDashOffset(self._dash_offset)
        self.pipe.setPen(pen)
        self.flow_arrow.setDefaultTextColor(QColor(color))

    def _animate_flow(self) -> None:
        self._dash_offset = (self._dash_offset - 1.5) % 24
        self._update_pipe(_state(self._readings["flow"]))

    def _show_details(self, key: str) -> None:
        if key == "sample":
            text = self.instruments[key].toolTip()
        else:
            text = self._tooltip(key, self._readings[key])
            diagnostics = self._diagnostics[key]
            if diagnostics:
                text += "\n\nDiagnóstico:\n" + "\n".join(
                    f"{name}: {value}" for name, value in diagnostics.items()
                )
        QMessageBox.information(self, "Detalhes do instrumento", text)

    def reset(self) -> None:
        self.animation_timer.stop()
        self._readings = {"flow": SensorReading(), "pressure": SensorReading()}
        self._connections = {"flow": "DISCONNECTED", "pressure": "DISCONNECTED"}
        self._test_state = "AGUARDANDO"
        self._sample_code = "SEM ENSAIO"
        self._sample_name = "Nenhuma amostra selecionada"
        self._elapsed, self._samples, self._critical = "00:00:00", 0, False
        self._update_instrument("flow", "VAZÃO")
        self._update_instrument("pressure", "PRESSÃO")
        self._update_sample()
        self._update_pipe("DISCONNECTED")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.animation_timer.stop()
        super().closeEvent(event)
