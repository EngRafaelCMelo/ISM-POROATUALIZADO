from __future__ import annotations

from html import escape
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
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

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.key is not None and self.callback is not None:
            self.callback(self.key)
        super().mousePressEvent(event)


class ValueOverlayItem(QGraphicsRectItem):
    """Leitura dinâmica ancorada ao equipamento correspondente."""

    def __init__(self, key: str, title: str, rect: QRectF, callback) -> None:
        super().__init__(QRectF(0, 0, rect.width(), rect.height()))
        self.key = key
        self.callback = callback
        self.setPos(rect.topLeft())
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setBrush(QBrush(QColor("#F8FAFC")))
        self.setPen(QPen(QColor("#64748B"), 2))
        self.setZValue(10)
        self.text = QGraphicsTextItem(self)
        self.text.setDefaultTextColor(QColor("#17212B"))
        self.text.setPos(10, 5)
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
        self._locked = False
        self.setObjectName("manualSetpoint")
        self.setFixedSize(width, 120 if apply_button else 94)
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
        self.heading = heading
        heading.setWordWrap(True)
        heading.setMinimumHeight(28)
        heading.setFont(QFont("DejaVu Sans", 9, QFont.Weight.DemiBold))
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

    def set_title(self, title: str) -> None:
        self.heading.setText(title)

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
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

        holder_x = 436.5
        holder_y = 315.8
        holder_scale = 0.96
        self._equipment_port_map = {
            "filter": {"left": (2, 154), "right": (168, 154)},
            "flow": {"left": (2, 119), "right": (178, 119)},
            "pressure": {"left": (2, 112), "right": (128, 112)},
            "sample": {"inlet": (2, 65), "outlet": (428, 65), "confinement": (174, 23)},
            "pump": {"outlet": (177, 79)},
            "valve": {"left": (2, 82), "right": (98, 82)},
        }

        # Paths start empty and are routed after the fixed equipment positions
        # are created.
        self.pipe = PipeItem(QPainterPath())
        self.scene.addItem(self.pipe)
        self.confinement_pipe = QGraphicsPathItem(QPainterPath())
        self.confinement_pipe.setPen(
            QPen(QColor("#2C8B8C"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        self.confinement_pipe.setZValue(2)
        self.scene.addItem(self.confinement_pipe)
        self.crossing_bridge = QGraphicsPathItem(QPainterPath())
        self.crossing_bridge.setPen(QPen(QColor("#2C8B8C"), 7))
        self.crossing_bridge.setZValue(7)
        self.scene.addItem(self.crossing_bridge)

        self.flow_arrow = self._add_arrow(1165, 168, "left", STATE_COLORS["DISCONNECTED"])
        self.return_arrow = self._add_arrow(1165, 380, "right", STATE_COLORS["DISCONNECTED"])
        self.discharge_arrow = self._add_arrow(458, 235, "right", "#2C8B8C")

        equipment_specs = {
            "filter": ("filter_regulator.svg", "Reguladora", 966, 51, 0.76, None),
            "valve": ("valve.svg", "Válvula de alívio", 226.6, 399.1, 0.62, None),
            "flow": ("flowmeter.svg", "Flowmeter", 714, 88, 0.67, "flow"),
            "pressure": (
                "pressure_transmitter.svg",
                "Transdutor de pressão",
                408.3,
                97.1,
                0.64,
                "pressure",
            ),
            "sample": (
                "sample_holder.svg",
                "Holder com manta térmica",
                holder_x,
                holder_y,
                holder_scale,
                "sample",
            ),
            "pump": ("pump.svg", "Bomba de confinamento", 18.3, 280.3, 0.76, None),
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

        labels = {
            "filter": self._add_label("REGULADORA", 958, 224, 145),
            "valve": self._add_label("VÁLVULA DE\nALÍVIO", 272.5, 403.8, 102),
            "flow": self._add_label("FLOWMETER", 804.3, 122.7, 160),
            "confinement": self._add_label(
                "PRESSÃO DE CONFINAMENTO", 18.9, 265, 190, align_left=True
            ),
            "pressure": self._add_label("TRANSDUTOR\nDE PRESSÃO", 483.5, 107.9, 145),
            "holder": self._add_label("HOLDER", 588.4, 417.7, 120),
            "blanket": self._add_label("MANTA TÉRMICA", 5.8, 85.8, 155, color="#9B3D25"),
            "pump": self._add_label("BOMBA DE CONFINAMENTO", 2, 442, 190),
            "inlet": self._add_label("ENTRADA DO GÁS", 1080, 116, 112, align_left=True),
            "outlet": self._add_label("SAÍDA DO GÁS", 1077, 399, 112, align_left=True),
        }
        self.discharge_label = self._add_label(
            "DESCARGA PARA ATMOSFERA", 320.9, 457, 280, align_left=True
        )

        labels["blanket"].setPos(5.8, 101)
        self.instruments = {
            "flow": ValueOverlayItem(
                "flow", "VAZÃO", QRectF(686.5, 8.9, 220, 78), self.instrument_clicked.emit
            ),
            "pressure": ValueOverlayItem(
                "pressure",
                "PRESSÃO DA LINHA",
                QRectF(395, 10, 220, 78),
                self.instrument_clicked.emit,
            ),
            "sample": ValueOverlayItem(
                "sample",
                "ENSAIO / AMOSTRA",
                QRectF(638.4, 249.3, 280, 92),
                self.instrument_clicked.emit,
            ),
        }
        for name, item in self.instruments.items():
            self.scene.addItem(item)

        self.confinement_control = ManualSetpointWidget(
            "PRESSÃO DE CONFINAMENTO",
            "psi",
            self._confinement_pressure,
            0.0,
            1000.0,
            apply_button=True,
            width=240,
        )
        self.temperature_control = ManualSetpointWidget(
            "SETPOINT DE TEMPERATURA DA MANTA",
            "°C",
            self._blanket_temperature,
            0.0,
            200.0,
            width=215,
        )
        self.confinement_control.set_title("SETPOINT DE PRESSÃO DE CONFINAMENTO")
        self.confinement_proxy = QGraphicsProxyWidget()
        self.confinement_proxy.setWidget(self.confinement_control)
        self.confinement_proxy.setPos(3.2, 140)
        self.confinement_proxy.setZValue(12)
        self.scene.addItem(self.confinement_proxy)
        self.temperature_proxy = QGraphicsProxyWidget()
        self.temperature_proxy.setWidget(self.temperature_control)
        self.temperature_proxy.setPos(4.2, 7.7)
        self.temperature_proxy.setZValue(12)
        self.scene.addItem(self.temperature_proxy)
        self.confinement_control.value_changed.connect(self._setpoint_edited)
        self.temperature_control.value_changed.connect(self._setpoint_edited)

        self.guides = QGraphicsPathItem(QPainterPath())
        self.guides.setPen(QPen(QColor("#9FB2C8"), 2, Qt.PenStyle.DashLine))
        self.guides.setZValue(5)
        self.scene.addItem(self.guides)

        # Use one coordinate system for authoring and rendering. Scaling the
        # whole scene after positioning introduced gaps between pipes and SVG
        # connectors and made labels too small at common desktop resolutions.
        self.scene.setSceneRect(scene_rect)
        self._rebuild_connections()
        self._update_pipe("DISCONNECTED")

    def _equipment_port(self, equipment: str, port: str) -> QPointF:
        local = self._equipment_port_map[equipment][port]
        return self.equipment_items[equipment].mapToScene(QPointF(*local))

    @staticmethod
    def _orthogonal_connection(path: QPainterPath, start: QPointF, end: QPointF) -> None:
        middle_x = (start.x() + end.x()) / 2
        path.lineTo(middle_x, start.y())
        path.lineTo(middle_x, end.y())
        path.lineTo(end)

    def _set_arrow_path(self, arrow: QGraphicsPathItem, x: float, y: float, direction: str) -> None:
        path = QPainterPath()
        if direction == "left":
            path.moveTo(x - 14, y)
            path.lineTo(x + 8, y - 12)
            path.lineTo(x + 8, y + 12)
        else:
            path.moveTo(x + 14, y)
            path.lineTo(x - 8, y - 12)
            path.lineTo(x - 8, y + 12)
        path.closeSubpath()
        arrow.setPath(path)

    def _add_arrow(self, x: float, y: float, direction: str, color: str) -> QGraphicsPathItem:
        path = QPainterPath()
        arrow = QGraphicsPathItem(path)
        self._set_arrow_path(arrow, x, y, direction)
        arrow.setPen(QPen(QColor(color), 1))
        arrow.setBrush(QBrush(QColor(color)))
        arrow.setZValue(8)
        self.scene.addItem(arrow)
        return arrow

    def _rebuild_connections(self) -> None:
        filter_right = self._equipment_port("filter", "right")
        filter_left = self._equipment_port("filter", "left")
        flow_right = self._equipment_port("flow", "right")
        flow_left = self._equipment_port("flow", "left")
        pressure_right = self._equipment_port("pressure", "right")
        pressure_left = self._equipment_port("pressure", "left")
        holder_inlet = self._equipment_port("sample", "inlet")
        holder_outlet = self._equipment_port("sample", "outlet")
        holder_confinement = self._equipment_port("sample", "confinement")
        self.holder_ports = {
            "inlet": (holder_inlet.x(), holder_inlet.y()),
            "outlet": (holder_outlet.x(), holder_outlet.y()),
            "confinement": (holder_confinement.x(), holder_confinement.y()),
        }

        process_path = QPainterPath(QPointF(1190, filter_right.y()))
        process_path.lineTo(filter_right)
        process_path.lineTo(filter_left)
        self._orthogonal_connection(process_path, filter_left, flow_right)
        process_path.lineTo(flow_left)
        self._orthogonal_connection(process_path, flow_left, pressure_right)
        process_path.lineTo(pressure_left)
        process_drop_x = holder_inlet.x() - 72
        process_path.lineTo(process_drop_x, pressure_left.y())
        process_path.lineTo(process_drop_x, holder_inlet.y())
        process_path.lineTo(holder_inlet)
        process_path.moveTo(holder_outlet)
        process_path.lineTo(1190, holder_outlet.y())
        self.pipe.setPath(process_path)

        pump_outlet = self._equipment_port("pump", "outlet")
        valve_left = self._equipment_port("valve", "left")
        valve_right = self._equipment_port("valve", "right")
        tee_x = valve_left.x()
        bridge_start = process_drop_x - 14
        bridge_end = process_drop_x + 14
        discharge_end_x = valve_right.x() + 137

        confinement_path = QPainterPath(pump_outlet)
        confinement_path.lineTo(bridge_start, pump_outlet.y())
        confinement_path.cubicTo(
            bridge_start,
            pump_outlet.y() - 19,
            bridge_end,
            pump_outlet.y() - 19,
            bridge_end,
            pump_outlet.y(),
        )
        confinement_path.lineTo(holder_confinement.x(), pump_outlet.y())
        confinement_path.lineTo(holder_confinement)
        confinement_path.moveTo(tee_x, pump_outlet.y())
        confinement_path.lineTo(valve_left)
        confinement_path.moveTo(valve_right)
        confinement_path.lineTo(discharge_end_x, valve_right.y())
        self.confinement_pipe.setPath(confinement_path)

        bridge = QPainterPath(QPointF(bridge_start, pump_outlet.y()))
        bridge.cubicTo(
            bridge_start,
            pump_outlet.y() - 19,
            bridge_end,
            pump_outlet.y() - 19,
            bridge_end,
            pump_outlet.y(),
        )
        self.crossing_bridge.setPath(bridge)
        self._set_arrow_path(self.flow_arrow, 1165, filter_right.y(), "left")
        self._set_arrow_path(self.return_arrow, 1165, holder_outlet.y(), "right")
        self._set_arrow_path(self.discharge_arrow, discharge_end_x - 12, valve_right.y(), "right")

        guides = QPainterPath()
        for key, equipment in (("pressure", "pressure"), ("flow", "flow"), ("sample", "sample")):
            card_bounds = self.instruments[key].sceneBoundingRect()
            equipment_bounds = self.equipment_items[equipment].sceneBoundingRect()
            start = QPointF(card_bounds.center().x(), card_bounds.bottom())
            end = QPointF(equipment_bounds.center().x(), equipment_bounds.top())
            guides.moveTo(start)
            guides.lineTo(end)
        self.guides.setPath(guides)

    def _add_note_card(self, text: str, rect: QRectF, color: str) -> QGraphicsRectItem:
        card = QGraphicsRectItem(QRectF(0, 0, rect.width(), rect.height()))
        card.setPos(rect.x(), rect.y())
        card.setBrush(QBrush(QColor("#FFF9E8")))
        card.setPen(QPen(QColor(color), 1.5))
        card.setZValue(6)
        self.scene.addItem(card)
        label = QGraphicsTextItem(card)
        label.setDefaultTextColor(QColor("#5C4300"))
        label.setFont(QFont("DejaVu Sans", 8, QFont.Weight.DemiBold))
        label.setPlainText(text)
        label.setPos(8, 5)
        label.setTextWidth(rect.width() - 16)
        label.setZValue(7)
        card.note_label = label
        return card

    def _add_label(
        self,
        text: str,
        x: float,
        y: float,
        width: float,
        *,
        align_left: bool = False,
        color: str = "#10254A",
    ) -> QGraphicsTextItem:
        label = self.scene.addText(text, QFont("DejaVu Sans", 8, QFont.Weight.DemiBold))
        label.setDefaultTextColor(QColor(color))
        label.setTextWidth(width)
        label.document().setDefaultStyleSheet(
            "body { text-align: left; }" if align_left else "body { text-align: center; }"
        )
        label.setPos(x, y)
        label.setZValue(6)
        return label

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
        color = QColor(pipe_colors.get(state, pipe_colors["DISCONNECTED"]))
        for arrow in (self.flow_arrow, self.return_arrow):
            arrow.setPen(QPen(color, 1))
            arrow.setBrush(QBrush(color))

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
