from __future__ import annotations

from html import escape
from typing import Any

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGraphicsPathItem,
    QGraphicsProxyWidget,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
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
        pipe_colors = {
            "OK": "#17658A",
            "SIMULATED": "#506B8A",
            "WARNING": "#B66A13",
            "STALE": "#B66A13",
            "INVALID": "#B42318",
            "CRITICAL": "#B42318",
            "DISCONNECTED": "#758899",
            "MISSING": "#758899",
        }
        pen = QPen(
            QColor(pipe_colors.get(state, pipe_colors["DISCONNECTED"])),
            8,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        self.setPen(pen)


class ManualSetpointWidget(QWidget):
    """Controle compacto para uma condição operacional sem telemetria."""

    value_changed = Signal(float)

    def __init__(
        self,
        title: str,
        unit: str,
        value: float,
        minimum: float,
        maximum: float,
        *,
        apply_button: bool = False,
        width: int = 210,
    ) -> None:
        super().__init__()
        self.setObjectName("manualSetpoint")
        self.setFixedSize(width, 104 if apply_button else 72)
        self.setStyleSheet(
            "QWidget#manualSetpoint{background:#F8FAFC;border:1px solid #7898B1;border-radius:5px;}"
            "QLabel{color:#10254A;font-weight:700;background:transparent;border:0;}"
            "QDoubleSpinBox{background:white;color:#10254A;border:1px solid #8AA6BF;"
            "border-radius:3px;padding:2px;font-size:13px;font-weight:700;}"
            "QPushButton{padding:3px;border:1px solid #567997;"
            "border-radius:4px;background:#EAF2F7;color:#10254A;font-weight:700;}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 5, 9, 5)
        layout.setSpacing(3)
        heading = QLabel(title)
        heading.setFont(QFont("DejaVu Sans", 8, QFont.Weight.DemiBold))
        heading.setToolTip("Valor configurado manualmente; sem telemetria")
        layout.addWidget(heading)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(1)
        self.spin.setSingleStep(1.0)
        self.spin.setSuffix(f" {unit}")
        self.spin.setValue(value)
        minus = QPushButton("−")
        plus = QPushButton("+")
        minus.setFixedWidth(34)
        plus.setFixedWidth(34)
        minus.clicked.connect(lambda: self.spin.stepDown())
        plus.clicked.connect(lambda: self.spin.stepUp())
        row.addWidget(self.spin, 1)
        row.addWidget(minus)
        row.addWidget(plus)
        layout.addLayout(row)
        if apply_button:
            apply = QPushButton("APLICAR")
            apply.setMinimumHeight(24)
            apply.clicked.connect(lambda: self.value_changed.emit(self.spin.value()))
            layout.addWidget(apply)
        self.spin.valueChanged.connect(self.value_changed)

    def set_locked(self, locked: bool) -> None:
        self.setEnabled(not locked)
        self.setToolTip(
            "Bloqueado durante o ensaio: o snapshot das condições já foi registrado."
            if locked
            else "Valor configurado manualmente; sem telemetria"
        )


class ProcessSynoptic(QGraphicsView):
    """Sinótico passivo: apresenta estados processados, sem acessar hardware."""

    instrument_clicked = Signal(str)
    setpoints_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("processSynoptic")
        self.setMinimumSize(600, 260)
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
        self._confinement_pressure = 150.0
        self._blanket_temperature = 60.0
        self._build_scene()
        self.animation_timer = QTimer(self)
        self.animation_timer.setInterval(100)
        self.animation_timer.timeout.connect(self._animate_flow)
        self.instrument_clicked.connect(self._show_details)

    @property
    def animation_running(self) -> bool:
        return self.animation_timer.isActive()

    def _build_scene(self) -> None:
        scene_rect = QRectF(0, 0, 1200, 480)
        panel = QGraphicsRectItem(scene_rect)
        panel.setBrush(QBrush(QColor("#EEF4F7")))
        panel.setPen(QPen(QColor("#9AB3C7"), 1.5))
        panel.setZValue(0)
        self.scene.addItem(panel)

        grid_pen = QPen(QColor("#DDE7ED"), 1)
        grid_pen.setCosmetic(True)
        for x in range(40, 1200, 40):
            self.scene.addLine(x, 0, x, 480, grid_pen).setZValue(0.1)
        for y in range(40, 480, 40):
            self.scene.addLine(0, y, 1200, y, grid_pen).setZValue(0.1)

        # Main gas line: inlet -> regulator -> flowmeter -> transmitter ->
        # holder. The holder outlet has no downstream instrument.
        process_path = QPainterPath()
        process_path.moveTo(1180, 168)
        process_path.lineTo(1080, 168)
        process_path.lineTo(850, 168)
        process_path.lineTo(655, 168)
        process_path.lineTo(445, 168)
        process_path.lineTo(360, 168)
        process_path.lineTo(360, 375)
        process_path.lineTo(455, 375)
        process_path.moveTo(825, 375)
        process_path.lineTo(1180, 375)
        self.pipe = PipeItem(process_path)
        self.scene.addItem(self.pipe)

        # Independent confinement circuit. The small hump at x=360 marks a
        # non-connected crossing with the vertical process pipe.
        confinement_path = QPainterPath()
        confinement_path.moveTo(165, 390)
        confinement_path.lineTo(346, 390)
        confinement_path.cubicTo(346, 372, 374, 372, 374, 390)
        confinement_path.lineTo(420, 390)
        confinement_path.lineTo(420, 330)
        confinement_path.lineTo(535, 330)
        confinement_path.lineTo(535, 346)
        confinement_path.moveTo(300, 390)
        confinement_path.lineTo(300, 235)
        confinement_path.lineTo(470, 235)
        self.confinement_pipe = QGraphicsPathItem(confinement_path)
        self.confinement_pipe.setPen(
            QPen(QColor("#2C8B8C"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        self.confinement_pipe.setZValue(2)
        self.scene.addItem(self.confinement_pipe)
        bridge = QPainterPath()
        bridge.moveTo(346, 390)
        bridge.cubicTo(346, 372, 374, 372, 374, 390)
        self.crossing_bridge = QGraphicsPathItem(bridge)
        self.crossing_bridge.setPen(QPen(QColor("#2C8B8C"), 7))
        self.crossing_bridge.setZValue(7)
        self.scene.addItem(self.crossing_bridge)

        self.flow_arrow = self.scene.addText("◀  ◀")
        self.flow_arrow.setPos(1110, 140)
        self.flow_arrow.setZValue(3)
        self.return_arrow = self.scene.addText("▶  ▶")
        self.return_arrow.setPos(1080, 347)
        self.return_arrow.setZValue(3)

        equipment_specs = {
            "filter": ("filter_regulator.svg", "Reguladora", 966, 42, 0.76, None),
            "valve": ("valve.svg", "Válvula de alívio", 272, 184, 0.62, None),
            "flow": ("flowmeter.svg", "Flowmeter", 714, 82, 0.67, "flow"),
            "regulator": (
                "pressure_regulator.svg",
                "Pressão de confinamento local",
                378,
                259,
                0.60,
                None,
            ),
            "pressure": (
                "pressure_transmitter.svg",
                "Transdutor de pressão",
                404,
                82,
                0.64,
                "pressure",
            ),
            "sample": (
                "sample_holder.svg",
                "Holder com manta térmica",
                444,
                326,
                0.88,
                "sample",
            ),
            "pump": ("pump.svg", "Bomba de confinamento", 28, 330, 0.76, None),
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

        self._add_label("REGULADORA", 966, 205, 145)
        self._add_label("VÁLVULA DE ALÍVIO", 246, 250, 180)
        self._add_label("FLOWMETER", 700, 205, 160)
        self._add_label("PRESSÃO DE CONFINAMENTO", 474, 278, 190, align_left=True)
        self._add_label("LEITURA LOCAL · SEM TELEMETRIA", 474, 300, 190, align_left=True)
        self._add_label("TRANSDUTOR DE PRESSÃO", 380, 205, 180)
        self._add_label("HOLDER", 570, 445, 120)
        self._add_label("MANTA TÉRMICA", 680, 445, 155, color="#9B3D25")
        self._add_label("BOMBA DE CONFINAMENTO", 18, 442, 190)
        self._add_label("◀  ENTRADA DO GÁS", 1090, 112, 106, align_left=True)
        self._add_label("SAÍDA DO GÁS  ▶", 1082, 383, 115, align_left=True)
        self._add_label("DESCARGA PARA ATMOSFERA  ▶", 474, 222, 195, align_left=True)

        self.instruments = {
            "flow": ValueOverlayItem(
                "flow", "VAZÃO", QRectF(680, 12, 205, 76), self.instrument_clicked.emit
            ),
            "pressure": ValueOverlayItem(
                "pressure",
                "PRESSÃO DA LINHA",
                QRectF(398, 12, 215, 76),
                self.instrument_clicked.emit,
            ),
            "sample": ValueOverlayItem(
                "sample",
                "ENSAIO / AMOSTRA",
                QRectF(875, 250, 300, 88),
                self.instrument_clicked.emit,
            ),
        }
        for item in self.instruments.values():
            self.scene.addItem(item)

        self.confinement_control = ManualSetpointWidget(
            "PRESSÃO DE CONFINAMENTO",
            "psi",
            self._confinement_pressure,
            0.0,
            1000.0,
            apply_button=True,
            width=210,
        )
        self.temperature_control = ManualSetpointWidget(
            "TEMPERATURA DA MANTA",
            "°C",
            self._blanket_temperature,
            0.0,
            200.0,
            width=200,
        )
        self.confinement_proxy = QGraphicsProxyWidget()
        self.confinement_proxy.setWidget(self.confinement_control)
        self.confinement_proxy.setPos(14, 178)
        self.confinement_proxy.setZValue(12)
        self.scene.addItem(self.confinement_proxy)
        self.temperature_proxy = QGraphicsProxyWidget()
        self.temperature_proxy.setWidget(self.temperature_control)
        self.temperature_proxy.setPos(665, 255)
        self.temperature_proxy.setZValue(12)
        self.scene.addItem(self.temperature_proxy)
        self.confinement_control.value_changed.connect(self._setpoint_edited)
        self.temperature_control.value_changed.connect(self._setpoint_edited)

        guides = QPainterPath()
        guides.moveTo(505, 88)
        guides.lineTo(482, 116)
        guides.moveTo(785, 88)
        guides.lineTo(770, 112)
        guides.moveTo(875, 295)
        guides.lineTo(830, 340)
        self.guides = QGraphicsPathItem(guides)
        self.guides.setPen(QPen(QColor("#9FB2C8"), 2, Qt.PenStyle.DashLine))
        self.guides.setZValue(5)
        self.scene.addItem(self.guides)

        # Keep the public virtual canvas compact (legacy layouts and tests rely
        # on it) while authoring the drawing at 1200 x 480 for precise placement.
        top_level_items = [item for item in self.scene.items() if item.parentItem() is None]
        self.layout_group = self.scene.createItemGroup(top_level_items)
        self.layout_group.setScale(5 / 6)
        self.scene.setSceneRect(QRectF(0, 0, 1000, 400))
        self._update_pipe("DISCONNECTED")

    def _add_label(
        self,
        text: str,
        x: float,
        y: float,
        width: float,
        *,
        align_left: bool = False,
        color: str = "#10254A",
    ) -> None:
        label = self.scene.addText(text, QFont("DejaVu Sans", 8, QFont.Weight.DemiBold))
        label.setDefaultTextColor(QColor(color))
        label.setTextWidth(width)
        label.document().setDefaultStyleSheet(
            "body { text-align: left; }" if align_left else "body { text-align: center; }"
        )
        label.setPos(x, y)
        label.setZValue(6)

    def _setpoint_edited(self, _value: float) -> None:
        self._confinement_pressure = self.confinement_control.spin.value()
        self._blanket_temperature = self.temperature_control.spin.value()
        self.setpoints_changed.emit(self._confinement_pressure, self._blanket_temperature)

    def set_setpoints(self, confinement_pressure_psi: float, blanket_temperature_c: float) -> None:
        for control, value in (
            (self.confinement_control, confinement_pressure_psi),
            (self.temperature_control, blanket_temperature_c),
        ):
            control.spin.blockSignals(True)
            control.spin.setValue(value)
            control.spin.blockSignals(False)
        self._confinement_pressure = self.confinement_control.spin.value()
        self._blanket_temperature = self.temperature_control.spin.value()

    def set_setpoint_ranges(
        self,
        confinement_range_psi: tuple[float, float],
        temperature_range_c: tuple[float, float],
    ) -> None:
        self.confinement_control.spin.setRange(*confinement_range_psi)
        self.temperature_control.spin.setRange(*temperature_range_c)

    def setpoints(self) -> tuple[float, float]:
        return self._confinement_pressure, self._blanket_temperature

    def set_setpoints_locked(self, locked: bool) -> None:
        self.confinement_control.set_locked(locked)
        self.temperature_control.set_locked(locked)

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
        self._update_instrument("pressure", "PRESSÃO DA LINHA")
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
        elapsed = f" · {self._elapsed}" if self._elapsed != "00:00:00" else ""
        self.instruments["sample"].set_content(
            "ENSAIO / AMOSTRA",
            f"{self._sample_code} · {self._sample_name}",
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
        self._update_instrument("pressure", "PRESSÃO DA LINHA")
        self._update_sample()
        self._update_pipe("DISCONNECTED")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.animation_timer.stop()
        super().closeEvent(event)
