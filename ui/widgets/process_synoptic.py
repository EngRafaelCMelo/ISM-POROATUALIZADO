from __future__ import annotations

from html import escape
from typing import Any

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
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
        return "sem atualização"
    if seconds < 60:
        return f"atualizado há {seconds:.1f} s".replace(".", ",")
    return f"atualizado há {seconds / 60:.0f} min"


class EquipmentItem(QGraphicsSvgItem):
    """Ilustração vetorial individual, sem responsabilidade por dados."""

    def __init__(
        self,
        asset: str,
        label: str,
        x: float,
        y: float,
        scale: float,
        *,
        key: str | None = None,
        callback=None,
    ) -> None:
        super().__init__(str(resource_path("assets", "synoptic", "equipment", asset)))
        self.key = key
        self.callback = callback
        self.setPos(x, y)
        self.setScale(scale)
        self.setZValue(4)
        self.setToolTip(f"{label} — clique para detalhes" if key else label)
        self.setAcceptHoverEvents(key is not None)
        if key is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hover_outline = QGraphicsRectItem(self.boundingRect().adjusted(-5, -5, 5, 5), self)
        self.hover_outline.setBrush(Qt.BrushStyle.NoBrush)
        self.hover_outline.setPen(QPen(QColor("#58B719"), 3, Qt.PenStyle.DashLine))
        self.hover_outline.setZValue(-1)
        self.hover_outline.hide()

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        if self.key is not None:
            self.hover_outline.show()
            self.setOpacity(0.94)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self.hover_outline.hide()
        self.setOpacity(1.0)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.key is not None and self.callback is not None:
            self.callback(self.key)
        super().mousePressEvent(event)


class ValueOverlayItem(QGraphicsRectItem):
    """Leitura dinâmica ancorada ao equipamento correspondente."""

    def __init__(self, key: str, title: str, rect: QRectF, callback) -> None:
        super().__init__(rect)
        self.key = key
        self.callback = callback
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setBrush(QBrush(QColor("#F8FAFC")))
        self.setPen(QPen(QColor("#64748B"), 2))
        self.setZValue(10)
        self.text = QGraphicsTextItem(self)
        self.text.setDefaultTextColor(QColor("#17212B"))
        self.text.setPos(rect.x() + 10, rect.y() + 5)
        self.text.setTextWidth(rect.width() - 20)
        self.set_content(title, "—", "", "SEM LEITURA", STATE_COLORS["MISSING"])

    def set_content(
        self,
        title: str,
        value: str,
        unit: str,
        detail: str,
        color: str,
        value_size: int = 17,
    ) -> None:
        self.setPen(QPen(QColor(color), 2.5))
        unit_html = (
            f" <span style='font-size:{max(value_size - 5, 9)}pt;font-weight:600;color:#475569'>"
            f"{escape(unit)}</span>"
            if unit
            else ""
        )
        self.text.setHtml(
            "<div style='font-family:DejaVu Sans'>"
            f"<span style='font-size:9pt;font-weight:700;color:#526274'>{escape(title)}</span><br>"
            f"<span style='font-size:{value_size}pt;font-weight:750;color:#17212B'>"
            f"{escape(value)}</span>{unit_html}<br>"
            f"<span style='font-size:8pt;font-weight:650;color:{color}'>"
            f"{escape(detail)}</span></div>"
        )

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        self.setBrush(QBrush(QColor("#EEF4F7")))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self.setBrush(QBrush(QColor("#F8FAFC")))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.callback(self.key)
        super().mousePressEvent(event)


class PipeItem(QGraphicsPathItem):
    """Tubulação do processo com estado e animação independentes do desenho."""

    def __init__(self, path: QPainterPath) -> None:
        super().__init__(path)
        self.setZValue(2)
        self.set_state("DISCONNECTED", 0.0)

    def set_state(self, state: str, dash_offset: float) -> None:
        pen = QPen(
            QColor(STATE_COLORS.get(state, STATE_COLORS["DISCONNECTED"])),
            7,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        if state not in {"DISCONNECTED", "MISSING"}:
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([10, 4])
            pen.setDashOffset(dash_offset)
        self.setPen(pen)


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
        self._readings = {"flow": SensorReading(), "pressure": SensorReading()}
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
        self.animation_timer.setInterval(100)
        self.animation_timer.timeout.connect(self._animate_flow)
        self.instrument_clicked.connect(self._show_details)

    @property
    def animation_running(self) -> bool:
        return self.animation_timer.isActive()

    def _build_scene(self) -> None:
        panel = QGraphicsRectItem(QRectF(0, 0, 1000, 390))
        panel.setBrush(QBrush(QColor("#1A2838")))
        panel.setPen(QPen(QColor("#526274"), 2))
        panel.setZValue(0)
        self.scene.addItem(panel)

        process_path = QPainterPath()
        process_path.moveTo(18, 110)
        process_path.lineTo(136, 110)
        process_path.lineTo(180, 110)
        process_path.lineTo(180, 108)
        process_path.lineTo(246, 108)
        process_path.lineTo(290, 108)
        process_path.lineTo(290, 160)
        process_path.lineTo(459, 160)
        process_path.lineTo(520, 160)
        process_path.lineTo(520, 119)
        process_path.lineTo(750, 119)
        process_path.lineTo(780, 119)
        process_path.lineTo(780, 155)
        process_path.lineTo(534, 155)
        process_path.lineTo(534, 176)
        process_path.lineTo(534, 273)
        process_path.lineTo(534, 375)
        process_path.lineTo(325, 375)
        process_path.lineTo(325, 299)
        process_path.lineTo(157, 299)
        process_path.lineTo(18, 300)
        self.pipe = PipeItem(process_path)
        self.scene.addItem(self.pipe)

        self.flow_arrow = self.scene.addText("▶  ▶  ▶")
        self.flow_arrow.setPos(265, 130)
        self.flow_arrow.setZValue(3)
        self.return_arrow = self.scene.addText("◀  ◀  ◀")
        self.return_arrow.setPos(465, 346)
        self.return_arrow.setZValue(3)

        equipment_specs = {
            "filter": ("filter_regulator.svg", "Filtro / regulador", 55, 34, 0.68, None),
            "valve": ("valve.svg", "Válvula de processo", 205, 72, 0.58, None),
            "flow": ("flowmeter.svg", "Flowmeter", 340, 82, 0.78, "flow"),
            "regulator": (
                "pressure_regulator.svg",
                "Regulador com manômetro",
                650,
                38,
                0.72,
                None,
            ),
            "pressure": (
                "pressure_transmitter.svg",
                "Transdutor de pressão",
                490,
                175,
                0.68,
                "pressure",
            ),
            "sample": ("sample_holder.svg", "Porta-amostra", 155, 255, 0.75, "sample"),
            "pump": ("pump.svg", "Bomba auxiliar", 850, 225, 0.70, None),
        }
        self.equipment_items: dict[str, EquipmentItem] = {}
        for name, (asset, label, x, y, scale, key) in equipment_specs.items():
            item = EquipmentItem(
                asset,
                label,
                x,
                y,
                scale,
                key=key,
                callback=self.instrument_clicked.emit,
            )
            self.equipment_items[name] = item
            self.scene.addItem(item)

        self._add_label("FILTRO / REGULADOR", 43, 157, 132)
        self._add_label("VÁLVULA", 194, 130, 88)
        self._add_label("FLOWMETER", 346, 194, 126)
        self._add_label("REGULADOR", 658, 149, 110)
        self._add_label("TRANSDUTOR", 480, 291, 118)
        self._add_label("PORTA-AMOSTRA", 169, 348, 146)
        self._add_label("BOMBA AUXILIAR", 838, 330, 152)
        self._add_label("ENTRADA", 12, 80, 74, align_left=True)
        self._add_label("SAÍDA", 12, 308, 74, align_left=True)

        self.instruments = {
            "flow": ValueOverlayItem(
                "flow", "VAZÃO", QRectF(300, 4, 235, 76), self.instrument_clicked.emit
            ),
            "pressure": ValueOverlayItem(
                "pressure",
                "PRESSÃO",
                QRectF(620, 205, 225, 84),
                self.instrument_clicked.emit,
            ),
            "sample": ValueOverlayItem(
                "sample",
                "ENSAIO / AMOSTRA",
                QRectF(350, 266, 265, 94),
                self.instrument_clicked.emit,
            ),
        }
        for item in self.instruments.values():
            self.scene.addItem(item)

        guides = QPainterPath()
        guides.moveTo(420, 80)
        guides.lineTo(420, 86)
        guides.moveTo(578, 247)
        guides.lineTo(620, 247)
        guides.moveTo(325, 299)
        guides.lineTo(350, 300)
        self.guides = QGraphicsPathItem(guides)
        self.guides.setPen(QPen(QColor("#9FB2C8"), 2, Qt.PenStyle.DashLine))
        self.guides.setZValue(5)
        self.scene.addItem(self.guides)

        self.scene.setSceneRect(QRectF(0, 0, 1000, 390))
        self._update_pipe("DISCONNECTED")

    def _add_label(
        self, text: str, x: float, y: float, width: float, *, align_left: bool = False
    ) -> None:
        label = self.scene.addText(text, QFont("DejaVu Sans", 8, QFont.Weight.DemiBold))
        label.setDefaultTextColor(QColor("#D7E0EA"))
        label.setTextWidth(width)
        label.document().setDefaultStyleSheet(
            "body { text-align: left; }" if align_left else "body { text-align: center; }"
        )
        label.setPos(x, y)
        label.setZValue(6)

    def _fit_scene(self) -> None:
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
        self._refresh_process_state()

    def update_flow(self, reading: SensorReading) -> None:
        self._readings["flow"] = reading
        self._update_instrument("flow", "VAZÃO")
        self._refresh_process_state()

    def _update_instrument(self, key: str, title: str) -> None:
        reading = self._readings[key]
        state = _state(reading)
        value, unit = "—", ""
        if reading.value is not None and state not in {"DISCONNECTED", "MISSING"}:
            decimals = 3 if key == "flow" else 2
            value = f"{reading.value:.{decimals}f}".replace(".", ",")
            unit = reading.unit
        detail = f"{state} · {_age(reading)}"
        self.instruments[key].set_content(
            title, value, unit, detail, STATE_COLORS[state], value_size=16
        )
        tooltip = self._tooltip(key, reading)
        self.instruments[key].setToolTip(tooltip)
        self.equipment_items[key].setToolTip(f"{title.title()} · {state} — clique para detalhes")

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
        else:
            self._refresh_process_state()

    def set_flow_connection(self, state: str) -> None:
        self._connections["flow"] = state.upper()
        if state.upper() == "DISCONNECTED":
            reading = self._readings["flow"]
            reading.quality = ReadingQuality.DISCONNECTED
            self.update_flow(reading)
        else:
            self._refresh_process_state()

    def set_test_state(self, state: str) -> None:
        self._test_state = state.upper()
        self._update_sample()

    def set_sample(self, code: str, name: str) -> None:
        self._sample_code = code or "SEM ENSAIO"
        self._sample_name = name or "Nenhuma amostra selecionada"
        self._update_sample()

    def set_runtime(self, elapsed: str, samples: int) -> None:
        self._elapsed, self._samples = elapsed, samples
        self._update_sample()

    def set_diagnostics(self, instrument: str, **values: Any) -> None:
        if instrument in self._diagnostics:
            self._diagnostics[instrument].update(values)

    def set_critical_alarm(self, active: bool) -> None:
        self._critical = active
        self._refresh_process_state()

    def _update_sample(self) -> None:
        color = STATE_COLORS["SIMULATED"] if "SIMUL" in self._test_state else STATE_COLORS["OK"]
        if self._test_state in {"AGUARDANDO", "FINALIZADO"}:
            color = STATE_COLORS["DISCONNECTED"]
        elif self._test_state == "PAUSADO":
            color = STATE_COLORS["WARNING"]
        name = self._sample_name if len(self._sample_name) <= 22 else self._sample_name[:21] + "…"
        elapsed = f" · {self._elapsed}" if self._elapsed != "00:00:00" else ""
        self.instruments["sample"].set_content(
            "ENSAIO / AMOSTRA",
            f"{self._sample_code} · {name}",
            "",
            f"{self._test_state}{elapsed}",
            color,
            11,
        )
        tooltip = (
            f"Ensaio: {self._sample_code}\nAmostra: {self._sample_name}\n"
            f"Situação: {self._test_state}\nTempo: {self._elapsed}"
        )
        self.instruments["sample"].setToolTip(tooltip)
        self.equipment_items["sample"].setToolTip(
            f"Porta-amostra · {self._test_state} — clique para detalhes"
        )

    def _refresh_process_state(self) -> None:
        flow = self._readings["flow"]
        pressure_state = _state(self._readings["pressure"])
        flow_state = _state(flow)
        coherent_flow = flow.valid and flow.value is not None and flow.value > 0
        if self._critical:
            process_state = "CRITICAL"
        elif "INVALID" in {pressure_state, flow_state}:
            process_state = "INVALID"
        elif "STALE" in {pressure_state, flow_state}:
            process_state = "STALE"
        elif "WARNING" in {pressure_state, flow_state}:
            process_state = "WARNING"
        elif coherent_flow and "SIMULATED" in {pressure_state, flow_state}:
            process_state = "SIMULATED"
        elif coherent_flow:
            process_state = "OK"
        else:
            process_state = "DISCONNECTED"
        self._update_pipe(process_state)
        if coherent_flow and process_state in {"OK", "SIMULATED"}:
            if not self.animation_timer.isActive():
                self.animation_timer.start()
        else:
            self.animation_timer.stop()

    def _update_pipe(self, state: str) -> None:
        self.pipe.set_state(state, self._dash_offset)
        color = QColor(STATE_COLORS.get(state, STATE_COLORS["DISCONNECTED"]))
        self.flow_arrow.setDefaultTextColor(color)
        self.return_arrow.setDefaultTextColor(color)

    def _animate_flow(self) -> None:
        self._dash_offset = (self._dash_offset - 1.0) % 28
        self._refresh_process_state()

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
