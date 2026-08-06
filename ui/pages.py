from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
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
    QScrollArea,
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
from core.constants import TestStatus
from core.models import Alarm, Measurement, TestSession
from ui.widgets.sensor_card import SensorCard


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

        cards = QHBoxLayout()
        self.cards: dict[str, SensorCard] = {}
        for key in ("pressao", "vazao_baixa", "vazao_alta"):
            cfg = sensor_config[key]
            card = SensorCard(
                cfg["nome"], cfg["unidade"], float(cfg["limite_inferior"]),
                float(cfg["limite_superior"]), int(cfg.get("casas", 2)),
            )
            cards.addWidget(card)
            self.cards[key] = card
        outer.addLayout(cards)

        lower = QHBoxLayout()
        plot_card, plot_layout = card_frame()
        title = QLabel("Últimos 60 segundos")
        title.setObjectName("sectionTitle")
        plot_layout.addWidget(title)
        self.compact_plot = pg.PlotWidget()
        self.compact_plot.setMinimumHeight(210)
        self.compact_plot.showGrid(x=True, y=True, alpha=0.15)
        self.compact_plot.setBackground("w")
        self.pressure_curve = self.compact_plot.plot(pen=pg.mkPen("#216C83", width=2), name="Pressão")
        self.low_curve = self.compact_plot.plot(pen=pg.mkPen("#3A9470", width=2), name="Vazão baixa")
        self.high_curve = self.compact_plot.plot(pen=pg.mkPen("#D48B32", width=2), name="Vazão alta")
        self.compact_plot.addLegend(offset=(8, 8))
        plot_layout.addWidget(self.compact_plot)
        lower.addWidget(plot_card, 2)

        status_card, status_layout = card_frame()
        status_title = QLabel("Ensaio")
        status_title.setObjectName("sectionTitle")
        status_layout.addWidget(status_title)
        stats = QGridLayout()
        self.duration = QLabel("00:00:00")
        self.samples = QLabel("0")
        self.rate = QLabel("— Hz")
        self.recording = QLabel("Aguardando")
        self.active_flow = QLabel("Baixa vazão")
        for i, (label, value) in enumerate([
            ("Duração", self.duration), ("Amostras", self.samples),
            ("Taxa real", self.rate), ("Registro", self.recording),
            ("Faixa ativa", self.active_flow),
        ]):
            name = QLabel(label)
            name.setObjectName("muted")
            stats.addWidget(name, i, 0)
            stats.addWidget(value, i, 1)
        status_layout.addLayout(stats)
        status_layout.addStretch()
        self.start_button = QPushButton("Iniciar ensaio")
        self.start_button.setObjectName("primary")
        self.pause_button = QPushButton("Pausar")
        self.finish_button = QPushButton("Finalizar ensaio")
        self.finish_button.setObjectName("danger")
        self.marker_button = QPushButton("Adicionar marcação")
        self.start_button.clicked.connect(self.start_requested)
        self.pause_button.clicked.connect(self.pause_requested)
        self.finish_button.clicked.connect(self.finish_requested)
        self.marker_button.clicked.connect(self.marker_requested)
        status_layout.addWidget(self.start_button)
        status_layout.addWidget(self.pause_button)
        status_layout.addWidget(self.finish_button)
        status_layout.addWidget(self.marker_button)
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

        self._times: deque[float] = deque(maxlen=60)
        self._pressure: deque[float] = deque(maxlen=60)
        self._low: deque[float] = deque(maxlen=60)
        self._high: deque[float] = deque(maxlen=60)
        self._first_time: datetime | None = None

    def update_measurement(self, measurement: Measurement) -> None:
        self.cards["pressao"].update_reading(measurement.pressure)
        self.cards["vazao_baixa"].update_reading(measurement.low_flow)
        self.cards["vazao_alta"].update_reading(measurement.high_flow)
        self.active_flow.setText(
            "Alta vazão" if measurement.active_flow_meter == "alta" else "Baixa vazão"
        )
        self.simulation_banner.setVisible(measurement.simulated)
        if self._first_time is None:
            self._first_time = measurement.received_at
        t = (measurement.received_at - self._first_time).total_seconds()
        self._times.append(t)
        self._pressure.append(float("nan") if measurement.pressure.value is None else measurement.pressure.value)
        self._low.append(float("nan") if measurement.low_flow.value is None else measurement.low_flow.value)
        self._high.append(float("nan") if measurement.high_flow.value is None else measurement.high_flow.value)
        x = list(self._times)
        self.pressure_curve.setData(x, list(self._pressure))
        self.low_curve.setData(x, list(self._low))
        self.high_curve.setData(x, list(self._high))

    def set_test_active(self, active: bool, paused: bool = False) -> None:
        self.start_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
        self.finish_button.setEnabled(active)
        self.marker_button.setEnabled(active)
        self.pause_button.setText("Retomar" if paused else "Pausar")
        self.recording.setText("Pausado" if paused else "Gravando" if active else "Aguardando")
        if not active:
            self.duration.setText("00:00:00")

    def reset_test(self) -> None:
        for card in self.cards.values():
            card.reset_statistics()
        self.samples.setText("0")
        self.set_test_active(False)

    def add_alarm(self, alarm_id: int, alarm: Alarm) -> None:
        row = self.alarm_table.rowCount()
        self.alarm_table.insertRow(row)
        for col, text in enumerate([
            str(alarm_id), alarm.timestamp.strftime("%H:%M:%S"), alarm.sensor,
            alarm.severity.value, alarm.message,
        ]):
            item = QTableWidgetItem(text)
            if alarm.severity.value in ("alarme", "crítico"):
                item.setForeground(QColor("#A43131"))
            self.alarm_table.setItem(row, col, item)

    def _ack_selected(self) -> None:
        row = self.alarm_table.currentRow()
        if row >= 0:
            self.acknowledge_requested.emit(int(self.alarm_table.item(row, 0).text()))
            self.alarm_table.removeRow(row)


class GraphsPage(QWidget):
    export_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addLayout(page_header("Gráficos", "Aquisição em tempo real; zoom e deslocamento disponíveis"))
        toolbar = QHBoxLayout()
        self.window_combo = QComboBox()
        self.window_combo.addItems(["Últimos 60 s", "Últimos 5 min", "Todo o ensaio"])
        self.visual_pause = QCheckBox("Pausar visualização")
        self.auto_zoom = QCheckBox("Zoom automático")
        self.auto_zoom.setChecked(True)
        export = QPushButton("Exportar PNG")
        export.clicked.connect(self.export_requested)
        toolbar.addWidget(QLabel("Janela:"))
        toolbar.addWidget(self.window_combo)
        toolbar.addWidget(self.visual_pause)
        toolbar.addWidget(self.auto_zoom)
        toolbar.addStretch()
        toolbar.addWidget(export)
        layout.addLayout(toolbar)
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground("w")
        layout.addWidget(self.graphics)
        titles = [
            "Pressão × tempo", "Vazão baixa × tempo", "Vazão alta × tempo",
            "Pressão e vazão", "Correntes 4–20 mA", "Vazão selecionada × pressão",
        ]
        self.plots: list[pg.PlotItem] = []
        for index, title in enumerate(titles):
            plot = self.graphics.addPlot(row=index // 2, col=index % 2, title=title)
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.addLegend(offset=(5, 5))
            plot.setClipToView(True)
            self.plots.append(plot)
        self.curves = {
            "pressure": self.plots[0].plot(pen=pg.mkPen("#216C83", width=2), name="Pressão"),
            "low": self.plots[1].plot(pen=pg.mkPen("#3A9470", width=2), name="Baixa"),
            "high": self.plots[2].plot(pen=pg.mkPen("#D48B32", width=2), name="Alta"),
            "combined_p": self.plots[3].plot(pen=pg.mkPen("#216C83", width=2), name="Pressão"),
            "combined_f": self.plots[3].plot(pen=pg.mkPen("#8D5BA6", width=2), name="Vazão ativa"),
            "ma_p": self.plots[4].plot(pen=pg.mkPen("#216C83"), name="Pressão"),
            "ma_l": self.plots[4].plot(pen=pg.mkPen("#3A9470"), name="Baixa"),
            "ma_h": self.plots[4].plot(pen=pg.mkPen("#D48B32"), name="Alta"),
            "flow_pressure": self.plots[5].plot(
                pen=pg.mkPen("#8D5BA6", width=2), symbol="o", symbolSize=3, name="Vazão"
            ),
        }
        self.cursor_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#7A8D94"))
        self.plots[0].addItem(self.cursor_v, ignoreBounds=True)
        self.plots[0].scene().sigMouseMoved.connect(self._mouse_moved)
        self.times: list[float] = []
        self.pressure: list[float] = []
        self.low: list[float] = []
        self.high: list[float] = []
        self.ma_p: list[float] = []
        self.ma_l: list[float] = []
        self.ma_h: list[float] = []
        self.active_flow: list[float] = []
        self._first: datetime | None = None

    def add_measurement(self, m: Measurement) -> None:
        if self._first is None:
            self._first = m.received_at
        self.times.append((m.received_at - self._first).total_seconds())
        nan = float("nan")
        self.pressure.append(m.pressure.value if m.pressure.value is not None else nan)
        self.low.append(m.low_flow.value if m.low_flow.value is not None else nan)
        self.high.append(m.high_flow.value if m.high_flow.value is not None else nan)
        self.ma_p.append(m.pressure.current_ma if m.pressure.current_ma is not None else nan)
        self.ma_l.append(m.low_flow.current_ma if m.low_flow.current_ma is not None else nan)
        self.ma_h.append(m.high_flow.current_ma if m.high_flow.current_ma is not None else nan)
        active = m.high_flow.value if m.active_flow_meter == "alta" else m.low_flow.value
        self.active_flow.append(active if active is not None else nan)
        if len(self.times) > 100_000:
            for values in (
                self.times, self.pressure, self.low, self.high, self.ma_p, self.ma_l,
                self.ma_h, self.active_flow,
            ):
                del values[:10_000]
        if not self.visual_pause.isChecked():
            self.refresh()

    def refresh(self) -> None:
        if not self.times:
            return
        window = [60, 300, None][self.window_combo.currentIndex()]
        start = 0
        if window is not None:
            threshold = self.times[-1] - window
            start = max(0, next((i for i, x in enumerate(self.times) if x >= threshold), 0))
        step = max(1, (len(self.times) - start) // 3000)
        sl = slice(start, None, step)
        x = self.times[sl]
        datasets = {
            "pressure": self.pressure[sl], "low": self.low[sl], "high": self.high[sl],
            "combined_p": self.pressure[sl], "combined_f": self.active_flow[sl],
            "ma_p": self.ma_p[sl], "ma_l": self.ma_l[sl], "ma_h": self.ma_h[sl],
        }
        for name, values in datasets.items():
            self.curves[name].setData(x, values)
        self.curves["flow_pressure"].setData(self.pressure[sl], self.active_flow[sl])
        if self.auto_zoom.isChecked():
            for plot in self.plots:
                plot.enableAutoRange()

    def reset(self) -> None:
        for values in (
            self.times, self.pressure, self.low, self.high, self.ma_p, self.ma_l,
            self.ma_h, self.active_flow,
        ):
            values.clear()
        self._first = None
        for curve in self.curves.values():
            curve.clear()

    def _mouse_moved(self, pos) -> None:
        if self.plots[0].sceneBoundingRect().contains(pos):
            point = self.plots[0].vb.mapSceneToView(pos)
            self.cursor_v.setPos(point.x())


class TestPage(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    finish_requested = Signal()
    marker_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addLayout(page_header("Ensaio", "Identificação, controle e estatísticas do ensaio atual"))
        info, info_layout = card_frame()
        grid = QGridLayout()
        self.labels: dict[str, QLabel] = {}
        for index, (key, title) in enumerate([
            ("code", "Código"), ("sample", "Amostra"), ("operator", "Operador"),
            ("start", "Início"), ("status", "Status"), ("duration", "Duração"),
        ]):
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
            ("Novo ensaio", self.start_requested, True), ("Pausar/retomar", self.pause_requested, False),
            ("Adicionar marcação", self.marker_requested, False), ("Finalizar", self.finish_requested, False),
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
        self.stats_table = QTableWidget(3, 9)
        self.stats_table.setHorizontalHeaderLabels(
            ["Variável", "Atual", "Média", "Mediana", "Mín.", "Máx.", "Amplitude", "Desvio", "Válidas"]
        )
        self.stats_table.setVerticalHeaderLabels(["", "", ""])
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        stats_layout.addWidget(self.stats_table)
        layout.addWidget(stats_card)
        layout.addStretch()
        self.values: dict[str, list[float]] = {
            "Pressão": [], "Vazão baixa": [], "Vazão alta": []
        }

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
        for key, reading in [
            ("Pressão", m.pressure), ("Vazão baixa", m.low_flow), ("Vazão alta", m.high_flow)
        ]:
            if reading.value is not None and reading.quality.value not in ("inválida", "ausente"):
                self.values[key].append(reading.value)
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        for row, (name, values) in enumerate(self.values.items()):
            stats = calculate_statistics(values)
            entries = [
                name, stats.current, stats.average, stats.median, stats.minimum,
                stats.maximum, stats.amplitude, stats.standard_deviation, stats.valid_count,
            ]
            for col, value in enumerate(entries):
                text = value if isinstance(value, str) else str(value) if isinstance(value, int) else (
                    f"{value:.3f}" if value is not None else "—"
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
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(search_button)
        toolbar.addWidget(QLabel("De"))
        toolbar.addWidget(self.date_from)
        toolbar.addWidget(QLabel("Até"))
        toolbar.addWidget(self.date_to)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            "ID", "Código", "Amostra", "Operador", "Data", "Duração", "Amostras",
            "P. máxima", "V. máxima", "Status", "Observações",
        ])
        self.table.setColumnHidden(0, True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda: self._emit_selected(self.open_requested))
        layout.addWidget(self.table)
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
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

    def populate(self, rows: list[Any]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for row_data in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                row_data["id"], row_data["codigo"], row_data["amostra_nome"], row_data["operador"],
                datetime.fromisoformat(row_data["inicio"]).strftime("%d/%m/%Y %H:%M"),
                f"{row_data['duracao_segundos'] or 0:.0f} s", row_data["quantidade_amostras"],
                row_data["pressao_maxima"], row_data["vazao_maxima"], row_data["status"],
                row_data["observacao_final"] or row_data["observacoes"] or "",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem("—" if value is None else str(value)))
        self.table.setSortingEnabled(True)

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
        content = QHBoxLayout()
        setup, setup_layout = card_frame()
        form = QFormLayout()
        self.sensor = QComboBox()
        self.sensor.addItem("Pressão", "pressao")
        self.sensor.addItem("Vazão baixa", "vazao_baixa")
        self.sensor.addItem("Vazão alta", "vazao_alta")
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
        result.addRow("Estabilidade", self.stability)
        result.addRow("Observações", self.notes)
        setup_layout.addLayout(result)
        setup_layout.addWidget(save)
        content.addWidget(setup, 1)

        history, history_layout = card_frame()
        title = QLabel("Histórico de calibrações")
        title.setObjectName("sectionTitle")
        history_layout.addWidget(title)
        self.history = QTableWidget(0, 6)
        self.history.setHorizontalHeaderLabels(["Data", "Operador", "Ganho", "Offset", "Erro", "Ativa"])
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        history_layout.addWidget(self.history)
        content.addWidget(history, 1)
        layout.addLayout(content)
        self.current_ma: dict[str, float | None] = {}
        self.sample_windows: dict[str, deque[float]] = {
            "pressao": deque(maxlen=10),
            "vazao_baixa": deque(maxlen=10),
            "vazao_alta": deque(maxlen=10),
        }
        self.result = None

    def update_measurement(self, m: Measurement) -> None:
        self.current_ma = {
            "pressao": m.pressure.current_ma,
            "vazao_baixa": m.low_flow.current_ma,
            "vazao_alta": m.high_flow.current_ma,
        }
        for key, value in self.current_ma.items():
            if value is not None:
                self.sample_windows[key].append(value)
        current = self.current_ma.get(self.sensor.currentData())
        self.live_current.setText(f"{current:.3f} mA" if current is not None else "— mA")
        samples = list(self.sample_windows[self.sensor.currentData()])
        if samples:
            average = mean(samples)
            deviation = (
                sum((value - average) ** 2 for value in samples) / len(samples)
            ) ** 0.5
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
            self.stability.setText("Estável" if self.result.stable else "Instável — confirme antes de salvar")
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
                self.sensor.currentData(), self.result.gain, self.result.offset,
                self.result.error_rmse, self.result.stable, self._point_values(),
                self.notes.toPlainText().strip(),
            )

    def populate_history(self, rows: list[Any]) -> None:
        self.history.setRowCount(0)
        for item in rows:
            row = self.history.rowCount()
            self.history.insertRow(row)
            for col, value in enumerate([
                datetime.fromisoformat(item["timestamp"]).strftime("%d/%m/%Y %H:%M"),
                item["operador"], item["ganho"], item["offset"], item["erro"],
                "Sim" if item["ativa"] else "Não",
            ]):
                self.history.setItem(row, col, QTableWidgetItem(str(value)))


class SettingsPage(QWidget):
    save_requested = Signal(dict)

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addLayout(page_header("Configurações", "Comunicação, sensores, interface e dados"))
        tabs = QTabWidget()
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
        tabs.addTab(communication, "Comunicação")

        sensors = QWidget()
        sensor_layout = QVBoxLayout(sensors)
        self.sensor_table = QTableWidget(3, 9)
        self.sensor_table.setHorizontalHeaderLabels(
            ["Chave", "Nome", "Unidade", "Mín.", "Máx.", "mA mín.", "mA máx.", "Alerta", "Crítico"]
        )
        self.sensor_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, key in enumerate(("pressao", "vazao_baixa", "vazao_alta")):
            cfg = config["sensores"][key]
            values = [
                key, cfg["nome"], cfg["unidade"], cfg["limite_inferior"], cfg["limite_superior"],
                cfg["corrente_min"], cfg["corrente_max"], cfg["alerta"], cfg["critico"],
            ]
            for col, value in enumerate(values):
                self.sensor_table.setItem(row, col, QTableWidgetItem(str(value)))
        sensor_layout.addWidget(self.sensor_table)
        tabs.addTab(sensors, "Sensores")

        calculations = QWidget()
        calculation_form = QFormLayout(calculations)
        self.calculation_sample_chamber = QDoubleSpinBox()
        self.calculation_sample_chamber.setRange(0.00001, 1_000_000)
        self.calculation_sample_chamber.setDecimals(5)
        self.calculation_sample_chamber.setSuffix(" cm³")
        self.calculation_sample_chamber.setValue(config["calculos"]["volume_camara_amostra_cm3"])
        self.calculation_expansion_chamber = QDoubleSpinBox()
        self.calculation_expansion_chamber.setRange(0.00001, 1_000_000)
        self.calculation_expansion_chamber.setDecimals(5)
        self.calculation_expansion_chamber.setSuffix(" cm³")
        self.calculation_expansion_chamber.setValue(config["calculos"]["volume_expansao_cm3"])
        self.calculation_repeatability = QDoubleSpinBox()
        self.calculation_repeatability.setRange(0.001, 100)
        self.calculation_repeatability.setDecimals(3)
        self.calculation_repeatability.setSuffix(" %")
        self.calculation_repeatability.setValue(config["calculos"]["limite_repetibilidade_percentual"])
        calculation_form.addRow("Volume calibrado da câmara de amostra", self.calculation_sample_chamber)
        calculation_form.addRow("Volume calibrado da câmara de expansão", self.calculation_expansion_chamber)
        calculation_form.addRow("Limite do coeficiente de variação", self.calculation_repeatability)
        tabs.addTab(calculations, "Cálculos")

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
        tabs.addTab(data, "Dados e interface")
        save = QPushButton("Salvar configurações")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)

    def _save(self) -> None:
        sensors: dict[str, dict[str, Any]] = {}
        for row in range(3):
            key = self.sensor_table.item(row, 0).text()
            sensors[key] = {
                "nome": self.sensor_table.item(row, 1).text(),
                "unidade": self.sensor_table.item(row, 2).text(),
                "limite_inferior": float(self.sensor_table.item(row, 3).text()),
                "limite_superior": float(self.sensor_table.item(row, 4).text()),
                "corrente_min": float(self.sensor_table.item(row, 5).text()),
                "corrente_max": float(self.sensor_table.item(row, 6).text()),
                "alerta": float(self.sensor_table.item(row, 7).text()),
                "critico": float(self.sensor_table.item(row, 8).text()),
            }
        self.save_requested.emit({
            "comunicacao": {
                "porta": self.port.text().strip(), "baud_rate": int(self.baud.currentText()),
                "timeout_s": self.timeout.value(),
                "reconexao_automatica": self.auto_reconnect.isChecked(),
            },
            "sensores": sensors,
            "dados": {
                "diretorio_exportacao": self.export_path.text().strip(),
                "separador_csv": self.separator.currentText(),
                "backup_automatico": self.backup.isChecked(),
            },
            "calculos": {
                "volume_camara_amostra_cm3": self.calculation_sample_chamber.value(),
                "volume_expansao_cm3": self.calculation_expansion_chamber.value(),
                "limite_repetibilidade_percentual": self.calculation_repeatability.value(),
            },
        })


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
        layout.addLayout(page_header("Diagnóstico", "Informações técnicas da aquisição e armazenamento"))
        info, info_layout = card_frame()
        grid = QGridLayout()
        self.values: dict[str, QLabel] = {}
        fields = [
            ("port", "Porta serial"), ("baud", "Baud rate"), ("connection", "Conexão"),
            ("last_age", "Última mensagem"), ("frequency", "Frequência real"),
            ("valid", "Mensagens válidas"), ("invalid", "Mensagens inválidas"),
            ("database", "Banco de dados"), ("db_path", "Caminho do banco"),
            ("disk", "Espaço em disco"), ("version", "Versão"), ("mode", "Modo"),
            ("ma_pressure", "Pressão (mA)"), ("ma_low", "Baixa (mA)"), ("ma_high", "Alta (mA)"),
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
        buttons = QHBoxLayout()
        for text, signal in [
            ("Copiar diagnóstico", self.copy_requested), ("Limpar contadores", self.reset_requested),
            ("Testar banco", self.db_test_requested), ("Testar exportação", self.export_test_requested),
            ("Abrir logs", self.open_logs_requested), ("Reiniciar conexão", self.restart_requested),
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
        return "\n".join(lines)
