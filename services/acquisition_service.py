from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from communication.protocol_parser import ProtocolError, ProtocolParser
from core.calculations import FlowMeterSelector
from core.models import Measurement
from services.alarm_service import AlarmService

logger = logging.getLogger(__name__)


class AcquisitionService(QObject):
    measurement_ready = Signal(object)
    alarm_raised = Signal(object)
    counters_changed = Signal(int, int)
    timeout_detected = Signal(str)

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.config = config
        self.parser = ProtocolParser(
            config["sensores"], config["aquisicao"].get("fonte_valor", "comparar")
        )
        flow = config["flow_meter"]
        self.selector = FlowMeterSelector(
            float(flow["trocar_alta_percentual"]),
            float(flow["retornar_baixa_percentual"]),
        )
        self.alarm_service = AlarmService(config["sensores"])
        self.valid_messages = 0
        self.invalid_messages = 0
        self.last_message_at: datetime | None = None
        self.last_raw_message = ""
        self.simulation = False
        self._timeout_announced = False
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setInterval(500)
        self.timeout_timer.timeout.connect(self._check_timeout)
        self.timeout_timer.start()

    @Slot(str)
    def process_real(self, raw: str) -> None:
        self._process(raw, simulated=False)

    @Slot(str)
    def process_simulated(self, raw: str) -> None:
        self._process(raw, simulated=True)

    def _process(self, raw: str, simulated: bool) -> None:
        self.last_raw_message = raw
        try:
            measurement = self.parser.parse(raw, simulated)
            low_cfg = self.config["sensores"]["vazao_baixa"]
            mode = self.config["flow_meter"].get("modo", "automatico")
            if mode == "automatico":
                measurement.active_flow_meter = self.selector.select(
                    measurement.low_flow.value,
                    float(low_cfg["limite_inferior"]),
                    float(low_cfg["limite_superior"]),
                )
            else:
                measurement.active_flow_meter = "alta" if mode == "alta" else "baixa"
            self.valid_messages += 1
            self.last_message_at = datetime.now()
            self.simulation = simulated
            self._timeout_announced = False
            self.measurement_ready.emit(measurement)
            for alarm in self.alarm_service.evaluate(measurement):
                self.alarm_raised.emit(alarm)
        except ProtocolError as exc:
            self.invalid_messages += 1
            logger.warning("Mensagem descartada: %s | %r", exc, raw[:500])
        self.counters_changed.emit(self.valid_messages, self.invalid_messages)

    def reset_counters(self) -> None:
        self.valid_messages = self.invalid_messages = 0
        self.counters_changed.emit(0, 0)

    def _check_timeout(self) -> None:
        if not self.last_message_at or self._timeout_announced:
            return
        timeout = float(self.config["comunicacao"].get("timeout_s", 3.0))
        age = (datetime.now() - self.last_message_at).total_seconds()
        if age > timeout:
            self._timeout_announced = True
            message = f"Nenhum dado recebido há {age:.1f} s"
            self.timeout_detected.emit(message)
            alarm = self.alarm_service.communication_alarm(message)
            if alarm:
                self.alarm_raised.emit(alarm)
