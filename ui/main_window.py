from __future__ import annotations

import json
import logging
import os
import shutil
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from communication.serial_manager import (
    FlowmeterWorker,
    SerialWorker,
    available_port_details,
)
from communication.simulator import SimulatorWorker
from config.settings import AppPaths, ConfigManager
from core.constants import Severity, TestStatus
from core.models import Alarm, Measurement
from core.version import APP_NAME, APP_VERSION
from database.database import Database
from database.repositories import (
    CalculationRepository,
    CalibrationRepository,
    EventRepository,
    TestRepository,
)
from services.acquisition_service import AcquisitionService
from services.export_service import ExportService
from services.preflight_service import run_preflight
from services.test_service import TestService
from ui.calculation_page import CalculationPage
from ui.dialogs.marker_dialog import MarkerDialog
from ui.dialogs.test_dialog import TestSetupDialog
from ui.pages import (
    AboutPage,
    CalibrationPage,
    DiagnosticsPage,
    GraphsPage,
    HistoryPage,
    OverviewPage,
    SettingsPage,
    TestPage,
)
from ui.resources import branding_path
from ui.theme import COLORS, icon_path
from ui.widgets.components import StatusBadge
from ui.workers import ExportWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, config: ConfigManager, database: Database, paths: AppPaths):
        super().__init__()
        self.config = config
        self.database = database
        self.paths = paths
        self.test_repository = TestRepository(database)
        self.event_repository = EventRepository(database)
        self.calibration_repository = CalibrationRepository(database)
        self.calculation_repository = CalculationRepository(database)
        self.test_service = TestService(self.test_repository, self.event_repository)
        self.export_service = ExportService(self.test_repository, self.event_repository)
        self.acquisition = AcquisitionService(config.data)
        self.serial_worker: SerialWorker | None = None
        self.flowmeter_worker: FlowmeterWorker | None = None
        self.simulator: SimulatorWorker | None = None
        self.connected = False
        self.flow_connected = False
        self.simulating = False
        self.export_workers: set[ExportWorker] = set()
        self.exporting_test_ids: set[int] = set()
        self.message_times: deque[datetime] = deque(maxlen=20)
        self.calculation_test_id: int | None = None

        interrupted = self.test_repository.mark_interrupted_tests()
        if interrupted:
            logger.warning("%s ensaio(s) anterior(es) marcado(s) como interrompido(s)", interrupted)
        self._build_ui()
        self._connect_signals()
        self._load_style()
        self._refresh_ports()
        self._refresh_history()
        self._setup_timers()
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 920)
        self.setMinimumSize(1180, 700)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("contentRoot")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(11, 17, 11, 17)
        brand = QLabel()
        brand.setObjectName("brandLogo")
        brand.setPixmap(
            QPixmap(str(branding_path("ism_simbolo_transparente.png"))).scaled(
                82,
                58,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        brand.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        brand_name = QLabel("PERMEABILÍMETRO SUPERVISÓRIO")
        brand_name.setObjectName("brandName")
        brand_name.setWordWrap(True)
        side_layout.addWidget(brand)
        side_layout.addWidget(brand_name)
        side_layout.addSpacing(16)
        section = QLabel("OPERAÇÃO")
        section.setObjectName("sidebarCaption")
        side_layout.addWidget(section)
        self.nav_buttons: list[QPushButton] = []
        self.nav_by_page: dict[int, QPushButton] = {}
        nav_items = [
            ("Visão geral", "overview", 0),
            ("Novo ensaio", "new_test", 1),
            ("Histórico", "history", 4),
            ("Cálculos", "calculations", 2),
            ("Calibração", "calibration", 5),
            ("Configurações", "settings", 6),
        ]
        for text, icon, page_index in nav_items:
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setIcon(QIcon(icon_path(icon)))
            button.setIconSize(QSize(19, 19))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(lambda _checked=False, i=page_index: self._navigate(i))
            side_layout.addWidget(button)
            self.nav_buttons.append(button)
            self.nav_by_page[page_index] = button
        self.nav_buttons[0].setChecked(True)
        self.advanced_nav_buttons: list[QPushButton] = []
        advanced = QLabel("FERRAMENTAS")
        advanced.setObjectName("sidebarCaption")
        side_layout.addWidget(advanced)
        for text, icon, page_index in [
            ("Gráficos avançados", "graphs", 3),
            ("Diagnóstico", "diagnostics", 7),
            ("Sobre", "about", 8),
        ]:
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setIcon(QIcon(icon_path(icon)))
            button.setIconSize(QSize(19, 19))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(lambda _checked=False, i=page_index: self._navigate(i))
            side_layout.addWidget(button)
            self.nav_buttons.append(button)
            self.advanced_nav_buttons.append(button)
            self.nav_by_page[page_index] = button
        side_layout.addStretch()
        version = QLabel(f"Versão {APP_VERSION}")
        version.setObjectName("sidebarVersion")
        side_layout.addWidget(version)
        root_layout.addWidget(sidebar)

        main = QVBoxLayout()
        main.setContentsMargins(20, 16, 20, 14)
        main.setSpacing(12)
        root_layout.addLayout(main, 1)
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(14, 9, 14, 9)
        self.header_title = QLabel("Visão geral")
        self.header_title.setObjectName("headerTitle")
        self.current_test_label = QLabel("Nenhum ensaio ativo")
        self.current_test_label.setObjectName("muted")
        name_box = QVBoxLayout()
        name_box.addWidget(self.header_title)
        name_box.addWidget(self.current_test_label)
        top_layout.addLayout(name_box)
        top_layout.addStretch()
        self.mode_badge = StatusBadge("MODO REAL", "info")
        self.connection_badge = StatusBadge("Desconectado", "neutral")
        self.equipment_badge = StatusBadge("Aguardando dados", "neutral")
        self.clock_label = QLabel()
        self.user_label = QLabel(f"Usuário: {self.config.get('aplicacao.usuario', 'Operador')}")
        self.clock_label.setVisible(True)
        self.user_label.setVisible(True)
        self.user_label.setToolTip(
            f"Operador atual: {self.config.get('aplicacao.usuario', 'Operador')}"
        )
        top_layout.addWidget(self.mode_badge)
        top_layout.addWidget(self.connection_badge)
        top_layout.addWidget(self.equipment_badge)
        top_layout.addWidget(self.clock_label)
        top_layout.addWidget(self.user_label)
        main.addWidget(topbar)

        connection_bar = QFrame()
        connection_bar.setObjectName("connectionBar")
        connection_layout = QGridLayout(connection_bar)
        connection_layout.setContentsMargins(12, 8, 12, 8)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(190)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400"])
        self.baud_combo.setCurrentText(str(self.config.get("comunicacao.baud_rate", 115200)))
        refresh_ports = QPushButton("Atualizar portas")
        refresh_ports.clicked.connect(self._refresh_ports)
        self.connect_button = QPushButton("Conectar")
        self.connect_button.setObjectName("primary")
        self.connect_button.setIcon(QIcon(icon_path("connect")))
        self.connect_button.clicked.connect(self._toggle_serial)
        self.flow_port_combo = QComboBox()
        self.flow_connect_button = QPushButton("Conectar flowmeter")
        self.flow_connect_button.clicked.connect(self._toggle_flowmeter)
        self.simulation_button = QPushButton("Iniciar simulação")
        self.simulation_button.clicked.connect(self._toggle_simulation)
        self.sim_fault = QComboBox()
        self.sim_fault.addItem("Simulação normal", "normal")
        self.sim_fault.addItem("Sensor desconectado", "sensor")
        self.sim_fault.addItem("Corrente 3,7 mA", "abaixo")
        self.sim_fault.addItem("Corrente 3,2 mA", "critico_baixo")
        self.sim_fault.addItem("Corrente 20,2 mA", "acima")
        self.sim_fault.addItem("Corrente 21,0 mA", "critico_alto")
        self.sim_fault.addItem("Perda de comunicação", "perda")
        self.sim_fault.currentIndexChanged.connect(self._apply_sim_fault)
        connection_layout.addWidget(QLabel("ESP32"), 0, 0)
        connection_layout.addWidget(self.port_combo, 0, 1)
        connection_layout.addWidget(refresh_ports, 0, 2)
        connection_layout.addWidget(QLabel("Baud"), 0, 3)
        connection_layout.addWidget(self.baud_combo, 0, 4)
        connection_layout.addWidget(self.connect_button, 0, 5)
        connection_layout.addWidget(self.simulation_button, 0, 7)
        connection_layout.addWidget(self.sim_fault, 0, 8)
        connection_layout.addWidget(QLabel("Flowmeter USB–RS485"), 1, 0)
        connection_layout.addWidget(self.flow_port_combo, 1, 1, 1, 2)
        connection_layout.addWidget(self.flow_connect_button, 1, 3, 1, 3)
        connection_layout.setColumnStretch(6, 1)
        main.addWidget(connection_bar)

        self.stack = QStackedWidget()
        self.stack.setMinimumWidth(0)
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.overview = OverviewPage(self.config.data["sensores"])
        self.test_page = TestPage()
        self.calculations = CalculationPage(self.config.data)
        self.graphs = GraphsPage()
        self.graphs.set_units(
            str(self.config.get("sensores.pressao.unidade", "psi")),
            str(self.config.get("sensores.vazao.unidade", "NL/min")),
        )
        self.history = HistoryPage()
        self.calibration = CalibrationPage()
        self.settings = SettingsPage(self.config.data)
        self.diagnostics = DiagnosticsPage()
        self.about = AboutPage(APP_VERSION)
        for page in (
            self.overview,
            self.test_page,
            self.calculations,
            self.graphs,
            self.history,
            self.calibration,
            self.settings,
            self.diagnostics,
            self.about,
        ):
            self.stack.addWidget(page)
        # A 1360x728 display leaves less vertical space after the Windows
        # title bar.  Keep the navigation/header fixed and let the active
        # page scroll instead of clipping its lower controls and labels.
        page_scroll = QScrollArea()
        self.page_scroll = page_scroll
        page_scroll.setObjectName("pageScroll")
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        page_scroll.setWidget(self.stack)
        main.addWidget(page_scroll, 1)

    def _connect_signals(self) -> None:
        for page in (self.overview, self.test_page):
            page.start_requested.connect(self._start_test)
            page.pause_requested.connect(self._toggle_pause)
            page.finish_requested.connect(self._finish_test)
            page.marker_requested.connect(self._add_marker)
        self.overview.acknowledge_requested.connect(self._acknowledge_alarm)
        self.graphs.export_requested.connect(self._export_graph_png)
        self.calculations.save_requested.connect(self._save_calculation)
        self.history.search_requested.connect(self._refresh_history)
        self.history.open_requested.connect(self._open_test_details)
        self.history.export_requested.connect(self._export_test)
        self.history.delete_requested.connect(self._delete_test)
        self.history.invalidate_requested.connect(self._invalidate_test)
        self.calibration.save_requested.connect(self._save_calibration)
        self.calibration.sensor.currentIndexChanged.connect(self._refresh_calibration_history)
        self.settings.save_requested.connect(self._save_settings)
        self.diagnostics.copy_requested.connect(self._copy_diagnostics)
        self.diagnostics.reset_requested.connect(self.acquisition.reset_counters)
        self.diagnostics.db_test_requested.connect(self._test_database)
        self.diagnostics.export_test_requested.connect(self._test_export)
        self.diagnostics.open_logs_requested.connect(lambda: os.startfile(self.paths.logs))
        self.diagnostics.restart_requested.connect(self._restart_connection)
        self.acquisition.measurement_ready.connect(self._on_measurement)
        self.acquisition.pressure_updated.connect(self._on_pressure_updated)
        self.acquisition.flow_updated.connect(self._on_flow_updated)
        self.acquisition.alarm_raised.connect(self._on_alarm)
        self.acquisition.counters_changed.connect(self._update_counters)
        self.acquisition.timeout_detected.connect(self._on_timeout)

    def _load_style(self) -> None:
        style_path = Path(__file__).with_name("styles.qss")
        self.setStyleSheet(style_path.read_text(encoding="utf-8"))
        pg.setConfigOptions(
            antialias=True, foreground=COLORS["muted"], background=COLORS["surface"]
        )

    def _setup_timers(self) -> None:
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock_and_status)
        self.clock_timer.start(500)
        self._update_clock_and_status()

    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        titles = {
            0: "Visão geral",
            1: "Novo ensaio",
            2: "Cálculos",
            3: "Gráficos avançados",
            4: "Histórico de ensaios",
            5: "Calibração",
            6: "Configurações",
            7: "Diagnóstico",
            8: "Sobre",
        }
        self.header_title.setText(titles.get(index, "Supervisor"))
        button = self.nav_by_page.get(index)
        if button:
            button.setChecked(True)
        if index == 4:
            self._refresh_history()
        elif index == 5:
            self._refresh_calibration_history()
        elif index == 2:
            self._refresh_calculation_history()

    def _set_badge(self, label: QLabel, text: str, state: str) -> None:
        if isinstance(label, StatusBadge):
            label.set_state(text, state)
            return
        label.setText(text)
        label.setObjectName(
            {"good": "pillGood", "warn": "pillWarn", "bad": "pillBad"}.get(state, "pillNeutral")
        )
        label.style().unpolish(label)
        label.style().polish(label)

    def _refresh_ports(self) -> None:
        selected = self.port_combo.currentData()
        flow_selected = self.flow_port_combo.currentData()
        self.port_combo.clear()
        ports = available_port_details()
        configured = self.config.get("comunicacao.porta", "")
        configured_identity = self.config.get("comunicacao.identidade_porta", "")
        if configured_identity:
            configured = next(
                (p.device for p in ports if p.identity == configured_identity), configured
            )
        for port in ports:
            self.port_combo.addItem(f"{port.device} — {port.description}", port.device)
            self.port_combo.setItemData(
                self.port_combo.count() - 1, port.identity, Qt.ItemDataRole.UserRole + 1
            )
        if not ports:
            self.port_combo.addItem("Nenhum ESP32 detectado", "")
        self.flow_port_combo.clear()
        if ports:
            for port in ports:
                self.flow_port_combo.addItem(f"{port.device} — {port.description}", port.device)
                self.flow_port_combo.setItemData(
                    self.flow_port_combo.count() - 1, port.identity, Qt.ItemDataRole.UserRole + 1
                )
        else:
            self.flow_port_combo.addItem("Nenhum adaptador detectado", "")
        target = selected or configured
        for index in range(self.port_combo.count()):
            if self.port_combo.itemData(index) == target:
                self.port_combo.setCurrentIndex(index)
                break
        flow_configured = self.config.get("flowmeter.porta", "")
        flow_identity = self.config.get("flowmeter.identidade_porta", "")
        if flow_identity:
            flow_configured = next(
                (p.device for p in ports if p.identity == flow_identity), flow_configured
            )
        flow_target = flow_selected or flow_configured
        for index in range(self.flow_port_combo.count()):
            if self.flow_port_combo.itemData(index) == flow_target:
                self.flow_port_combo.setCurrentIndex(index)
                break
        serial_active = bool(self.serial_worker and self.serial_worker.isRunning())
        self.connect_button.setEnabled(bool(ports) or serial_active)
        self.statusBar().showMessage(
            f"{len(ports)} porta(s) encontrada(s)"
            if ports
            else "Conecte o ESP32 e clique em Atualizar",
            3000,
        )

    def _toggle_flowmeter(self) -> None:
        if self.flowmeter_worker and self.flowmeter_worker.isRunning():
            self._stop_flowmeter()
            return
        port = self.flow_port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Flowmeter", "Selecione a porta USB–RS485.")
            return
        if port == self.port_combo.currentData():
            QMessageBox.warning(
                self, "Flowmeter", "ESP32 e flowmeter precisam usar portas COM diferentes."
            )
            return
        self.config.data["flowmeter"]["porta"] = port
        self.config.data["flowmeter"]["identidade_porta"] = (
            self.flow_port_combo.currentData(Qt.ItemDataRole.UserRole + 1) or ""
        )
        self.config.save()
        try:
            self.flowmeter_worker = FlowmeterWorker(self.config.get("flowmeter", {}))
        except ValueError as exc:
            QMessageBox.critical(self, "Configuração do flowmeter", str(exc))
            return
        self.flowmeter_worker.reading_received.connect(self.acquisition.process_flow)
        self.flowmeter_worker.communication_error.connect(self.acquisition.process_flow_error)
        self.flowmeter_worker.state_changed.connect(self._on_flowmeter_state)
        self.flowmeter_worker.communication_error.connect(self._on_flowmeter_error)
        self.flowmeter_worker.statistics_changed.connect(self._on_flowmeter_statistics)
        self.flowmeter_worker.frame_logged.connect(self._on_modbus_frame)
        self.flowmeter_worker.start()
        self.flow_connect_button.setText("Desconectar flowmeter")

    def _stop_flowmeter(self) -> None:
        if self.flowmeter_worker:
            self.flowmeter_worker.stop()
            self.flowmeter_worker = None
        self.flow_connected = False
        self.acquisition.process_flow_error("SEM_COMUNICACAO")
        self.flow_connect_button.setText("Conectar flowmeter")

    def _on_flowmeter_state(self, connected: bool, message: str) -> None:
        self.flow_connected = connected
        self.overview.synoptic.set_flow_connection("OK" if connected else "DISCONNECTED")
        self.statusBar().showMessage(message, 5000)
        if connected:
            self.flow_connect_button.setText("Desconectar flowmeter")
        else:
            self.acquisition.process_flow_error("PORTA_DESCONECTADA")

    def _on_flowmeter_error(self, message: str) -> None:
        self.statusBar().showMessage(f"Flowmeter: {message}", 8000)
        self.diagnostics.values["flow_state"].setText(message)

    def _toggle_serial(self) -> None:
        if self.serial_worker and self.serial_worker.isRunning():
            self._stop_serial()
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Porta serial", "Selecione uma porta serial válida.")
            return
        if port == self.flow_port_combo.currentData():
            QMessageBox.warning(
                self, "Portas COM", "ESP32 e flowmeter precisam usar portas COM diferentes."
            )
            return
        self._stop_simulation()
        self.config.data["comunicacao"]["porta"] = port
        self.config.data["comunicacao"]["identidade_porta"] = (
            self.port_combo.currentData(Qt.ItemDataRole.UserRole + 1) or ""
        )
        self.config.save()
        self.serial_worker = SerialWorker(
            port,
            int(self.baud_combo.currentText()),
            reconnect=bool(self.config.get("comunicacao.reconexao_automatica", True)),
        )
        self.serial_worker.line_received.connect(self.acquisition.process_real)
        self.serial_worker.state_changed.connect(self._on_connection_state)
        self.serial_worker.communication_error.connect(self._on_serial_error)
        self.serial_worker.start()
        self.connect_button.setText("Desconectar")
        self.diagnostics.values["port"].setText(str(port))
        self.diagnostics.values["baud"].setText(self.baud_combo.currentText())

    def _stop_serial(self) -> None:
        if self.serial_worker:
            self.serial_worker.stop()
            self.serial_worker = None
        self.connect_button.setText("Conectar")
        self._on_connection_state(False, "Desconectado")

    def _toggle_simulation(self) -> None:
        if self.simulator and self.simulator.isRunning():
            self._stop_simulation()
            return
        self._stop_serial()
        self._stop_flowmeter()
        self.simulator = SimulatorWorker(
            float(self.config.get("simulacao.intervalo_s", 1.0)),
            float(self.config.get("simulacao.ruido", 0.03)),
        )
        self.simulator.line_generated.connect(self.acquisition.process_simulated)
        self.simulator.flow_generated.connect(self.acquisition.process_simulated_flow)
        self.simulator.state_changed.connect(self._on_simulation_state)
        self.simulator.start()
        self._apply_sim_fault()

    def _stop_simulation(self) -> None:
        if self.simulator:
            self.simulator.stop()
            self.simulator = None
        self.simulating = False
        self.simulation_button.setText("Iniciar simulação")
        self.overview.simulation_banner.hide()

    def _apply_sim_fault(self) -> None:
        if not self.simulator:
            return
        fault = self.sim_fault.currentData()
        self.simulator.sensor_disconnected = fault == "sensor"
        self.simulator.communication_loss = fault == "perda"
        self.simulator.current_fault = (
            fault if fault in ("abaixo", "critico_baixo", "acima", "critico_alto") else "normal"
        )

    def _on_connection_state(self, connected: bool, message: str) -> None:
        self.connected = connected
        self.overview.synoptic.set_pressure_connection("OK" if connected else "DISCONNECTED")
        self.acquisition.process_pressure_connection(connected, message)
        self._set_badge(
            self.connection_badge,
            "Conectado" if connected else "Desconectado",
            "good" if connected else "neutral",
        )
        self.diagnostics.values["connection"].setText(message)
        self.diagnostics.values["mode"].setText("Real")
        self.mode_badge.set_state("MODO REAL", "info")
        if not connected:
            self.connect_button.setText("Conectar")

    def _on_simulation_state(self, active: bool, message: str) -> None:
        self.simulating = active
        self.connected = active
        self.simulation_button.setText("Parar simulação" if active else "Iniciar simulação")
        self._set_badge(
            self.connection_badge,
            "Simulação ativa" if active else "Desconectado",
            "warn" if active else "neutral",
        )
        self.diagnostics.values["connection"].setText(message)
        self.diagnostics.values["mode"].setText("Simulação" if active else "—")
        self.mode_badge.set_state(
            "SIMULAÇÃO" if active else "MODO REAL", "warn" if active else "info"
        )
        self.overview.simulation_banner.setVisible(active)
        state = "SIMULATED" if active else "DISCONNECTED"
        self.overview.synoptic.set_pressure_connection(state)
        self.overview.synoptic.set_flow_connection(state)
        self.overview.synoptic.set_test_state("SIMULADO" if active else "AGUARDANDO")

    def _on_serial_error(self, message: str) -> None:
        logger.error("Erro serial: %s", message)
        self._set_badge(self.connection_badge, "Falha serial", "bad")
        self._on_alarm(
            self.acquisition.alarm_service.communication_alarm(f"Porta serial: {message}")
        )

    def _on_measurement(self, measurement: Measurement) -> None:
        self._last_firmware_version = measurement.firmware_version
        self.calculations.update_measurement(measurement)
        self.graphs.add_combined_measurement(measurement)
        self.diagnostics.raw.setPlainText(measurement.raw_message)
        self.diagnostics.values["ma_pressure"].setText(
            self._format_ma(measurement.pressure.current_ma)
        )
        self.diagnostics.values["flow_health"].setText("OK" if measurement.flow.valid else "Falha")
        self.diagnostics.values["reading_age"].setText("0.0 s")
        healthy = measurement.pressure.valid and measurement.flow.valid
        self._set_badge(
            self.equipment_badge,
            "Operação normal" if healthy else "Sensor em falha",
            "good" if healthy else "bad",
        )
        if self.test_service.current and measurement.recordable:
            try:
                recorded = self.test_service.record(measurement)
                if recorded:
                    self.test_page.add_measurement(measurement)
                    self.overview.samples.setText(str(self.test_service.current.sample_count))
            except Exception as exc:
                logger.exception("Falha ao registrar medição")
                self._set_badge(self.equipment_badge, "Falha de gravação", "bad")
                alarm = Alarm(
                    datetime.now(), "Banco", Severity.CRITICAL, "banco", f"Falha na gravação: {exc}"
                )
                self._on_alarm(alarm)

    def _on_pressure_updated(self, reading) -> None:
        if reading.timestamp:
            self.message_times.append(reading.timestamp)
        self.overview.update_pressure(reading)
        self.graphs.add_pressure(reading)
        pressure_only = Measurement(datetime.now(), pressure=reading, recordable=False)
        self.calibration.update_measurement(pressure_only)
        self.diagnostics.values["ma_pressure"].setText(self._format_ma(reading.current_ma))

    def _on_flow_updated(self, reading) -> None:
        self.overview.update_flow(reading)
        self.graphs.add_flow(reading)
        self.diagnostics.values["flow_health"].setText(
            reading.device_status or reading.quality.value
        )

    def _on_flowmeter_statistics(self, statistics: dict) -> None:
        summary = " | ".join(f"{key}: {value}" for key, value in statistics.items())
        self.diagnostics.values["modbus_stats"].setText(summary)
        self.overview.synoptic.set_diagnostics("flow", **statistics)

    def _on_modbus_frame(self, direction: str, frame: str) -> None:
        self.diagnostics.frames.appendPlainText(f"{datetime.now():%H:%M:%S.%f} {direction} {frame}")

    @staticmethod
    def _format_ma(value: float | None) -> str:
        return f"{value:.3f} mA" if value is not None else "—"

    def _on_alarm(self, alarm: Alarm | None) -> None:
        if alarm is None:
            return
        try:
            test_id = self.test_service.current.id if self.test_service.current else None
            alarm_id = self.event_repository.add_alarm(test_id, alarm)
            self.overview.add_alarm(alarm_id, alarm)
            if alarm.severity.value in ("alarme", "crítico"):
                self._set_badge(self.equipment_badge, alarm.severity.value.capitalize(), "bad")
                self.overview.synoptic.set_critical_alarm(alarm.severity.value == "crítico")
            elif alarm.severity.value == "atenção":
                self._set_badge(self.equipment_badge, "Atenção", "warn")
        except Exception:
            logger.exception("Não foi possível persistir o alarme")

    def _on_timeout(self, message: str) -> None:
        self._set_badge(self.equipment_badge, "Sem comunicação", "bad")
        self.diagnostics.values["last_age"].setText(message)

    def _update_counters(self, valid: int, invalid: int) -> None:
        self.diagnostics.values["valid"].setText(str(valid))
        self.diagnostics.values["invalid"].setText(str(invalid))
        self.overview.valid_count.setText(str(valid))
        self.overview.invalid_count.setText(str(invalid))

    def _start_test(self) -> None:
        if self.test_service.current:
            QMessageBox.information(
                self, "Ensaio ativo", "Finalize o ensaio atual antes de iniciar outro."
            )
            return
        if self.simulating:
            response = QMessageBox.question(
                self,
                "Ensaio simulado",
                "Os dados não vêm do equipamento real e o relatório será marcado como SIMULADO. Continuar?",
            )
            if response != QMessageBox.StandardButton.Yes:
                return
        else:
            preflight = run_preflight(
                self.config.data,
                self.acquisition.preflight_snapshot(),
                esp32_connected=self.connected,
                flowmeter_connected=self.flow_connected,
                database_writable=self.database.writable_check(),
                configuration_errors=self.config.real_mode_errors(),
                calibration_available=self.calibration_repository.active_exists("pressao"),
            )
            if not preflight.ok:
                QMessageBox.critical(
                    self,
                    "Preflight reprovado",
                    "Corrija os itens abaixo antes do ensaio real:\n\n• "
                    + "\n• ".join(preflight.errors),
                )
                return
        dialog = TestSetupDialog(
            self.test_repository.next_code(),
            Path(self.config.get("dados.diretorio_exportacao") or self.paths.exports),
            self,
            pressure_unit=str(self.config.get("sensores.pressao.unidade", "psi")),
            flow_unit=str(self.config.get("flowmeter.unit", "L/min")),
            expected_pressure_range=(
                f"{self.config.get('sensores.pressao.limite_inferior', 0):g}–"
                f"{self.config.get('sensores.pressao.limite_superior', 400):g} "
                f"{self.config.get('sensores.pressao.unidade', 'psi')}"
            ),
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            definition = dialog.definition()
            if definition.flow_unit != self.acquisition.latest_flow.unit:
                QMessageBox.warning(
                    self,
                    "Unidade de vazão",
                    f"Selecione {self.acquisition.latest_flow.unit}, a unidade recebida do flowmeter.",
                )
                return
            definition.configuration_snapshot = json.dumps(
                self.config.data, ensure_ascii=False, sort_keys=True
            )
            definition.firmware_version = getattr(self, "_last_firmware_version", "")
            definition.simulated = self.simulating
            session = self.test_service.start(definition)
            self.graphs.reset()
            self.graphs.set_units(definition.pressure_unit, definition.flow_unit)
            self.test_page.reset()
            self.test_page.set_session(session)
            self.calculations.set_session(session.definition, "active")
            self.calculation_test_id = session.id
            self.overview.reset_test()
            self.overview.set_test_active(True)
            self.overview.synoptic.set_sample(
                session.definition.code, session.definition.sample_name
            )
            self.current_test_label.setText(
                f"{session.definition.code} — {session.definition.sample_name}"
            )
            self._navigate(0)
            self.nav_by_page[0].setChecked(True)
        except Exception as exc:
            logger.exception("Falha ao criar ensaio")
            QMessageBox.critical(self, "Novo ensaio", f"Não foi possível iniciar:\n{exc}")

    def _toggle_pause(self) -> None:
        if not self.test_service.current:
            return
        status = self.test_service.toggle_pause()
        paused = status == TestStatus.PAUSED
        self.overview.set_test_active(True, paused)
        self.test_page.set_session(self.test_service.current)

    def _finish_test(self) -> None:
        if not self.test_service.current:
            return
        response = QMessageBox.question(
            self,
            "Finalizar ensaio",
            "Deseja finalizar o ensaio? Após finalizar, novas leituras não serão registradas.",
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        note, accepted = QInputDialog.getMultiLineText(
            self, "Observação final", "Observação final (opcional):"
        )
        if not accepted:
            return
        try:
            # Persiste a última combinação pendente antes de encerrar a sessão.
            # O sinal é entregue de forma síncrona na thread da interface e cada
            # gravação termina sua transação antes de o relatório ser iniciado.
            self.acquisition.emit_combined_measurement()
            pending = self.calculations.pending_results()
            if pending:
                save_response = QMessageBox.question(
                    self,
                    "Resultados não salvos",
                    "Há resultados de permeabilidade calculados e ainda não salvos. "
                    "Deseja salvá-los antes de gerar o relatório?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes,
                )
                if save_response == QMessageBox.StandardButton.Cancel:
                    return
                if save_response == QMessageBox.StandardButton.Yes:
                    test_id = self.test_service.current.id
                    for kind, inputs, results, observations in pending:
                        self.calculation_repository.save(
                            test_id, kind, inputs, results, observations
                        )
                        self.calculations.mark_saved(kind)
            session = self.test_service.finish(note)
            self.overview.set_test_active(False)
            self.current_test_label.setText("Nenhum ensaio ativo")
            self.calculation_test_id = session.id
            self.calculations.set_session(session.definition, "history")
            self._refresh_history()
            report_directory = Path(session.definition.export_directory or self.paths.exports)
            self._start_report_export(session.id, report_directory)
            QMessageBox.information(
                self,
                "Ensaio finalizado",
                f"Ensaio {session.definition.code} salvo com {session.sample_count} amostras.\n\n"
                "Gerando relatório… Você pode continuar usando o aplicativo.",
            )
        except Exception as exc:
            logger.exception("Falha ao finalizar ensaio")
            QMessageBox.critical(self, "Finalizar ensaio", str(exc))

    def _add_marker(self) -> None:
        if not self.test_service.current:
            return
        dialog = MarkerDialog(self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.test_service.add_marker(
                dialog.category.currentText(), dialog.comment.toPlainText().strip()
            )
            self.statusBar().showMessage("Marcação registrada", 3000)

    def _acknowledge_alarm(self, alarm_id: int) -> None:
        note, accepted = QInputDialog.getText(
            self, "Reconhecer alarme", "Observação do operador (opcional):"
        )
        if accepted:
            self.event_repository.acknowledge(alarm_id, note)

    def _refresh_history(self, search: str = "") -> None:
        self.history.populate(self.test_repository.list(search))

    def _open_test_details(self, test_id: int) -> None:
        row = self.test_repository.get(test_id)
        if not row:
            return
        measurements = self.test_repository.measurements(test_id)
        alarms = self.event_repository.alarms(test_id)
        markers = self.event_repository.markers(test_id)
        QMessageBox.information(
            self,
            f"Ensaio {row['codigo']}",
            f"Amostra: {row['amostra_nome']}\nOperador: {row['operador']}\n"
            f"Início: {row['inicio']}\nStatus: {row['status']}\n"
            f"Medições: {len(measurements)}\nAlarmes: {len(alarms)}\nMarcações: {len(markers)}\n\n"
            f"Observações: {row['observacao_final'] or row['observacoes'] or '—'}",
        )
        definition = self._definition_from_record(row)
        self.calculation_test_id = test_id
        self.calculations.set_session(definition, "history")
        self._refresh_calculation_history()
        calculations = self.calculation_repository.list(test_id)
        self.graphs.load_history(
            test_id,
            measurements,
            calculations,
            row["unidade_pressao"] or "psi",
            row["unidade_vazao"] or "não registrada",
        )
        self._navigate(3)
        self.nav_by_page[3].setChecked(True)
        self.statusBar().showMessage(
            f"Ensaio histórico {row['codigo']} aberto em modo somente leitura", 6000
        )

    @staticmethod
    def _definition_from_record(row) -> object:
        from core.models import TestDefinition

        return TestDefinition(
            code=row["codigo"],
            sample_name=row["amostra_nome"],
            sample_identification=row["amostra_identificacao"] or "",
            operator=row["operador"],
            description=row["descricao"] or "",
            test_type=row["tipo"] or "Permeabilidade",
            notes=row["observacoes"] or "",
            expected_pressure_range=row["faixa_pressao"] or "",
            pressure_unit=row["unidade_pressao"] or "bar",
            flow_unit=row["unidade_vazao"] or "não registrada",
            acquisition_interval=row["intervalo_aquisicao"] or 1.0,
            export_directory=row["diretorio_exportacao"] or "",
            sample_length_mm=row["comprimento_amostra_mm"],
            sample_diameter_mm=row["diametro_amostra_mm"],
            sample_mass_g=row["massa_amostra_g"],
            bulk_volume_cm3=row["volume_geometrico_cm3"],
            gas_type=row["tipo_gas"] or "Helio",
            temperature_c=row["temperatura_c"] or 20.0,
            atmospheric_pressure_kpa=row["pressao_atmosferica_kpa"] or 101.325,
            pressure_reference=row["referencia_pressao"] or "manometrica",
            configuration_snapshot=row["configuracao_json"] or "",
            firmware_version=row["versao_firmware"] or "",
            simulated=bool(row["simulado"]),
        )

    def _save_calculation(
        self, calculation_type: str, inputs: dict, results: dict, notes: str
    ) -> None:
        if (
            self.calculation_test_id is None
            or not self.test_service.current
            or self.test_service.current.id != self.calculation_test_id
        ):
            QMessageBox.warning(
                self,
                "Salvar cálculo",
                "Somente o ensaio ativo pode receber novos cálculos. Ensaios históricos são somente leitura.",
            )
            return
        try:
            self.calculation_repository.save(
                self.calculation_test_id, calculation_type, inputs, results, notes
            )
            self.calculations.mark_saved(calculation_type)
            self._refresh_calculation_history()
            self.graphs.load_calculations(
                self.calculation_repository.list(self.calculation_test_id)
            )
            QMessageBox.information(self, "Cálculos", "Resultado salvo no ensaio.")
        except Exception as exc:
            logger.exception("Falha ao salvar cálculo")
            QMessageBox.critical(self, "Salvar cálculo", str(exc))

    def _refresh_calculation_history(self) -> None:
        rows = (
            self.calculation_repository.list(self.calculation_test_id)
            if self.calculation_test_id is not None
            else []
        )
        self.calculations.populate_history(rows)

    def _export_test(self, test_id: int, format_name: str) -> None:
        row = self.test_repository.get(test_id)
        if not row:
            return
        default = (
            row["diretorio_exportacao"]
            or self.config.get("dados.diretorio_exportacao")
            or self.paths.exports
        )
        directory = QFileDialog.getExistingDirectory(self, "Diretório de exportação", str(default))
        if not directory:
            return
        method = {
            "csv": self.export_service.export_csv,
            "xlsx": self.export_service.export_xlsx,
            "json": self.export_service.export_json,
            "pdf": self.export_service.export_pdf,
        }[format_name]
        args: tuple[object, ...] = (
            (test_id, Path(directory), self.config.get("dados.separador_csv", ";"))
            if format_name == "csv"
            else (test_id, Path(directory))
        )
        if test_id in self.exporting_test_ids:
            QMessageBox.information(
                self, "Exportação em andamento", "Este ensaio já está sendo exportado."
            )
            return
        worker = ExportWorker(method, args)
        self.export_workers.add(worker)
        self.exporting_test_ids.add(test_id)
        worker.completed.connect(
            lambda target: QMessageBox.information(
                self, "Exportação concluída", f"Arquivo salvo em:\n{target}"
            )
        )
        worker.failed.connect(
            lambda error: QMessageBox.critical(self, "Falha na exportação", error)
        )
        worker.finished.connect(lambda: self.export_workers.discard(worker))
        worker.finished.connect(lambda: self.exporting_test_ids.discard(test_id))
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self.statusBar().showMessage("Exportação em andamento…", 3000)

    def _delete_test(self, test_id: int) -> None:
        row = self.test_repository.get(test_id)
        if not row:
            return
        response = QMessageBox.warning(
            self,
            "Excluir ensaio",
            f"Excluir permanentemente {row['codigo']} e todas as suas medições?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            self.test_repository.delete(test_id)
            self._refresh_history()

    def _invalidate_test(self, test_id: int) -> None:
        if (
            QMessageBox.question(
                self, "Marcar como inválido", "Manter os dados e marcar este ensaio como inválido?"
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.test_repository.invalidate(test_id)
            self._refresh_history()

    def _save_calibration(
        self,
        sensor: str,
        gain: float,
        offset: float,
        error: float,
        stable: bool,
        points: list[tuple[float, float]],
        notes: str,
    ) -> None:
        if (
            not stable
            and QMessageBox.warning(
                self,
                "Calibração instável",
                "As amostras foram classificadas como instáveis. Deseja salvar mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        operator = self.calibration.operator.text().strip() or "Operador"
        self.calibration_repository.save(
            sensor, operator, gain, offset, error, stable, points, notes
        )
        self.config.set(f"sensores.{sensor}.ganho", gain)
        self.config.set(f"sensores.{sensor}.offset", offset)
        self._refresh_calibration_history()
        QMessageBox.information(self, "Calibração", "Calibração salva e ativada.")

    def _refresh_calibration_history(self) -> None:
        sensor = self.calibration.sensor.currentData()
        if sensor:
            self.calibration.populate_history(self.calibration_repository.history(sensor))

    def _save_settings(self, values: dict[str, Any]) -> None:
        try:
            ConfigManager._deep_update(self.config.data, values)
            self.config.save()
            self.graphs.set_units(
                str(self.config.get("sensores.pressao.unidade", "psi")),
                str(self.config.get("sensores.vazao.unidade", "NL/min")),
            )
            QMessageBox.information(
                self,
                "Configurações",
                "Configurações salvas. As alterações dos sensores serão aplicadas na próxima inicialização.",
            )
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Configurações inválidas", str(exc))

    def _export_graph_png(self, mode: str = "individual") -> None:
        items = self.graphs.export_items(mode)
        if mode == "individual":
            name, item = items[0]
            filename, _ = QFileDialog.getSaveFileName(
                self, "Exportar gráfico", str(self.paths.exports / f"{name}.png"), "PNG (*.png)"
            )
            if not filename:
                return
            ImageExporter(item).export(filename)
            self.statusBar().showMessage(f"Gráfico salvo em {filename}", 4000)
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Exportar todos os gráficos", str(self.paths.exports)
        )
        if not directory:
            return
        for name, item in items:
            ImageExporter(item).export(str(Path(directory) / f"{name}.png"))
        self.statusBar().showMessage(f"Gráficos salvos em {directory}", 4000)

    def _start_report_export(self, test_id: int, directory: Path) -> None:
        if test_id in self.exporting_test_ids:
            return
        worker = ExportWorker(self.export_service.export_pdf, (test_id, directory))
        self.export_workers.add(worker)
        self.exporting_test_ids.add(test_id)

        def completed(target: str) -> None:
            self.overview.set_report_ready(True)
            self.statusBar().showMessage(f"Relatório salvo em {target}", 8000)
            QMessageBox.information(self, "Relatório concluído", f"Relatório salvo em:\n{target}")

        def failed(error: str) -> None:
            self.overview.set_report_ready(False)
            logger.error("Falha ao gerar relatório do ensaio %s: %s", test_id, error)
            QMessageBox.critical(
                self,
                "Falha no relatório",
                "O ensaio foi finalizado e permanece salvo. O PDF pode ser gerado "
                f"novamente pelo histórico.\n\nDetalhes: {error}",
            )

        worker.completed.connect(completed)
        worker.failed.connect(failed)
        worker.finished.connect(lambda: self.export_workers.discard(worker))
        worker.finished.connect(lambda: self.exporting_test_ids.discard(test_id))
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self.statusBar().showMessage("Gerando relatório…")

    def _copy_diagnostics(self) -> None:
        QApplication.clipboard().setText(self.diagnostics.report_text())
        self.statusBar().showMessage("Diagnóstico copiado", 2500)

    def _test_database(self) -> None:
        ok = self.database.health_check()
        QMessageBox.information(
            self, "Teste do banco", "Leitura e conexão bem-sucedidas." if ok else "Falha no banco."
        )

    def _test_export(self) -> None:
        rows = self.test_repository.list()
        if not rows:
            QMessageBox.information(self, "Teste de exportação", "Crie um ensaio antes de testar.")
            return
        try:
            target = self.export_service.export_csv(
                rows[0]["id"], self.paths.exports, self.config.get("dados.separador_csv", ";")
            )
            QMessageBox.information(self, "Teste de exportação", f"Teste concluído:\n{target}")
        except Exception as exc:
            QMessageBox.critical(self, "Teste de exportação", str(exc))

    def _restart_connection(self) -> None:
        was_simulating = self.simulating
        had_serial = bool(self.serial_worker)
        had_flowmeter = bool(self.flowmeter_worker)
        self._stop_serial()
        self._stop_flowmeter()
        self._stop_simulation()
        if was_simulating:
            self._toggle_simulation()
            return
        if had_serial and self.port_combo.currentData():
            self._toggle_serial()
        if had_flowmeter and self.flow_port_combo.currentData():
            self._toggle_flowmeter()

    def _update_clock_and_status(self) -> None:
        now = datetime.now()
        self.clock_label.setText(now.strftime("%d/%m/%Y  %H:%M:%S"))
        if self.test_service.current:
            seconds = int(self.test_service.elapsed_seconds())
            self.overview.duration.setText(
                f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
            )
            self.overview.synoptic.set_runtime(
                self.overview.duration.text(), self.test_service.current.sample_count
            )
            self.test_page.labels["duration"].setText(self.overview.duration.text())
        frequency = 0.0
        if len(self.message_times) > 1:
            elapsed = (self.message_times[-1] - self.message_times[0]).total_seconds()
            frequency = (len(self.message_times) - 1) / elapsed if elapsed > 0 else 0.0
        self.overview.rate.setText(f"{frequency:.2f} Hz" if frequency else "— Hz")
        self.diagnostics.values["frequency"].setText(f"{frequency:.3f} Hz")
        if self.acquisition.last_message_at:
            age = (now - self.acquisition.last_message_at).total_seconds()
            self.diagnostics.values["last_age"].setText(f"{age:.1f} s")
            self.diagnostics.values["reading_age"].setText(f"{age:.1f} s")
        for card in self.overview.cards.values():
            card.refresh_age()
        self.diagnostics.values["database"].setText(
            "Operacional" if self.database.health_check() else "Falha"
        )
        self.diagnostics.values["db_path"].setText(str(self.database.path))
        self.diagnostics.values["version"].setText(APP_VERSION)
        try:
            free = shutil.disk_usage(self.database.path.parent).free / (1024**3)
            self.diagnostics.values["disk"].setText(f"{free:.1f} GB livres")
        except OSError:
            self.diagnostics.values["disk"].setText("Indisponível")

    def closeEvent(self, event: QCloseEvent) -> None:
        running_exports = [worker for worker in self.export_workers if worker.isRunning()]
        if running_exports:
            QMessageBox.information(
                self,
                "Exportação em andamento",
                "Aguarde a exportação terminar antes de fechar o aplicativo.",
            )
            event.ignore()
            return
        if self.test_service.current:
            response = QMessageBox.warning(
                self,
                "Ensaio em andamento",
                "Há um ensaio ativo. Fechar agora preservará os dados e o marcará como interrompido.\n\n"
                "Deseja realmente sair?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            interrupted = self.test_repository.mark_interrupted_tests()
            logger.warning(
                "Encerramento com %s ensaio(s) marcado(s) como interrompido(s)", interrupted
            )
        self._stop_serial()
        self._stop_flowmeter()
        self._stop_simulation()
        self.acquisition.stop()
        self.database.close()
        event.accept()
