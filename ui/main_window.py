from __future__ import annotations

import logging
import json
import os
import shutil
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from communication.serial_manager import SerialWorker, available_ports
from communication.simulator import SimulatorWorker
from config.settings import AppPaths, ConfigManager
from core.constants import Severity, TestStatus
from core.models import Alarm, Measurement
from database.database import Database
from database.repositories import (
    CalculationRepository,
    CalibrationRepository,
    EventRepository,
    TestRepository,
)
from services.acquisition_service import AcquisitionService
from services.export_service import ExportService
from services.test_service import TestService
from ui.dialogs.marker_dialog import MarkerDialog
from ui.dialogs.test_dialog import TestSetupDialog
from ui.workers import ExportWorker
from ui.calculation_page import CalculationPage
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
from ui.theme import COLORS, icon_path
from ui.resources import branding_path
from ui.widgets.components import StatusBadge

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
        self.simulator: SimulatorWorker | None = None
        self.connected = False
        self.simulating = False
        self.export_workers: set[ExportWorker] = set()
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
        self.setWindowTitle("Supervisor de Porosímetro")
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
        brand.setPixmap(QPixmap(str(branding_path("ism_simbolo_transparente.png"))).scaled(
            82, 58, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        brand.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        brand_name = QLabel("POROSÍMETRO SUPERVISÓRIO")
        brand_name.setObjectName("brandName")
        side_layout.addWidget(brand)
        side_layout.addWidget(brand_name)
        side_layout.addSpacing(16)
        section = QLabel("OPERAÇÃO")
        section.setObjectName("sidebarCaption")
        side_layout.addWidget(section)
        self.nav_buttons: list[QPushButton] = []
        self.nav_by_page: dict[int, QPushButton] = {}
        nav_items = [
            ("Visão geral", "overview", 0), ("Novo ensaio", "new_test", 1),
            ("Histórico", "history", 4), ("Cálculos", "calculations", 2),
            ("Calibração", "calibration", 5), ("Configurações", "settings", 6),
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
        advanced = QLabel("FERRAMENTAS")
        advanced.setObjectName("sidebarCaption")
        side_layout.addWidget(advanced)
        for text, icon, page_index in [("Gráficos avançados", "graphs", 3), ("Diagnóstico", "diagnostics", 7), ("Sobre", "about", 8)]:
            button = QPushButton(text); button.setObjectName("navButton")
            button.setIcon(QIcon(icon_path(icon))); button.setIconSize(QSize(19, 19))
            button.setCheckable(True); button.setAutoExclusive(True)
            button.clicked.connect(lambda _checked=False, i=page_index: self._navigate(i))
            side_layout.addWidget(button); self.nav_buttons.append(button); self.nav_by_page[page_index] = button
        side_layout.addStretch()
        version = QLabel(f"Versão {self.config.get('aplicacao.versao', '1.0.0')}")
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
        self.clock_label.setVisible(False)
        self.user_label.setVisible(False)
        self.user_label.setToolTip(f"Operador atual: {self.config.get('aplicacao.usuario', 'Operador')}")
        top_layout.addWidget(self.mode_badge)
        top_layout.addWidget(self.connection_badge)
        top_layout.addWidget(self.equipment_badge)
        top_layout.addWidget(self.clock_label)
        top_layout.addWidget(self.user_label)
        main.addWidget(topbar)

        connection_bar = QFrame()
        connection_bar.setObjectName("connectionBar")
        connection_layout = QHBoxLayout(connection_bar)
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
        connection_layout.addWidget(QLabel("Porta"))
        connection_layout.addWidget(self.port_combo)
        connection_layout.addWidget(refresh_ports)
        connection_layout.addWidget(QLabel("Baud"))
        connection_layout.addWidget(self.baud_combo)
        connection_layout.addWidget(self.connect_button)
        connection_layout.addStretch()
        connection_layout.addWidget(self.simulation_button)
        connection_layout.addWidget(self.sim_fault)
        main.addWidget(connection_bar)

        self.stack = QStackedWidget()
        self.overview = OverviewPage(self.config.data["sensores"])
        self.test_page = TestPage()
        self.calculations = CalculationPage(self.config.data)
        self.graphs = GraphsPage()
        self.history = HistoryPage()
        self.calibration = CalibrationPage()
        self.settings = SettingsPage(self.config.data)
        self.diagnostics = DiagnosticsPage()
        self.about = AboutPage(self.config.get("aplicacao.versao", "2.0.0"))
        for page in (
            self.overview, self.test_page, self.calculations, self.graphs, self.history,
            self.calibration, self.settings, self.diagnostics, self.about,
        ):
            self.stack.addWidget(page)
        main.addWidget(self.stack, 1)

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
        self.acquisition.alarm_raised.connect(self._on_alarm)
        self.acquisition.counters_changed.connect(self._update_counters)
        self.acquisition.timeout_detected.connect(self._on_timeout)

    def _load_style(self) -> None:
        style_path = Path(__file__).with_name("styles.qss")
        self.setStyleSheet(style_path.read_text(encoding="utf-8"))
        pg.setConfigOptions(antialias=True, foreground=COLORS["muted"], background=COLORS["surface"])

    def _setup_timers(self) -> None:
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock_and_status)
        self.clock_timer.start(500)
        self._update_clock_and_status()

    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        titles = {0: "Visão geral", 1: "Novo ensaio", 2: "Cálculos", 3: "Gráficos avançados", 4: "Histórico de ensaios", 5: "Calibração", 6: "Configurações", 7: "Diagnóstico", 8: "Sobre"}
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
        label.setObjectName({
            "good": "pillGood", "warn": "pillWarn", "bad": "pillBad"
        }.get(state, "pillNeutral"))
        label.style().unpolish(label)
        label.style().polish(label)

    def _refresh_ports(self) -> None:
        selected = self.port_combo.currentData()
        self.port_combo.clear()
        ports = available_ports()
        configured = self.config.get("comunicacao.porta", "")
        for device, description in ports:
            self.port_combo.addItem(f"{device} — {description}", device)
        if not ports:
            self.port_combo.addItem("Nenhuma porta detectada", "")
        target = selected or configured
        for index in range(self.port_combo.count()):
            if self.port_combo.itemData(index) == target:
                self.port_combo.setCurrentIndex(index)
                break

    def _toggle_serial(self) -> None:
        if self.serial_worker and self.serial_worker.isRunning():
            self._stop_serial()
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Porta serial", "Selecione uma porta serial válida.")
            return
        self._stop_simulation()
        self.serial_worker = SerialWorker(port, int(self.baud_combo.currentText()), reconnect=bool(self.config.get("comunicacao.reconexao_automatica", True)))
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
        self.simulator = SimulatorWorker(
            float(self.config.get("simulacao.intervalo_s", 1.0)),
            float(self.config.get("simulacao.ruido", 0.03)),
        )
        self.simulator.line_generated.connect(self.acquisition.process_simulated)
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
        self.simulator.current_fault = fault if fault in (
            "abaixo", "critico_baixo", "acima", "critico_alto"
        ) else "normal"

    def _on_connection_state(self, connected: bool, message: str) -> None:
        self.connected = connected
        self._set_badge(self.connection_badge, "Conectado" if connected else "Desconectado",
                        "good" if connected else "neutral")
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
            self.connection_badge, "Simulação ativa" if active else "Desconectado",
            "warn" if active else "neutral",
        )
        self.diagnostics.values["connection"].setText(message)
        self.diagnostics.values["mode"].setText("Simulação" if active else "—")
        self.mode_badge.set_state("SIMULAÇÃO" if active else "MODO REAL", "warn" if active else "info")
        self.overview.simulation_banner.setVisible(active)

    def _on_serial_error(self, message: str) -> None:
        logger.error("Erro serial: %s", message)
        self._set_badge(self.connection_badge, "Falha serial", "bad")
        self._on_alarm(
            self.acquisition.alarm_service.communication_alarm(f"Porta serial: {message}")
        )

    def _on_measurement(self, measurement: Measurement) -> None:
        self.message_times.append(measurement.received_at)
        self.overview.update_measurement(measurement)
        self.graphs.add_measurement(measurement)
        self.calibration.update_measurement(measurement)
        self.calculations.update_measurement(measurement)
        self.diagnostics.raw.setPlainText(measurement.raw_message)
        self.diagnostics.values["ma_pressure"].setText(self._format_ma(measurement.pressure.current_ma))
        self._last_firmware_version = measurement.firmware_version
        self.diagnostics.values["flow_health"].setText("OK" if measurement.flow.valid else "Falha")
        self.diagnostics.values["reading_age"].setText("0.0 s")
        healthy = measurement.pressure.valid and measurement.flow.valid
        self._set_badge(self.equipment_badge, "Operação normal" if healthy else "Sensor em falha", "good" if healthy else "bad")
        if self.test_service.current:
            try:
                recorded = self.test_service.record(measurement)
                if recorded:
                    self.test_page.add_measurement(measurement)
                    self.overview.samples.setText(str(self.test_service.current.sample_count))
            except Exception as exc:
                logger.exception("Falha ao registrar medição")
                self._set_badge(self.equipment_badge, "Falha de gravação", "bad")
                alarm = Alarm(
                    datetime.now(), "Banco", Severity.CRITICAL, "banco",
                    f"Falha na gravação: {exc}"
                )
                self._on_alarm(alarm)

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
            QMessageBox.information(self, "Ensaio ativo", "Finalize o ensaio atual antes de iniciar outro.")
            return
        if self.simulating:
            response = QMessageBox.question(
                self, "Ensaio simulado",
                "Os dados não vêm do equipamento real e o relatório será marcado como SIMULADO. Continuar?",
            )
            if response != QMessageBox.StandardButton.Yes:
                return
        else:
            errors = self.config.real_mode_errors()
            if errors:
                QMessageBox.critical(self, "Configuração real incompleta", "Não é seguro iniciar o ensaio real:\n\n• " + "\n• ".join(errors))
                return
        dialog = TestSetupDialog(
            self.test_repository.next_code(),
            Path(self.config.get("dados.diretorio_exportacao") or self.paths.exports),
            self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            definition = dialog.definition()
            definition.configuration_snapshot = json.dumps(self.config.data, ensure_ascii=False, sort_keys=True)
            definition.firmware_version = getattr(self, "_last_firmware_version", "")
            definition.simulated = self.simulating
            session = self.test_service.start(definition)
            self.graphs.reset()
            self.test_page.reset()
            self.test_page.set_session(session)
            self.calculations.set_session(session.definition)
            self.calculation_test_id = session.id
            self.overview.reset_test()
            self.overview.set_test_active(True)
            self.current_test_label.setText(f"{session.definition.code} — {session.definition.sample_name}")
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
            self, "Finalizar ensaio",
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
            session = self.test_service.finish(note)
            self.overview.set_test_active(False)
            self.current_test_label.setText("Nenhum ensaio ativo")
            self.calculation_test_id = session.id
            self.calculations.set_session(session.definition)
            self._refresh_history()
            export = QMessageBox.question(
                self, "Ensaio finalizado",
                f"Ensaio {session.definition.code} salvo com {session.sample_count} amostras.\n\n"
                "Deseja exportar o relatório XLSX agora?",
            )
            if export == QMessageBox.StandardButton.Yes:
                self._export_test(session.id, "xlsx")
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
            self, f"Ensaio {row['codigo']}",
            f"Amostra: {row['amostra_nome']}\nOperador: {row['operador']}\n"
            f"Início: {row['inicio']}\nStatus: {row['status']}\n"
            f"Medições: {len(measurements)}\nAlarmes: {len(alarms)}\nMarcações: {len(markers)}\n\n"
            f"Observações: {row['observacao_final'] or row['observacoes'] or '—'}",
        )
        definition = self._definition_from_record(row)
        self.calculation_test_id = test_id
        self.calculations.set_session(definition)
        self._refresh_calculation_history()
        self._navigate(2)
        self.nav_by_page[2].setChecked(True)

    @staticmethod
    def _definition_from_record(row) -> object:
        from core.models import TestDefinition

        return TestDefinition(
            code=row["codigo"], sample_name=row["amostra_nome"],
            sample_identification=row["amostra_identificacao"] or "",
            operator=row["operador"], description=row["descricao"] or "",
            test_type=row["tipo"] or "Porosimetria por gás", notes=row["observacoes"] or "",
            expected_pressure_range=row["faixa_pressao"] or "",
            pressure_unit=row["unidade_pressao"] or "bar",
            flow_unit=row["unidade_vazao"] or "L/min",
            acquisition_interval=row["intervalo_aquisicao"] or 1.0,
            export_directory=row["diretorio_exportacao"] or "",
            sample_length_mm=row["comprimento_amostra_mm"],
            sample_diameter_mm=row["diametro_amostra_mm"],
            sample_mass_g=row["massa_amostra_g"], bulk_volume_cm3=row["volume_geometrico_cm3"],
            gas_type=row["tipo_gas"] or "Helio", temperature_c=row["temperatura_c"] or 20.0,
            atmospheric_pressure_kpa=row["pressao_atmosferica_kpa"] or 101.325,
            pressure_reference=row["referencia_pressao"] or "manometrica",
            configuration_snapshot=row["configuracao_json"] or "",
            firmware_version=row["versao_firmware"] or "",
            simulated=bool(row["simulado"]),
        )

    def _save_calculation(
        self, calculation_type: str, inputs: dict, results: dict, notes: str
    ) -> None:
        if self.calculation_test_id is None:
            QMessageBox.warning(
                self, "Salvar cálculo",
                "Inicie um ensaio ou abra um ensaio do histórico antes de salvar.",
            )
            return
        try:
            self.calculation_repository.save(
                self.calculation_test_id, calculation_type, inputs, results, notes
            )
            self._refresh_calculation_history()
            QMessageBox.information(self, "Cálculos", "Resultado salvo no ensaio.")
        except Exception as exc:
            logger.exception("Falha ao salvar cálculo")
            QMessageBox.critical(self, "Salvar cálculo", str(exc))

    def _refresh_calculation_history(self) -> None:
        rows = (
            self.calculation_repository.list(self.calculation_test_id)
            if self.calculation_test_id is not None else []
        )
        self.calculations.populate_history(rows)

    def _export_test(self, test_id: int, format_name: str) -> None:
        row = self.test_repository.get(test_id)
        if not row:
            return
        default = row["diretorio_exportacao"] or self.config.get(
            "dados.diretorio_exportacao"
        ) or self.paths.exports
        directory = QFileDialog.getExistingDirectory(self, "Diretório de exportação", str(default))
        if not directory:
            return
        method = {"csv": self.export_service.export_csv, "xlsx": self.export_service.export_xlsx, "json": self.export_service.export_json, "pdf": self.export_service.export_pdf}[format_name]
        args: tuple[object, ...] = (test_id, Path(directory), self.config.get("dados.separador_csv", ";")) if format_name == "csv" else (test_id, Path(directory))
        worker = ExportWorker(method, args)
        self.export_workers.add(worker)
        worker.completed.connect(lambda target: QMessageBox.information(self, "Exportação concluída", f"Arquivo salvo em:\n{target}"))
        worker.failed.connect(lambda error: QMessageBox.critical(self, "Falha na exportação", error))
        worker.finished.connect(lambda: self.export_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self.statusBar().showMessage("Exportação em andamento…", 3000)

    def _delete_test(self, test_id: int) -> None:
        row = self.test_repository.get(test_id)
        if not row:
            return
        response = QMessageBox.warning(
            self, "Excluir ensaio",
            f"Excluir permanentemente {row['codigo']} e todas as suas medições?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            self.test_repository.delete(test_id)
            self._refresh_history()

    def _invalidate_test(self, test_id: int) -> None:
        if QMessageBox.question(
            self, "Marcar como inválido", "Manter os dados e marcar este ensaio como inválido?"
        ) == QMessageBox.StandardButton.Yes:
            self.test_repository.invalidate(test_id)
            self._refresh_history()

    def _save_calibration(
        self, sensor: str, gain: float, offset: float, error: float,
        stable: bool, points: list[tuple[float, float]], notes: str,
    ) -> None:
        if not stable and QMessageBox.warning(
            self, "Calibração instável",
            "As amostras foram classificadas como instáveis. Deseja salvar mesmo assim?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
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
            QMessageBox.information(
                self, "Configurações",
                "Configurações salvas. As alterações dos sensores serão aplicadas na próxima inicialização.",
            )
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Configurações inválidas", str(exc))

    def _export_graph_png(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar gráficos", str(self.paths.exports / "graficos.png"), "PNG (*.png)"
        )
        if filename:
            self.graphs.graphics.grab().save(filename)
            self.statusBar().showMessage(f"Gráfico salvo em {filename}", 4000)

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
        self._stop_serial()
        self._stop_simulation()
        if was_simulating:
            self._toggle_simulation()
        elif self.port_combo.currentData():
            self._toggle_serial()

    def _update_clock_and_status(self) -> None:
        now = datetime.now()
        self.clock_label.setText(now.strftime("%d/%m/%Y  %H:%M:%S"))
        if self.test_service.current:
            seconds = int(self.test_service.elapsed_seconds())
            self.overview.duration.setText(
                f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
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
        self.diagnostics.values["database"].setText(
            "Operacional" if self.database.health_check() else "Falha"
        )
        self.diagnostics.values["db_path"].setText(str(self.database.path))
        self.diagnostics.values["version"].setText(self.config.get("aplicacao.versao", "1.0.0"))
        try:
            free = shutil.disk_usage(self.database.path.parent).free / (1024 ** 3)
            self.diagnostics.values["disk"].setText(f"{free:.1f} GB livres")
        except OSError:
            self.diagnostics.values["disk"].setText("Indisponível")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.test_service.current:
            response = QMessageBox.warning(
                self, "Ensaio em andamento",
                "Há um ensaio ativo. Fechar agora preservará os dados e o marcará como interrompido.\n\n"
                "Deseja realmente sair?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._stop_serial()
        self._stop_simulation()
        for worker in tuple(self.export_workers):
            worker.wait(5000)
        self.database.close()
        event.accept()
