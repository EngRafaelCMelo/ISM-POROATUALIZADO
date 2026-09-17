from __future__ import annotations

import logging
from datetime import datetime
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from communication.protocol_parser import ProtocolError, ProtocolParser
from core.constants import ReadingQuality
from core.models import Measurement, SensorReading
from core.validation import classify_value
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
        self.alarm_service = AlarmService(config["sensores"])
        self.valid_messages = 0
        self.invalid_messages = 0
        self.last_message_at: datetime | None = None
        self.last_raw_message = ""
        self.simulation = False
        self._timeout_announced = False
        self.latest_flow: tuple[SensorReading, bool, datetime] | None = None
        self.latest_pressure: SensorReading | None = None
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setInterval(500)
        self.timeout_timer.timeout.connect(self._check_timeout)
        self.timeout_timer.start()

    @Slot(str)
    def process_real(self, raw: str) -> None:
        self._process(raw, simulated=False)

    @Slot(float)
    def process_flow(self, value: float) -> None:
        cfg = self.config["sensores"]["vazao"]
        quality = classify_value(value, float(cfg["limite_inferior"]),
                                 float(cfg["limite_superior"]), ReadingQuality.VALID)
        reading = SensorReading(value=value, device_value=value, quality=quality, device_status="OK")
        self.latest_flow = (reading, True, datetime.now())
        self._emit_live_flow()

    @Slot(str)
    def process_flow_error(self, message: str) -> None:
        self.latest_flow = (SensorReading(device_status=message), False, datetime.now())
        self._emit_live_flow()

    def _emit_live_flow(self) -> None:
        if not self.latest_flow:
            return
        flow, flow_ok, _timestamp = self.latest_flow
        measurement = Measurement(received_at=datetime.now(), pressure=self.latest_pressure or SensorReading(),
                                  flow=flow, flowmeter_ok=flow_ok,
                                  communication_state="OK" if flow_ok else "PARCIAL_SEM_VAZAO",
                                  recordable=False)
        self.measurement_ready.emit(measurement)

    @Slot(str)
    def process_simulated(self, raw: str) -> None:
        self._process(raw, simulated=True)

    def _process(self, raw: str, simulated: bool) -> None:
        self.last_raw_message = raw
        try:
            measurement = self.parser.parse(raw, simulated)
            self.latest_pressure = measurement.pressure
            if self.latest_flow is not None:
                flow, flow_ok, flow_at = self.latest_flow
                max_age = 3 * float(self.config["flowmeter"].get("intervalo_ms", 1000)) / 1000
                if (datetime.now() - flow_at).total_seconds() > max_age:
                    flow, flow_ok = SensorReading(device_status="SEM_COMUNICACAO"), False
                measurement = replace(
                    measurement,
                    flowmeter_ok=flow_ok,
                    flow=flow,
                )
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
