from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from statistics import mean
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QDate, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.calculations import calculate_statistics
from core.calibration import fit_calibration
from core.constants import ReadingQuality
from core.models import Alarm, Measurement, SensorReading, TestSession
from ui.resources import branding_path
from ui.theme import COLORS, icon_path
from ui.widgets.process_synoptic import ProcessSynoptic
from ui.widgets.sensor_card import SensorCard

logger = logging.getLogger(__name__)


def card_frame() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(15, 13, 15, 13)
    return frame, layout


def page_header(title: str, subtitle: str = "") -> QVBoxLayout:
    layout = QVBoxLayout()
    label = QLabel(title)
    label.setObjectName("pageTitle")
    layout.addWidget(label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        layout.addWidget(sub)
    return layout


class OverviewPage(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    finish_requested = Signal()
    marker_requested = Signal()
    acknowledge_requested = Signal(int)

    def __init__(self, sensor_config: dict[str, dict[str, Any]]):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.addLayout(page_header("Visão geral", "Leituras instantâneas e estado do ensaio"))
        self.simulation_banner = QLabel("MODO SIMULAÇÃO — dados não provenientes do equipamento")
        self.simulation_banner.setObjectName("simulationBanner")
        self.simulation_banner.hide()
        outer.addWidget(self.simulation_banner)

        # Mantidos como adaptadores compatíveis para telas/testes existentes; o
        # valor operacional visível agora fica ancorado no próprio instrumento.
        self.cards: dict[str, SensorCard] = {}
        for key in ("pressao", "vazao"):
            cfg = sensor_config[key]
            card = SensorCard(
                cfg["nome"],
                cfg["unidade"],
                float(cfg.get("limite_inferior") or 0),
                float(cfg.get("limite_superior") or 100),
                int(cfg.get("casas", 2)),
            )
            self.cards[key] = card

        lower = QHBoxLayout()
        synoptic_card, synoptic_layout = card_frame()
        synoptic_header = QHBoxLayout()
        title = QLabel("Processo · caminho do gás")
        title.setObjectName("sectionTitle")
        hint = QLabel("Passe o mouse ou clique nos instrumentos para detalhes")
        hint.setObjectName("muted")
        synoptic_header.addWidget(title)
        synoptic_header.addStretch()
        synoptic_header.addWidget(hint)
        synoptic_layout.addLayout(synoptic_header)
        self.synoptic = ProcessSynoptic()
        synoptic_layout.addWidget(self.synoptic, 1)
        lower.addWidget(synoptic_card, 4)

        status_card, status_layout = card_frame()
        status_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        status_title = QLabel("Ensaio")
        status_title.setObjectName("sectionTitle")
        status_layout.addWidget(status_title)
        stats = QGridLayout()
        stats.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.duration = QLabel("00:00:00")
        self.samples = QLabel("0")
        self.rate = QLabel("— Hz")
        self.recording = QLabel("Aguardando")
        self.active_flow = QLabel("Flow meter único")
        self.valid_count = QLabel("0")
        self.invalid_count = QLabel("0")
        for i, (label, value) in enumerate(
            [
                ("Duração", self.duration),
                ("Amostras", self.samples),
                ("Taxa real", self.rate),
                ("Registro", self.recording),
                ("Sensor de vazão", self.active_flow),
                ("Leituras válidas", self.valid_count),
                ("Leituras inválidas", self.invalid_count),
            ]
        ):
            name = QLabel(label)
            name.setObjectName("muted")
            row, group = divmod(i, 2)
            stats.addWidget(name, row * 2, group * 2)
            stats.addWidget(value, row * 2 + 1, group * 2)
            stats.setColumnStretch(group * 2, 1)
        status_layout.addLayout(stats)
        self.start_button = QPushButton("Iniciar ensaio")
        self.start_button.setObjectName("primary")
        self.pause_button = QPushButton("Pausar")
        self.finish_button = QPushButton("Finalizar ensaio")
        self.finish_button.setObjectName("danger")
        self.marker_button = QPushButton("Adicionar marcação")
        self.start_button.setIcon(QIcon(icon_path("new_test")))
        self.pause_button.setIcon(QIcon(icon_path("pause")))
        self.finish_button.setIcon(QIcon(icon_path("finish")))
        self.marker_button.setIcon(QIcon(icon_path("marker")))
        for button in (
            self.start_button,
            self.pause_button,
            self.finish_button,
            self.marker_button,
        ):
            button.setIconSize(QSize(17, 17))
        self.start_button.clicked.connect(self.start_requested)
        self.pause_button.clicked.connect(self.pause_requested)
        self.finish_button.clicked.connect(self.finish_requested)
        self.marker_button.clicked.connect(self.marker_requested)
        actions = QGridLayout()
        actions.addWidget(self.start_button, 0, 0)
        actions.addWidget(self.pause_button, 0, 1)
        actions.addWidget(self.marker_button, 1, 0)
        actions.addWidget(self.finish_button, 1, 1)
        status_layout.addLayout(actions)
        self.set_test_active(False)
        lower.addWidget(status_card, 1)
        outer.addLayout(lower)

        alarms_card, alarms_layout = card_frame()
        alarm_head = QHBoxLayout()
        alarm_title = QLabel("Alarmes ativos")
        alarm_title.setObjectName("sectionTitle")
        self.ack_button = QPushButton("Reconhecer selecionado")
        self.ack_button.clicked.connect(self._ack_selected)
        alarm_head.addWidget(alarm_title)
        alarm_head.addStretch()
        alarm_head.addWidget(self.ack_button)
        alarms_layout.addLayout(alarm_head)
        self.alarm_table = QTableWidget(0, 5)
        self.alarm_table.setHorizontalHeaderLabels(
            ["ID", "Horário", "Sensor", "Severidade", "Mensagem"]
        )
        self.alarm_table.setColumnHidden(0, True)
        self.alarm_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.alarm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.alarm_table.setMaximumHeight(145)
        alarms_layout.addWidget(self.alarm_table)
        outer.addWidget(alarms_card)

        self._pressure_times: deque[float] = deque(maxlen=60)
        self._flow_times: deque[float] = deque(maxlen=60)
        self._pressure: deque[float] = deque(maxlen=60)
        self._flow: deque[float] = deque(maxlen=60)
        self._first_time: datetime | None = None
        self._report_ready = False

    def update_measurement(self, measurement: Measurement) -> None:
        self.simulation_banner.setVisible(measurement.simulated)
        self.update_pressure(measurement.pressure)
        self.update_flow(measurement.flow)

    def update_pressure(self, reading: SensorReading) -> None:
        self.cards["pressao"].update_reading(reading)
        self.synoptic.update_pressure(reading)
        timestamp = reading.timestamp or datetime.now()
        if self._first_time is None:
            self._first_time = timestamp
        self._pressure_times.append((timestamp - self._first_time).total_seconds())
        self._pressure.append(float("nan") if reading.value is None else reading.value)

    def update_flow(self, reading: SensorReading) -> None:
        self.cards["vazao"].update_reading(
            reading,
            unavailable_message="Sem comunicação com flowmeter"
            if reading.quality == ReadingQuality.DISCONNECTED
            else None,
        )
        self.synoptic.update_flow(reading)
        timestamp = reading.timestamp
        if timestamp is None:
            return
        if self._first_time is None:
            self._first_time = timestamp
        self._flow_times.append((timestamp - self._first_time).total_seconds())
        self._flow.append(float("nan") if reading.value is None else reading.value)

    def set_test_active(self, active: bool, paused: bool = False) -> None:
        self.start_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
        self.finish_button.setEnabled(active)
        self.marker_button.setEnabled(active)
        self.pause_button.setText("Retomar" if paused else "Pausar")
        self.recording.setText("Pausado" if paused else "Gravando" if active else "Aguardando")
        self.synoptic.set_test_state(
            "PAUSADO" if paused else "EM EXECUÇÃO" if active else "AGUARDANDO"
        )
        if not active:
            self.duration.setText("00:00:00")

    def reset_test(self) -> None:
        for card in self.cards.values():
            card.reset_statistics()
        self.samples.setText("0")
        self._report_ready = False
        self.set_test_active(False)
        self.synoptic.reset()

    def set_report_ready(self, ready: bool) -> None:
        self._report_ready = ready

    def clear_visualization(self) -> None:
        self._pressure_times.clear()
        self._flow_times.clear()
        self._pressure.clear()
        self._flow.clear()
        self._first_time = None

    def add_alarm(self, alarm_id: int, alarm: Alarm) -> None:
        row = self.alarm_table.rowCount()
        self.alarm_table.insertRow(row)
        for col, text in enumerate(
            [
                str(alarm_id),
                alarm.timestamp.strftime("%H:%M:%S"),
                alarm.sensor,
                alarm.severity.value,
                alarm.message,
            ]
        ):
            item = QTableWidgetItem(text)
            if alarm.severity.value in ("alarme", "crítico"):
                item.setForeground(QColor(COLORS["error"]))
            self.alarm_table.setItem(row, col, item)

    def _ack_selected(self) -> None:
        row = self.alarm_table.currentRow()
        if row >= 0:
            self.acknowledge_requested.emit(int(self.alarm_table.item(row, 0).text()))
            self.alarm_table.removeRow(row)


class GraphsPage(QWidget):
    export_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.pressure_unit = "psi"
        self.flow_unit = "NL/min"
        self._first: datetime | None = None
        self._historical_test_id: int | None = None
        self._initialize_data()

        layout = QVBoxLayout(self)
        layout.addLayout(
            page_header(
                "Gráficos", "Processo e permeabilidade; zoom, pan e restauração disponíveis"
            )
        )
        toolbar = QHBoxLayout()
        self.window_combo = QComboBox()
        self.window_combo.addItems(["Últimos 60 s", "Últimos 5 min", "Todo o ensaio"])
        self.visual_pause = QCheckBox("Pausar visualização")
        self.auto_zoom = QCheckBox("Zoom automático")
        self.auto_zoom.setChecked(True)
        self.export_graph_combo = QComboBox()
        for title, group, index in (
            ("Pressão × tempo", "process", 0),
            ("Vazão × tempo", "process", 1),
            ("Pressão e vazão × tempo", "process", 2),
            ("Corrente do transdutor", "process", 3),
            ("Vazão × pressão", "process", 4),
            ("Qualidade da aquisição", "process", 5),
            ("Permeabilidade × tempo", "permeability", 0),
            ("Permeabilidade × pressão", "permeability", 1),
            ("Klinkenberg", "permeability", 2),
        ):
            self.export_graph_combo.addItem(title, (group, index))
        restore = QPushButton("Restaurar enquadramento")
        restore.clicked.connect(self.restore_view)
        export_current = QPushButton("Exportar gráfico")
        export_current.clicked.connect(lambda: self.export_requested.emit("individual"))
        export_all = QPushButton("Exportar todos")
        export_all.clicked.connect(lambda: self.export_requested.emit("all"))
        for widget in (
            QLabel("Janela:"),
            self.window_combo,
            self.visual_pause,
            self.auto_zoom,
            restore,
        ):
            toolbar.addWidget(widget)
        toolbar.addStretch()
        toolbar.addWidget(self.export_graph_combo)
        toolbar.addWidget(export_current)
        toolbar.addWidget(export_all)
        layout.addLayout(toolbar)

        self.tabs = QTabWidget()
        self.process_page = QWidget()
        process_layout = QVBoxLayout(self.process_page)
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground("w")
        process_layout.addWidget(self.graphics)
        self.tabs.addTab(self.process_page, "Processo")

        self.permeability_page = QWidget()
        permeability_layout = QVBoxLayout(self.permeability_page)
        self.permeability_message = QLabel(
            "Nenhum cálculo de permeabilidade salvo para este ensaio."
        )
        self.permeability_message.setObjectName("muted")
        self.permeability_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        permeability_layout.addWidget(self.permeability_message)
        self.permeability_graphics = pg.GraphicsLayoutWidget()
        self.permeability_graphics.setBackground("w")
        permeability_layout.addWidget(self.permeability_graphics, 1)
        self.tabs.addTab(self.permeability_page, "Permeabilidade")
        layout.addWidget(self.tabs)
        self._build_process_plots()
        self._build_permeability_plots()
        self.window_combo.currentIndexChanged.connect(self.refresh)
        self.visual_pause.toggled.connect(lambda paused: None if paused else self.refresh())
        self.auto_zoom.toggled.connect(self._set_auto_zoom)

    def _initialize_data(self):
        for name in (
            "pressure_times",
            "flow_times",
            "pressure",
            "flow",
            "ma_p",
            "flow_pressure_x",
            "flow_pressure_y",
            "quality_times",
            "pressure_quality",
            "flow_quality",
            "permeability_times",
            "permeability_values",
            "permeability_pressures",
            "permeability_pressure_values",
            "klinkenberg_x",
            "klinkenberg_y",
        ):
            setattr(self, name, [])
        self.klinkenberg_fit_x: list[float] = []
        self.klinkenberg_fit_y: list[float] = []

    def _build_process_plots(self):
        titles = [
            "Pressão × tempo",
            "Vazão × tempo",
            "Pressão e vazão × tempo",
            "Corrente do transdutor",
            "Vazão × pressão",
            "Qualidade da aquisição",
        ]
        self.plots: list[pg.PlotItem] = []
        for index, title in enumerate(titles):
            plot = self.graphics.addPlot(row=index // 2, col=index % 2, title=title)
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.addLegend(offset=(5, 5))
            plot.setClipToView(True)
            self.plots.append(plot)
        self.plots[0].setLabel("left", "Pressão", units=self.pressure_unit)
        self.plots[1].setLabel("left", "Vazão", units=self.flow_unit)
        self.plots[2].setLabel(
            "left", "Pressão", units=self.pressure_unit, color=COLORS["pressure"]
        )
        self.plots[4].setLabel("bottom", "Pressão", units=self.pressure_unit)
        self.plots[4].setLabel("left", "Vazão", units=self.flow_unit)
        self.plots[5].setLabel("left", "Qualidade (3=OK, 2=WARNING, 1=STALE, 0=INV./DESC.)")
        self.curves = {
            "pressure": self.plots[0].plot(
                pen=pg.mkPen(COLORS["pressure"], width=2), name="Pressão"
            ),
            "flow": self.plots[1].plot(pen=pg.mkPen(COLORS["flow"], width=2), name="Vazão"),
            "combined_p": self.plots[2].plot(
                pen=pg.mkPen(COLORS["pressure"], width=2), name="Pressão"
            ),
            "ma_p": self.plots[3].plot(pen=pg.mkPen(COLORS["pressure"]), name="Pressão"),
            "flow_pressure": self.plots[4].plot(
                pen=pg.mkPen(COLORS["accent"], width=2),
                symbol="o",
                symbolSize=3,
                name="Pares sincronizados",
            ),
            "quality_p": self.plots[5].plot(
                pen=pg.mkPen(COLORS["pressure"], width=2), name="Pressão"
            ),
            "quality_f": self.plots[5].plot(pen=pg.mkPen(COLORS["flow"], width=2), name="Vazão"),
        }
        # Eixo Y direito independente para vazão no gráfico combinado.
        self.combined_flow_view = pg.ViewBox()
        self.plots[2].showAxis("right")
        self.plots[2].scene().addItem(self.combined_flow_view)
        self.plots[2].getAxis("right").linkToView(self.combined_flow_view)
        self.combined_flow_view.setXLink(self.plots[2])
        self.plots[2].getAxis("right").setLabel("Vazão", units=self.flow_unit, color=COLORS["flow"])
        self.combined_flow_curve = pg.PlotCurveItem(
            pen=pg.mkPen(COLORS["flow"], width=2), name="Vazão"
        )
        self.combined_flow_view.addItem(self.combined_flow_curve)
        self.plots[2].legend.addItem(self.combined_flow_curve, "Vazão")
        self.plots[2].vb.sigResized.connect(self._update_combined_view)
        self._update_combined_view()
        self.cursor_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(COLORS["inactive"]))
        self.plots[0].addItem(self.cursor_v, ignoreBounds=True)
        self.plots[0].scene().sigMouseMoved.connect(self._mouse_moved)
        self.plots[5].setYRange(-0.2, 3.2)

    def _build_permeability_plots(self):
        titles = [
            "Permeabilidade aparente × tempo",
            "Permeabilidade aparente × pressão média absoluta",
            "Klinkenberg: permeabilidade × 1/Pm",
        ]
        self.permeability_plots = []
        for index, title in enumerate(titles):
            plot = self.permeability_graphics.addPlot(row=index, col=0, title=title)
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.addLegend(offset=(5, 5))
            self.permeability_plots.append(plot)
        self.permeability_plots[0].setLabel("left", "Permeabilidade aparente", units="mD")
        self.permeability_plots[1].setLabel("bottom", "Pressão média absoluta", units="kPa abs")
        self.permeability_plots[1].setLabel("left", "Permeabilidade aparente", units="mD")
        self.permeability_plots[2].setLabel("bottom", "1/Pm", units="1/kPa")
        self.permeability_plots[2].setLabel("left", "Permeabilidade aparente", units="mD")
        self.permeability_curves = {
            "time": self.permeability_plots[0].plot(
                pen=pg.mkPen(COLORS["accent"], width=2), symbol="o", name="k aparente"
            ),
            "pressure": self.permeability_plots[1].plot(
                pen=pg.mkPen(COLORS["accent"], width=2), symbol="o", name="k aparente"
            ),
            "points": self.permeability_plots[2].plot(
                pen=None, symbol="o", symbolBrush=COLORS["pressure"], name="Pontos experimentais"
            ),
            "fit": self.permeability_plots[2].plot(
                pen=pg.mkPen(COLORS["flow"], width=2), name="Reta ajustada"
            ),
        }

    def set_units(self, pressure_unit: str, flow_unit: str) -> None:
        self.pressure_unit = pressure_unit or "não disponível"
        self.flow_unit = flow_unit or "não disponível"
        self.plots[0].setTitle(f"Pressão × tempo ({self.pressure_unit})")
        self.plots[1].setTitle(f"Vazão × tempo ({self.flow_unit})")
        self.plots[2].setTitle(f"Pressão ({self.pressure_unit}) e vazão ({self.flow_unit}) × tempo")
        self.plots[4].setTitle(f"Vazão ({self.flow_unit}) × pressão ({self.pressure_unit})")
        self.plots[0].setLabel("left", "Pressão", units=self.pressure_unit)
        self.plots[1].setLabel("left", "Vazão", units=self.flow_unit)
        self.plots[2].setLabel(
            "left", "Pressão", units=self.pressure_unit, color=COLORS["pressure"]
        )
        self.plots[2].getAxis("right").setLabel("Vazão", units=self.flow_unit, color=COLORS["flow"])
        self.plots[4].setLabel("bottom", "Pressão", units=self.pressure_unit)
        self.plots[4].setLabel("left", "Vazão", units=self.flow_unit)
        self.plots[0].setToolTip(f"Pressão em {self.pressure_unit}")
        self.plots[1].setToolTip(f"Vazão em {self.flow_unit}")
        self.plots[2].setToolTip(f"Pressão em {self.pressure_unit}; vazão em {self.flow_unit}")
        self.plots[4].setToolTip(
            f"Pares sincronizados: pressão em {self.pressure_unit}; vazão em {self.flow_unit}"
        )
        self.export_graph_combo.setItemText(0, f"Pressão × tempo ({self.pressure_unit})")
        self.export_graph_combo.setItemText(1, f"Vazão × tempo ({self.flow_unit})")
        self.export_graph_combo.setItemText(
            2, f"Pressão ({self.pressure_unit}) e vazão ({self.flow_unit})"
        )
        self.export_graph_combo.setItemText(
            4, f"Vazão ({self.flow_unit}) × pressão ({self.pressure_unit})"
        )
        for plot, labels in (
            (self.plots[0], [f"Pressão ({self.pressure_unit})"]),
            (self.plots[1], [f"Vazão ({self.flow_unit})"]),
            (
                self.plots[2],
                [f"Pressão ({self.pressure_unit})", f"Vazão ({self.flow_unit})"],
            ),
        ):
            for (_, label), text in zip(plot.legend.items, labels):
                label.setText(text)

    @staticmethod
    def _quality_value(reading: SensorReading) -> int:
        return {
            ReadingQuality.VALID: 3,
            ReadingQuality.SIMULATED: 3,
            ReadingQuality.WARNING: 2,
            ReadingQuality.STALE: 1,
        }.get(reading.quality, 0)

    def add_measurement(self, measurement: Measurement) -> None:
        self.add_combined_measurement(measurement)

    def add_pressure(self, reading: SensorReading) -> None:
        timestamp = reading.timestamp or datetime.now()
        if self._first is None:
            self._first = timestamp
        self.pressure_times.append((timestamp - self._first).total_seconds())
        self.pressure.append(reading.value if reading.valid else float("nan"))
        self.ma_p.append(
            reading.current_ma if reading.valid and reading.current_ma is not None else float("nan")
        )
        if not self.visual_pause.isChecked():
            self.refresh()

    def add_flow(self, reading: SensorReading) -> None:
        if reading.timestamp is None:
            return
        if self._first is None:
            self._first = reading.timestamp
        self.flow_times.append((reading.timestamp - self._first).total_seconds())
        self.flow.append(reading.value if reading.valid else float("nan"))
        if not self.visual_pause.isChecked():
            self.refresh()

    def add_combined_measurement(self, measurement: Measurement) -> None:
        timestamp = measurement.received_at
        if self._first is None:
            self._first = timestamp
        elapsed = (timestamp - self._first).total_seconds()
        self.quality_times.append(elapsed)
        self.pressure_quality.append(self._quality_value(measurement.pressure))
        self.flow_quality.append(self._quality_value(measurement.flow))
        if (
            measurement.communication_state.upper() == "OK"
            and measurement.pressure.valid
            and measurement.flow.valid
        ):
            self.flow_pressure_x.append(float(measurement.pressure.value))
            self.flow_pressure_y.append(float(measurement.flow.value))
        if not self.visual_pause.isChecked():
            self.refresh()

    def refresh(self) -> None:
        window = [60, 300, None][self.window_combo.currentIndex()]

        def selected(times, values):
            start = 0
            if window is not None and times:
                threshold = times[-1] - window
                start = next((i for i, x in enumerate(times) if x >= threshold), 0)
            step = max(1, (len(times) - start) // 3000)
            return times[start::step], values[start::step]

        px, pressure = selected(self.pressure_times, self.pressure)
        _, current = selected(self.pressure_times, self.ma_p)
        fx, flow = selected(self.flow_times, self.flow)
        qx, pq = selected(self.quality_times, self.pressure_quality)
        _, fq = selected(self.quality_times, self.flow_quality)
        self.curves["pressure"].setData(px, pressure)
        self.curves["combined_p"].setData(px, pressure)
        self.curves["ma_p"].setData(px, current)
        self.curves["flow"].setData(fx, flow)
        self.combined_flow_curve.setData(fx, flow)
        self.curves["flow_pressure"].setData(
            self.flow_pressure_x[-3000:], self.flow_pressure_y[-3000:]
        )
        self.curves["quality_p"].setData(qx, pq)
        self.curves["quality_f"].setData(qx, fq)
        if self.auto_zoom.isChecked():
            self.restore_view()

    def load_calculations(self, rows) -> None:
        from services.chart_service import ChartService

        for values in (
            self.permeability_times,
            self.permeability_values,
            self.permeability_pressures,
            self.permeability_pressure_values,
            self.klinkenberg_x,
            self.klinkenberg_y,
            self.klinkenberg_fit_x,
            self.klinkenberg_fit_y,
        ):
            values.clear()
        records = ChartService.calculation_records(rows)
        first_time = None
        for record in records:
            result = record["results"]
            value = result.get("permeability_md")
            pressure = result.get("mean_pressure_kpa_abs")
            try:
                timestamp = (
                    datetime.fromisoformat(record["timestamp"]) if record.get("timestamp") else None
                )
            except (TypeError, ValueError):
                timestamp = None
                logger.warning("Timestamp de cálculo legado inválido: %r", record.get("timestamp"))
            if ChartService._finite_positive(value) and timestamp:
                first_time = first_time or timestamp
                self.permeability_times.append((timestamp - first_time).total_seconds())
                self.permeability_values.append(float(value))
                if ChartService._finite_positive(pressure):
                    self.permeability_pressures.append(float(pressure))
                    self.permeability_pressure_values.append(float(value))
            if str(record.get("tipo", "")).lower() == "klinkenberg":
                parsed = ChartService.klinkenberg_points(record)
                if len(parsed) < 2:
                    logger.warning(
                        "Registro Klinkenberg ignorado: menos de dois pontos válidos (id=%r)",
                        record.get("id"),
                    )
                    continue
                self.klinkenberg_x = [x for x, _ in parsed]
                self.klinkenberg_y = [y for _, y in parsed]
                slope = result.get("slope_md_kpa")
                intercept = result.get("intrinsic_permeability_md")
                if (
                    len(parsed) >= 2
                    and ChartService._finite(intercept)
                    and ChartService._finite(slope)
                ):
                    self.klinkenberg_fit_x = [min(self.klinkenberg_x), max(self.klinkenberg_x)]
                    self.klinkenberg_fit_y = [
                        float(intercept) + float(slope) * x for x in self.klinkenberg_fit_x
                    ]
                    details = f"Klinkenberg · k∞={float(intercept):.5g} mD"
                    if ChartService._finite(result.get("slip_factor_kpa")):
                        details += f" · b={float(result['slip_factor_kpa']):.5g} kPa"
                    if ChartService._finite(result.get("r_squared")):
                        details += f" · R²={float(result['r_squared']):.4f}"
                    self.permeability_plots[2].setTitle(details)
        self.permeability_curves["time"].setData(self.permeability_times, self.permeability_values)
        self.permeability_curves["pressure"].setData(
            self.permeability_pressures, self.permeability_pressure_values
        )
        self.permeability_curves["points"].setData(self.klinkenberg_x, self.klinkenberg_y)
        self.permeability_curves["fit"].setData(self.klinkenberg_fit_x, self.klinkenberg_fit_y)
        plotted = bool(self.permeability_values or self.klinkenberg_x)
        self.permeability_message.setText(
            "Nenhum cálculo com dados válidos foi encontrado para este ensaio."
        )
        self.permeability_message.setVisible(not plotted)

    def load_history(
        self, test_id: int, measurements, calculations, pressure_unit: str, flow_unit: str
    ) -> None:
        self.reset()
        self._historical_test_id = test_id
        self.set_units(pressure_unit, flow_unit)
        was_paused = self.visual_pause.isChecked()
        self.visual_pause.setChecked(True)
        for raw in measurements:
            row = dict(raw)
            timestamp = datetime.fromisoformat(row["timestamp_computador"])
            pressure_ts = (
                datetime.fromisoformat(row["timestamp_pressao"])
                if row.get("timestamp_pressao")
                else timestamp
            )
            flow_ts = (
                datetime.fromisoformat(row["timestamp_vazao"])
                if row.get("timestamp_vazao")
                else timestamp
            )

            def quality(valid, status):
                upper = str(status or "").upper()
                if "DISCONNECTED" in upper:
                    return ReadingQuality.DISCONNECTED
                if "STALE" in upper:
                    return ReadingQuality.STALE
                return ReadingQuality.VALID if valid else ReadingQuality.INVALID

            measurement = Measurement(
                timestamp,
                pressure=SensorReading(
                    value=row.get("pressao"),
                    current_ma=row.get("pressao_ma"),
                    quality=quality(row.get("pressao_valida"), row.get("status_pressao")),
                    timestamp=pressure_ts,
                    unit=pressure_unit,
                ),
                flow=SensorReading(
                    value=row.get("vazao"),
                    quality=quality(row.get("vazao_valida"), row.get("status_vazao")),
                    timestamp=flow_ts,
                    unit=flow_unit,
                ),
                communication_state=row.get("estado_comunicacao") or "INVALID",
            )
            self.add_pressure(measurement.pressure)
            self.add_flow(measurement.flow)
            self.add_combined_measurement(measurement)
        self.load_calculations(calculations)
        self.visual_pause.setChecked(was_paused)
        self.refresh()

    def reset(self) -> None:
        self._historical_test_id = None
        self._first = None
        self._initialize_data()
        if hasattr(self, "curves"):
            for curve in self.curves.values():
                curve.clear()
            self.combined_flow_curve.clear()
            for curve in self.permeability_curves.values():
                curve.clear()
            self.permeability_plots[2].setTitle("Klinkenberg: permeabilidade × 1/Pm")
            self.permeability_message.show()

    def _set_auto_zoom(self, enabled: bool) -> None:
        if enabled:
            self.restore_view()
            return
        for plot in [*self.plots, *self.permeability_plots]:
            plot.disableAutoRange()
        self.combined_flow_view.disableAutoRange()

    def restore_view(self) -> None:
        for plot in [*self.plots, *self.permeability_plots]:
            plot.enableAutoRange()
        self.combined_flow_view.enableAutoRange()

    def export_items(self, mode: str = "all"):
        process = [(f"processo_{index + 1}", plot) for index, plot in enumerate(self.plots)]
        permeability = [
            (f"permeabilidade_{index + 1}", plot)
            for index, plot in enumerate(self.permeability_plots)
        ]
        if mode == "all":
            return process + permeability
        group, index = self.export_graph_combo.currentData()
        return [process[index] if group == "process" else permeability[index]]

    def _update_combined_view(self):
        self.combined_flow_view.setGeometry(self.plots[2].vb.sceneBoundingRect())
        self.combined_flow_view.linkedViewChanged(self.plots[2].vb, self.combined_flow_view.XAxis)

    def _mouse_moved(self, pos) -> None:
        if self.plots[0].sceneBoundingRect().contains(pos):
            self.cursor_v.setPos(self.plots[0].vb.mapSceneToView(pos).x())


class TestPage(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    finish_requested = Signal()
    marker_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addLayout(
            page_header("Ensaio", "Identificação, controle e estatísticas do ensaio atual")
        )
        info, info_layout = card_frame()
        grid = QGridLayout()
        self.labels: dict[str, QLabel] = {}
        for index, (key, title) in enumerate(
            [
                ("code", "Código"),
                ("sample", "Amostra"),
                ("operator", "Operador"),
                ("start", "Início"),
                ("status", "Status"),
                ("duration", "Duração"),
            ]
        ):
            name = QLabel(title)
            name.setObjectName("muted")
            value = QLabel("—")
            self.labels[key] = value
            row, col = divmod(index, 3)
            grid.addWidget(name, row * 2, col)
            grid.addWidget(value, row * 2 + 1, col)
        info_layout.addLayout(grid)
        controls = QHBoxLayout()
        for text, signal, primary in [
            ("Novo ensaio", self.start_requested, True),
            ("Pausar/retomar", self.pause_requested, False),
            ("Adicionar marcação", self.marker_requested, False),
            ("Finalizar", self.finish_requested, False),
        ]:
            button = QPushButton(text)
            if primary:
                button.setObjectName("primary")
            button.clicked.connect(signal)
            controls.addWidget(button)
        controls.addStretch()
        info_layout.addLayout(controls)
        layout.addWidget(info)

        stats_card, stats_layout = card_frame()
        heading = QLabel("Estatísticas em tempo real")
        heading.setObjectName("sectionTitle")
        stats_layout.addWidget(heading)
        self.stats_table = QTableWidget(2, 9)
        self.stats_table.setHorizontalHeaderLabels(
            [
                "Variável",
                "Atual",
                "Média",
                "Mediana",
                "Mín.",
                "Máx.",
                "Amplitude",
                "Desvio",
                "Válidas",
            ]
        )
        self.stats_table.setVerticalHeaderLabels(["", ""])
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        stats_layout.addWidget(self.stats_table)
        layout.addWidget(stats_card)
        layout.addStretch()
        self.values: dict[str, list[float]] = {"Pressão": [], "Vazão": []}

    def set_session(self, session: TestSession | None) -> None:
        if not session:
            for label in self.labels.values():
                label.setText("—")
            return
        self.labels["code"].setText(session.definition.code)
        self.labels["sample"].setText(session.definition.sample_name)
        self.labels["operator"].setText(session.definition.operator)
        self.labels["start"].setText(session.started_at.strftime("%d/%m/%Y %H:%M:%S"))
        self.labels["status"].setText(session.status.value.replace("_", " ").capitalize())

    def add_measurement(self, m: Measurement) -> None:
        for key, reading in [("Pressão", m.pressure), ("Vazão", m.flow)]:
            # WARNING e SIMULATED contam como válidas; INVALID, STALE,
            # DISCONNECTED e MISSING são excluídas por SensorReading.valid.
            if reading.valid:
                self.values[key].append(reading.value)
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        for row, (name, values) in enumerate(self.values.items()):
            stats = calculate_statistics(values)
            entries = [
                name,
                stats.current,
                stats.average,
                stats.median,
                stats.minimum,
                stats.maximum,
                stats.amplitude,
                stats.standard_deviation,
                stats.valid_count,
            ]
            for col, value in enumerate(entries):
                text = (
                    value
                    if isinstance(value, str)
                    else str(value)
                    if isinstance(value, int)
                    else (f"{value:.3f}" if value is not None else "—")
                )
                self.stats_table.setItem(row, col, QTableWidgetItem(text))

    def reset(self) -> None:
        for values in self.values.values():
            values.clear()
        self.set_session(None)
        self._refresh_stats()


class HistoryPage(QWidget):
    search_requested = Signal(str)
    open_requested = Signal(int)
    export_requested = Signal(int, str)
    delete_requested = Signal(int)
    invalidate_requested = Signal(int)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addLayout(page_header("Histórico", "Consulte e exporte ensaios armazenados"))
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar código, amostra ou operador…")
        self.search.returnPressed.connect(lambda: self.search_requested.emit(self.search.text()))
        search_button = QPushButton("Pesquisar")
        search_button.clicked.connect(lambda: self.search_requested.emit(self.search.text()))
        self.date_from = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_from.dateChanged.connect(lambda: self.search_requested.emit(self.search.text()))
        self.date_to.dateChanged.connect(lambda: self.search_requested.emit(self.search.text()))
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(search_button)
        toolbar.addWidget(QLabel("De"))
        toolbar.addWidget(self.date_from)
        toolbar.addWidget(QLabel("Até"))
        toolbar.addWidget(self.date_to)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "Código",
                "Amostra",
                "Operador",
                "Data",
                "Tempo ativo / legado",
                "Amostras",
                "P. máxima",
                "V. máxima",
                "Status",
                "Observações",
            ]
        )
        self.table.setColumnHidden(0, True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda: self._emit_selected(self.open_requested))
        layout.addWidget(self.table)
        self.empty_label = QLabel("◇  Nenhum ensaio encontrado para os filtros selecionados")
        self.empty_label.setObjectName("muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)
        actions = QHBoxLayout()
        for text, callback in [
            ("Abrir detalhes", lambda: self._emit_selected(self.open_requested)),
            ("Exportar CSV", lambda: self._emit_export("csv")),
            ("Exportar XLSX", lambda: self._emit_export("xlsx")),
            ("Exportar PDF", lambda: self._emit_export("pdf")),
            ("Marcar inválido", lambda: self._emit_selected(self.invalidate_requested)),
            ("Excluir", lambda: self._emit_selected(self.delete_requested)),
        ]:
            button = QPushButton(text)
            if text == "Excluir":
                button.setObjectName("danger")
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

    def populate(self, rows: list[Any]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for row_data in rows:
            started = datetime.fromisoformat(row_data["inicio"]).date()
            if (
                started < self.date_from.date().toPython()
                or started > self.date_to.date().toPython()
            ):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                row_data["id"],
                row_data["codigo"],
                row_data["amostra_nome"],
                row_data["operador"],
                datetime.fromisoformat(row_data["inicio"]).strftime("%d/%m/%Y %H:%M"),
                (
                    f"{row_data['duracao_segundos'] or 0:.0f} s ativo; "
                    f"{row_data['duracao_pausada_segundos'] or 0:.0f} s pausa; "
                    f"{row_data['duracao_decorrida_segundos'] or 0:.0f} s total"
                    if row_data["duracao_decorrida_segundos"] is not None
                    else f"{row_data['duracao_segundos'] or 0:.0f} s decorrido legado"
                ),
                row_data["quantidade_amostras"],
                row_data["pressao_maxima"],
                row_data["vazao_maxima"],
                row_data["status"],
                row_data["observacao_final"] or row_data["observacoes"] or "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem("—" if value is None else str(value))
                if col in (5, 6, 7, 8):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.empty_label.setVisible(self.table.rowCount() == 0)

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        return int(self.table.item(row, 0).text()) if row >= 0 else None

    def _emit_selected(self, signal: Signal) -> None:
        selected = self.selected_id()
        if selected:
            signal.emit(selected)

    def _emit_export(self, format_name: str) -> None:
        selected = self.selected_id()
        if selected:
            self.export_requested.emit(selected, format_name)


class CalibrationPage(QWidget):
    save_requested = Signal(str, float, float, float, bool, object, str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addLayout(page_header("Calibração", "Ajuste por dois ou múltiplos pontos"))
        workflow = QLabel(
            "1  Selecionar sensor   ›   2  Capturar pontos   ›   3  Calcular   ›   4  Validar   ›   5  Salvar versão"
        )
        workflow.setObjectName("warningBanner")
        layout.addWidget(workflow)
        content = QHBoxLayout()
        setup, setup_layout = card_frame()
        form = QFormLayout()
        self.sensor = QComboBox()
        self.sensor.addItem("Pressão", "pressao")
        self.operator = QLineEdit("Operador")
        self.live_current = QLabel("— mA")
        self.capture_stats = QLabel("Aguardando amostras")
        self.capture_stats.setWordWrap(True)
        self.reference = QDoubleSpinBox()
        self.reference.setRange(-1_000_000, 1_000_000)
        self.reference.setDecimals(4)
        self.points = QTableWidget(0, 2)
        self.points.setHorizontalHeaderLabels(["Corrente média (mA)", "Referência"])
        self.points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        add = QPushButton("Capturar ponto atual")
        add.clicked.connect(self._add_point)
        remove = QPushButton("Remover ponto")
        remove.clicked.connect(self._remove_point)
        calculate = QPushButton("Calcular ajuste")
        calculate.clicked.connect(self._calculate)
        self.gain = QLineEdit()
        self.offset = QLineEdit()
        self.error = QLineEdit()
        for field in (self.gain, self.offset, self.error):
            field.setReadOnly(True)
        self.stability = QLabel("Aguardando pontos")
        self.stability.setObjectName("pillNeutral")
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(80)
        save = QPushButton("Salvar calibração")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        form.addRow("Sensor", self.sensor)
        form.addRow("Operador", self.operator)
        form.addRow("Corrente atual", self.live_current)
        form.addRow("Janela de captura", self.capture_stats)
        form.addRow("Valor de referência", self.reference)
        setup_layout.addLayout(form)
        setup_layout.addWidget(add)
        setup_layout.addWidget(self.points)
        setup_layout.addWidget(remove)
        setup_layout.addWidget(calculate)
        result = QFormLayout()
        result.addRow("Ganho", self.gain)
        result.addRow("Offset", self.offset)
        result.addRow("Erro RMSE", self.error)
        self.equation = QLabel("Equação: valor = leitura × ganho + offset")
        self.equation.setObjectName("muted")
        result.addRow("Modelo aplicado", self.equation)
        result.addRow("Estabilidade", self.stability)
        result.addRow("Observações", self.notes)
        setup_layout.addLayout(result)
        setup_layout.addWidget(save)
        content.addWidget(setup, 1)

        history, history_layout = card_frame()
        title = QLabel("Histórico de calibrações")
        title.setObjectName("sectionTitle")
        history_layout.addWidget(title)
        self.history = QTableWidget(0, 7)
        self.history.setHorizontalHeaderLabels(
            ["Versão", "Data", "Responsável", "Ganho", "Offset", "Erro", "Ativa"]
        )
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        history_layout.addWidget(self.history)
        content.addWidget(history, 1)
        layout.addLayout(content)
        self.current_ma: dict[str, float | None] = {}
        self.sample_windows: dict[str, deque[float]] = {
            "pressao": deque(maxlen=10),
        }
        self.result = None

    def update_measurement(self, m: Measurement) -> None:
        self.current_ma = {
            "pressao": m.pressure.current_ma,
        }
        for key, value in self.current_ma.items():
            if value is not None:
                self.sample_windows[key].append(value)
        current = self.current_ma.get(self.sensor.currentData())
        self.live_current.setText(f"{current:.3f} mA" if current is not None else "— mA")
        samples = list(self.sample_windows[self.sensor.currentData()])
        if samples:
            average = mean(samples)
            deviation = (sum((value - average) ** 2 for value in samples) / len(samples)) ** 0.5
            self.capture_stats.setText(
                f"n={len(samples)} · média {average:.4f} · σ {deviation:.4f} · "
                f"mín {min(samples):.4f} · máx {max(samples):.4f} mA"
            )

    def _add_point(self) -> None:
        samples = list(self.sample_windows[self.sensor.currentData()])
        if not samples:
            return
        current = mean(samples)
        row = self.points.rowCount()
        self.points.insertRow(row)
        self.points.setItem(row, 0, QTableWidgetItem(f"{current:.5f}"))
        self.points.setItem(row, 1, QTableWidgetItem(f"{self.reference.value():.5f}"))

    def _remove_point(self) -> None:
        if self.points.currentRow() >= 0:
            self.points.removeRow(self.points.currentRow())

    def _point_values(self) -> list[tuple[float, float]]:
        return [
            (float(self.points.item(row, 0).text()), float(self.points.item(row, 1).text()))
            for row in range(self.points.rowCount())
        ]

    def _calculate(self) -> None:
        try:
            samples = list(self.sample_windows[self.sensor.currentData()])
            self.result = fit_calibration(self._point_values(), samples)
            self.gain.setText(f"{self.result.gain:.8f}")
            self.offset.setText(f"{self.result.offset:.8f}")
            self.error.setText(f"{self.result.error_rmse:.6f}")
            self.stability.setText(
                "Estável" if self.result.stable else "Instável — confirme antes de salvar"
            )
            self.stability.setObjectName("pillGood" if self.result.stable else "pillWarn")
            self.stability.style().unpolish(self.stability)
            self.stability.style().polish(self.stability)
        except (ValueError, AttributeError):
            self.result = None
            self.stability.setText("Informe ao menos dois pontos válidos")
            self.stability.setObjectName("pillBad")

    def _save(self) -> None:
        if self.result:
            self.save_requested.emit(
                self.sensor.currentData(),
                self.result.gain,
                self.result.offset,
                self.result.error_rmse,
                self.result.stable,
                self._point_values(),
                self.notes.toPlainText().strip(),
            )

    def populate_history(self, rows: list[Any]) -> None:
        self.history.setRowCount(0)
        for item in rows:
            row = self.history.rowCount()
            self.history.insertRow(row)
            for col, value in enumerate(
                [
                    f"CAL-{item['id']:04d}",
                    datetime.fromisoformat(item["timestamp"]).strftime("%d/%m/%Y %H:%M"),
                    item["operador"],
                    item["ganho"],
                    item["offset"],
                    item["erro"],
                    "Sim" if item["ativa"] else "Não",
                ]
            ):
                self.history.setItem(row, col, QTableWidgetItem(str(value)))


class SettingsPage(QWidget):
    save_requested = Signal(dict)

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.config = config
        layout = QVBoxLayout(self)
        layout.addLayout(page_header("Configurações", "Comunicação, sensores, interface e dados"))
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)
        tabs = self.tabs
        layout.addWidget(tabs)
        communication = QWidget()
        form = QFormLayout(communication)
        self.port = QLineEdit(config["comunicacao"].get("porta", ""))
        self.baud = QComboBox()
        self.baud.addItems(["9600", "19200", "38400", "57600", "115200", "230400"])
        self.baud.setCurrentText(str(config["comunicacao"]["baud_rate"]))
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(1, 60)
        self.timeout.setValue(config["comunicacao"]["timeout_s"])
        self.auto_reconnect = QCheckBox()
        self.auto_reconnect.setChecked(config["comunicacao"]["reconexao_automatica"])
        form.addRow("Porta padrão", self.port)
        form.addRow("Baud rate", self.baud)
        form.addRow("Timeout (s)", self.timeout)
        form.addRow("Reconexão automática", self.auto_reconnect)
        tabs.addTab(communication, "Conexão")

        sensors = QWidget()
        sensor_layout = QVBoxLayout(sensors)
        sensor_help = QLabel(
            "A faixa de pressão é validada. Para a vazão Modbus, mínimo e máximo são apenas referências visuais e não bloqueiam o ensaio."
        )
        sensor_help.setObjectName("warningBanner")
        sensor_help.setWordWrap(True)
        sensor_layout.addWidget(sensor_help)
        self.sensor_table = QTableWidget(2, 5)
        self.sensor_table.setHorizontalHeaderLabels(
            ["Chave", "Sensor", "Unidade", "Mínimo", "Máximo"]
        )
        self.sensor_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, key in enumerate(("pressao", "vazao")):
            cfg = config["sensores"][key]
            values = [
                key,
                cfg["nome"],
                cfg["unidade"],
                "" if cfg.get("limite_inferior") is None else cfg["limite_inferior"],
                "" if cfg.get("limite_superior") is None else cfg["limite_superior"],
            ]
            for col, value in enumerate(values):
                self.sensor_table.setItem(row, col, QTableWidgetItem(str(value)))
        sensor_layout.addWidget(self.sensor_table)
        tabs.addTab(sensors, "Transdutor")

        modbus = QWidget()
        modbus_form = QFormLayout(modbus)
        modbus_notice = QLabel(
            "Preencha somente com dados confirmados no manual do flow meter. Campos vazios mantêm o modo real bloqueado."
        )
        modbus_notice.setObjectName("warningBanner")
        modbus_notice.setWordWrap(True)
        modbus_form.addRow(modbus_notice)
        flow_cfg = config["flowmeter"]
        self.modbus_configured = QCheckBox("Parâmetros conferidos no manual")
        self.modbus_configured.setChecked(bool(flow_cfg.get("configurado")))
        modbus_form.addRow("Estado", self.modbus_configured)
        unit_help = QLabel(
            "L/min é volume nas condições informadas; NL/min é volume normalizado e exige "
            "pressão e temperatura normais confirmadas. Não selecione NL/min por suposição."
        )
        unit_help.setWordWrap(True)
        unit_help.setObjectName("warningBanner")
        modbus_form.addRow(unit_help)
        self.flow_unit = QComboBox()
        self.flow_unit.addItems(["L/min", "NL/min", "mL/min"])
        self.flow_unit.setCurrentText(
            str(flow_cfg.get("unit") or config["sensores"]["vazao"].get("unidade", "L/min"))
        )
        self.flow_unit_confirmed = QCheckBox("Unidade conferida no manual/equipamento")
        self.flow_unit_confirmed.setChecked(bool(flow_cfg.get("unit_confirmed", False)))
        self.normal_pressure = QDoubleSpinBox()
        self.normal_pressure.setRange(0.001, 10000)
        self.normal_pressure.setDecimals(3)
        self.normal_pressure.setValue(float(flow_cfg.get("normal_pressure_kpa_abs") or 101.325))
        self.normal_temperature = QDoubleSpinBox()
        self.normal_temperature.setRange(-273.14, 1000)
        self.normal_temperature.setDecimals(2)
        self.normal_temperature.setValue(float(flow_cfg.get("normal_temperature_c") or 0.0))
        self.normal_reference_confirmed = QCheckBox("Pressão e temperatura normais conferidas")
        self.normal_reference_confirmed.setChecked(
            bool(flow_cfg.get("normal_reference_confirmed", False))
        )
        self.volume_reference_pressure = QDoubleSpinBox()
        self.volume_reference_pressure.setRange(0.001, 10000)
        self.volume_reference_pressure.setDecimals(3)
        self.volume_reference_pressure.setValue(
            float(flow_cfg.get("volume_reference_pressure_kpa_abs") or 101.325)
        )
        modbus_form.addRow("Unidade fornecida", self.flow_unit)
        modbus_form.addRow("Confirmação da unidade", self.flow_unit_confirmed)
        modbus_form.addRow("Pressão normal (kPa abs)", self.normal_pressure)
        modbus_form.addRow("Temperatura normal (°C)", self.normal_temperature)
        modbus_form.addRow("Confirmação das referências", self.normal_reference_confirmed)
        modbus_form.addRow("Pressão de referência L/min (kPa abs)", self.volume_reference_pressure)
        self.modbus_fields: dict[str, QLineEdit] = {}
        for key, label in [
            ("porta", "Porta USB–RS485"),
            ("slave_id", "Endereço do escravo"),
            ("baud_rate", "Baud rate RS-485"),
            ("funcao", "Função Modbus"),
            ("registrador_inicial", "Registrador inicial"),
            ("quantidade_registradores", "Quantidade de registradores"),
            ("tipo_dado", "Tipo do dado"),
            ("ordem_bytes", "Ordem de bytes"),
            ("fator_escala", "Fator de escala"),
        ]:
            field = QLineEdit("" if flow_cfg.get(key) is None else str(flow_cfg[key]))
            field.setPlaceholderText("Obrigatório · consultar manual")
            field.setProperty("required", True)
            if key != "porta":
                field.setReadOnly(True)
                field.setToolTip(
                    "Parâmetro fixo do flowmeter validado; comunicação somente leitura"
                )
            self.modbus_fields[key] = field
            modbus_form.addRow(label, field)
        self.modbus_timeout = QDoubleSpinBox()
        self.modbus_timeout.setRange(0.75, 1.5)
        self.modbus_timeout.setSingleStep(0.05)
        self.modbus_timeout.setValue(float(flow_cfg.get("timeout_s", 1.0)))
        self.modbus_interval = QSpinBox()
        self.modbus_interval.setRange(125, 60000)
        self.modbus_interval.setValue(int(flow_cfg.get("intervalo_ms", 1000)))
        self.modbus_log_frames = QCheckBox("Habilitar no diagnóstico")
        self.modbus_log_frames.setChecked(bool(flow_cfg.get("log_frames", False)))
        modbus_form.addRow("Timeout (s)", self.modbus_timeout)
        modbus_form.addRow("Intervalo de leitura (ms)", self.modbus_interval)
        modbus_form.addRow("Log de frames TX/RX", self.modbus_log_frames)
        tabs.addTab(modbus, "Modbus")

        ads = QWidget()
        ads_form = QFormLayout(ads)
        pressure_cfg = config["sensores"]["pressao"]
        ads_form.addRow("Interface I²C", QLabel("SDA GPIO21 · SCL GPIO22"))
        ads_form.addRow(
            "Endereço ADS1115", QLabel(str(pressure_cfg.get("ads1115_endereco", "0x48")))
        )
        ads_form.addRow(
            "Canal", QLabel(f"A{pressure_cfg.get('ads1115_canal', 0)} · single-ended para GND")
        )
        ads_form.addRow("Faixa do ADC", QLabel(f"±{pressure_cfg.get('ads1115_faixa_v', 4.096)} V"))
        ads_form.addRow("Resistor shunt", QLabel(f"{pressure_cfg.get('shunt_ohm', 149.7)} Ω"))
        ads_notice = QLabel("⚠ 24 V nunca deve ser aplicado ao ESP32 ou ADS1115.")
        ads_notice.setObjectName("warningBanner")
        ads_form.addRow(ads_notice)
        tabs.addTab(ads, "ADS1115")

        calculation_notice = QLabel(
            "A permeabilidade é calculada a partir da geometria da amostra, pressão, vazão, gás e viscosidade. Configure a pressão de saída na tela de cálculo."
        )
        calculation_notice.setWordWrap(True)
        tabs.addTab(calculation_notice, "Permeabilidade")

        data = QWidget()
        data_form = QFormLayout(data)
        self.export_path = QLineEdit(config["dados"].get("diretorio_exportacao", ""))
        self.separator = QComboBox()
        self.separator.addItems([";", ",", "\\t"])
        self.separator.setCurrentText(config["dados"].get("separador_csv", ";"))
        self.backup = QCheckBox()
        self.backup.setChecked(config["dados"].get("backup_automatico", True))
        self.sound = QCheckBox()
        data_form.addRow("Diretório de exportação", self.export_path)
        data_form.addRow("Separador CSV", self.separator)
        data_form.addRow("Backup automático", self.backup)
        data_form.addRow("Sinal sonoro de alarme", self.sound)
        tabs.addTab(data, "Dados")
        save = QPushButton("Salvar configurações")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)

    def _save(self) -> None:
        sensors: dict[str, dict[str, Any]] = {}
        for row in range(self.sensor_table.rowCount()):
            key = self.sensor_table.item(row, 0).text()
            lower = self.sensor_table.item(row, 3).text().strip()
            upper = self.sensor_table.item(row, 4).text().strip()
            sensors[key] = {
                "nome": self.sensor_table.item(row, 1).text(),
                "unidade": self.sensor_table.item(row, 2).text(),
                "limite_inferior": float(lower) if lower else None,
                "limite_superior": float(upper) if upper else None,
            }
        flow: dict[str, Any] = {
            "configurado": self.modbus_configured.isChecked(),
            "unit": self.flow_unit.currentText(),
            "unit_confirmed": self.flow_unit_confirmed.isChecked(),
            "normal_pressure_kpa_abs": self.normal_pressure.value(),
            "normal_temperature_c": self.normal_temperature.value(),
            "normal_reference_confirmed": self.normal_reference_confirmed.isChecked(),
            "volume_reference_pressure_kpa_abs": self.volume_reference_pressure.value(),
        }
        integer_keys = {
            "slave_id",
            "baud_rate",
            "funcao",
            "registrador_inicial",
            "quantidade_registradores",
            "intervalo_ms",
        }
        for key, field in self.modbus_fields.items():
            text = field.text().strip()
            flow[key] = (
                int(text)
                if text and key in integer_keys
                else float(text)
                if text and key == "fator_escala"
                else text or None
            )
        flow.update(
            {
                "timeout_s": self.modbus_timeout.value(),
                "intervalo_ms": self.modbus_interval.value(),
                "stale_after_s": max(3.0, self.modbus_interval.value() * 3 / 1000.0),
                "reconexao_automatica": True,
                "log_frames": self.modbus_log_frames.isChecked(),
            }
        )
        sensors["vazao"]["unidade"] = self.flow_unit.currentText()
        self.save_requested.emit(
            {
                "comunicacao": {
                    "porta": self.port.text().strip(),
                    "baud_rate": int(self.baud.currentText()),
                    "timeout_s": self.timeout.value(),
                    "reconexao_automatica": self.auto_reconnect.isChecked(),
                },
                "sensores": sensors,
                "flowmeter": flow,
                "dados": {
                    "diretorio_exportacao": self.export_path.text().strip(),
                    "separador_csv": self.separator.currentText(),
                    "backup_automatico": self.backup.isChecked(),
                },
                "calculos": self.config.get("calculos", {}),
            }
        )


class DiagnosticsPage(QWidget):
    copy_requested = Signal()
    reset_requested = Signal()
    db_test_requested = Signal()
    export_test_requested = Signal()
    open_logs_requested = Signal()
    restart_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addLayout(
            page_header("Diagnóstico", "Informações técnicas da aquisição e armazenamento")
        )
        info, info_layout = card_frame()
        grid = QGridLayout()
        self.values: dict[str, QLabel] = {}
        fields = [
            ("port", "Porta serial"),
            ("baud", "Baud rate"),
            ("connection", "Conexão"),
            ("last_age", "Última mensagem"),
            ("frequency", "Frequência real"),
            ("valid", "Mensagens válidas"),
            ("invalid", "Mensagens inválidas"),
            ("database", "Banco de dados"),
            ("db_path", "Caminho do banco"),
            ("disk", "Espaço em disco"),
            ("version", "Versão"),
            ("mode", "Modo"),
            ("ma_pressure", "Pressão (mA)"),
            ("flow_health", "Saúde do flow meter"),
            ("flow_state", "Estado Modbus"),
            ("reading_age", "Idade da leitura"),
            ("modbus_stats", "Estatísticas Modbus"),
        ]
        for index, (key, title) in enumerate(fields):
            row, col = divmod(index, 3)
            label = QLabel(title)
            label.setObjectName("muted")
            value = QLabel("—")
            value.setWordWrap(True)
            self.values[key] = value
            grid.addWidget(label, row * 2, col)
            grid.addWidget(value, row * 2 + 1, col)
        info_layout.addLayout(grid)
        layout.addWidget(info)
        raw_card, raw_layout = card_frame()
        raw_title = QLabel("Última mensagem bruta")
        raw_title.setObjectName("sectionTitle")
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setMaximumHeight(105)
        raw_layout.addWidget(raw_title)
        raw_layout.addWidget(self.raw)
        layout.addWidget(raw_card)
        frames_card, frames_layout = card_frame()
        frames_title = QLabel("Frames Modbus TX/RX (quando habilitados)")
        frames_title.setObjectName("sectionTitle")
        self.frames = QPlainTextEdit()
        self.frames.setReadOnly(True)
        self.frames.setMaximumHeight(105)
        self.frames.document().setMaximumBlockCount(200)
        frames_layout.addWidget(frames_title)
        frames_layout.addWidget(self.frames)
        layout.addWidget(frames_card)
        buttons = QHBoxLayout()
        for text, signal in [
            ("Copiar diagnóstico", self.copy_requested),
            ("Limpar contadores", self.reset_requested),
            ("Testar banco", self.db_test_requested),
            ("Testar exportação", self.export_test_requested),
            ("Abrir logs", self.open_logs_requested),
            ("Reiniciar conexão", self.restart_requested),
        ]:
            button = QPushButton(text)
            button.clicked.connect(signal)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addStretch()

    def report_text(self) -> str:
        lines = [f"{key}: {label.text()}" for key, label in self.values.items()]
        lines.append(f"Mensagem: {self.raw.toPlainText()}")
        lines.append(f"Frames Modbus:\n{self.frames.toPlainText()}")
        return "\n".join(lines)


class AboutPage(QWidget):
    def __init__(self, version: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addLayout(
            page_header("Sobre", "Identificação, arquitetura e informações de suporte")
        )
        card, card_layout = card_frame()
        logo = QLabel()
        logo.setPixmap(
            QPixmap(str(branding_path("ism_logo_horizontal.png"))).scaled(
                560,
                190,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setMinimumHeight(170)
        title = QLabel("Supervisório ISM – Permeabilímetro")
        title.setObjectName("pageTitle")
        description = QLabel(
            "Sistema industrial de aquisição e análise para um transdutor de pressão 4–20 mA "
            "lido pelo ESP32 e um flowmeter Modbus RTU ligado diretamente ao computador por USB–RS485."
        )
        description.setWordWrap(True)
        description.setObjectName("muted")
        details = QFormLayout()
        details.addRow("Versão do software", QLabel(version))
        details.addRow("Protocolo serial", QLabel("JSON Lines · schema 1"))
        details.addRow("Banco de dados", QLabel("SQLite · modo WAL"))
        details.addRow("Interface", QLabel("PySide6 / Qt"))
        notice = QLabel(
            "◇ Consulte o README antes de conectar alimentação de 24 V ou alterar parâmetros Modbus."
        )
        notice.setObjectName("warningBanner")
        notice.setWordWrap(True)
        card_layout.addWidget(logo)
        card_layout.addWidget(title)
        card_layout.addWidget(description)
        card_layout.addSpacing(12)
        card_layout.addLayout(details)
        card_layout.addSpacing(12)
        card_layout.addWidget(notice)
        layout.addWidget(card)
        layout.addStretch()
