from __future__ import annotations

import logging
import math
from dataclasses import replace
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from communication.protocol_parser import ProtocolError, ProtocolParser
from communication.serial_manager import FlowReading
from core.constants import ReadingQuality
from core.models import Measurement, SensorReading
from services.alarm_service import AlarmService

logger = logging.getLogger(__name__)


class AcquisitionService(QObject):
    pressure_updated = Signal(object)
    flow_updated = Signal(object)
    combined_measurement_ready = Signal(object)
    measurement_ready = Signal(object)  # compatibilidade: somente medição combinada
    sensor_status_changed = Signal(str, str)
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
        self.latest_pressure = SensorReading(
            unit=config["sensores"]["pressao"].get("unidade", "bar")
        )
        self.latest_flow = SensorReading(unit=config["sensores"]["vazao"].get("unidade", "NL/min"))
        self._latest_pressure_meta: Measurement | None = None
        self._dirty = False
        self._flow_stale_announced = False

        self.timeout_timer = QTimer(self)
        self.timeout_timer.setInterval(500)
        self.timeout_timer.timeout.connect(self._check_timeout)
        self.timeout_timer.start()

        self.combine_timer = QTimer(self)
        self.combine_timer.setInterval(
            max(100, int(float(config["aquisicao"].get("intervalo_s", 1.0)) * 1000))
        )
        self.combine_timer.timeout.connect(self.emit_combined_measurement)
        self.combine_timer.start()

    @Slot(str)
    def process_real(self, raw: str) -> None:
        self._process_pressure(raw, simulated=False)

    @Slot(str)
    def process_simulated(self, raw: str) -> None:
        self._process_pressure(raw, simulated=True)

    def _process_pressure(self, raw: str, simulated: bool) -> None:
        self.last_raw_message = raw
        try:
            measurement = self.parser.parse(raw, simulated)
            self.latest_pressure = measurement.pressure
            self._latest_pressure_meta = measurement
            self.valid_messages += 1
            self.last_message_at = measurement.pressure.timestamp
            self.simulation = simulated
            self._timeout_announced = False
            self._dirty = True
            self.pressure_updated.emit(measurement.pressure)
            self.sensor_status_changed.emit("pressao", measurement.pressure.device_status or "OK")
        except ProtocolError as exc:
            self.invalid_messages += 1
            logger.warning("Mensagem do ESP32 descartada: %s | %r", exc, raw[:500])
            self.sensor_status_changed.emit("pressao", "INVALID")
        self.counters_changed.emit(self.valid_messages, self.invalid_messages)

    @Slot(object)
    def process_flow(self, flow: FlowReading | float) -> None:
        if isinstance(flow, FlowReading):
            value, raw, timestamp, status = flow.value, flow.raw_uint32, flow.timestamp, flow.status
        else:  # compatibilidade com integrações anteriores e simulação
            value, raw, timestamp, status = float(flow), None, datetime.now(), "OK"
        cfg = self.config["sensores"]["vazao"]
        quality = (
            ReadingQuality.SIMULATED
            if self.simulation and math.isfinite(value) and value >= 0
            else ReadingQuality.VALID
            if math.isfinite(value) and value >= 0
            else ReadingQuality.INVALID
        )
        self.latest_flow = SensorReading(
            value=value,
            device_value=value,
            quality=quality,
            device_status=status,
            raw_value=raw,
            unit=cfg.get("unidade", "NL/min"),
            timestamp=timestamp,
        )
        self._flow_stale_announced = False
        self._dirty = True
        self.flow_updated.emit(self.latest_flow)
        self.sensor_status_changed.emit("vazao", status)

    @Slot(float)
    def process_simulated_flow(self, value: float) -> None:
        self.simulation = True
        self.process_flow(value)

    @Slot(str)
    def process_flow_error(self, message: str) -> None:
        raw_code = message.partition(":")[0].strip().casefold()
        disconnected_codes = {
            "porta_desconectada",
            "porta_ocupada",
            "sem_comunicacao",
        }
        quality = (
            ReadingQuality.DISCONNECTED
            if raw_code in disconnected_codes
            else ReadingQuality.INVALID
        )
        status = raw_code.upper() if raw_code else "ERRO_MODBUS"
        self.latest_flow = replace(
            self.latest_flow,
            quality=quality,
            device_status=status,
        )
        self._flow_stale_announced = quality == ReadingQuality.DISCONNECTED
        self._dirty = True
        self.flow_updated.emit(self.latest_flow)
        self.sensor_status_changed.emit("vazao", quality.name)

    @Slot(bool, str)
    def process_pressure_connection(self, connected: bool, message: str) -> None:
        if connected:
            return
        self.latest_pressure = replace(
            self.latest_pressure,
            quality=ReadingQuality.DISCONNECTED,
            device_status="DISCONNECTED",
        )
        self._dirty = True
        self.pressure_updated.emit(self.latest_pressure)
        self.sensor_status_changed.emit("pressao", "DISCONNECTED")
        logger.warning("ESP32 desconectado: %s", message)

    @Slot()
    def emit_combined_measurement(self) -> Measurement | None:
        if not self._dirty:
            return None
        now = datetime.now()
        pressure = self._with_freshness(self.latest_pressure, self._pressure_stale_after(), now)
        flow = self._with_freshness(self.latest_flow, self._flow_stale_after(), now)
        meta = self._latest_pressure_meta
        if pressure.quality == ReadingQuality.STALE:
            self.sensor_status_changed.emit("pressao", "STALE")
        if flow.quality == ReadingQuality.STALE:
            self.sensor_status_changed.emit("vazao", "STALE")
        state = self._combined_state(pressure, flow)
        if state == "OK" and not self._timestamps_synchronized(pressure, flow):
            state = "UNSYNCHRONIZED"
        measurement = Measurement(
            received_at=now,
            device_timestamp_ms=meta.device_timestamp_ms if meta else None,
            pressure=pressure,
            flow=flow,
            flowmeter_ok=flow.valid,
            communication_state=state,
            raw_message=meta.raw_message if meta else "",
            simulated=self.simulation,
            recordable=True,
            sequence=meta.sequence if meta else None,
            schema_version=meta.schema_version if meta else None,
            firmware_version=meta.firmware_version if meta else "",
        )
        self._dirty = False
        self.combined_measurement_ready.emit(measurement)
        self.measurement_ready.emit(measurement)
        for alarm in self.alarm_service.evaluate(measurement):
            self.alarm_raised.emit(alarm)
        return measurement

    @staticmethod
    def _with_freshness(reading: SensorReading, stale_after: float, now: datetime) -> SensorReading:
        age = reading.age_seconds(now)
        if reading.timestamp is not None and age is not None and age > stale_after:
            return replace(reading, quality=ReadingQuality.STALE, device_status="STALE")
        return reading

    def _pressure_stale_after(self) -> float:
        return float(self.config["comunicacao"].get("timeout_s", 3.0))

    def _flow_stale_after(self) -> float:
        return float(self.config["flowmeter"].get("stale_after_s", 3.0))

    def _timestamps_synchronized(self, pressure: SensorReading, flow: SensorReading) -> bool:
        if pressure.timestamp is None or flow.timestamp is None:
            return False
        window = max(0.1, float(self.config["aquisicao"].get("intervalo_s", 1.0)))
        return abs((pressure.timestamp - flow.timestamp).total_seconds()) <= window + 0.05

    @staticmethod
    def _combined_state(pressure: SensorReading, flow: SensorReading) -> str:
        if (
            pressure.quality == ReadingQuality.DISCONNECTED
            or flow.quality == ReadingQuality.DISCONNECTED
        ):
            return "DISCONNECTED"
        if pressure.quality == ReadingQuality.STALE or flow.quality == ReadingQuality.STALE:
            return "STALE"
        if not pressure.valid or not flow.valid:
            return "INVALID"
        return "OK"

    def preflight_snapshot(self) -> Measurement:
        now = datetime.now()
        return Measurement(
            received_at=now,
            pressure=self._with_freshness(self.latest_pressure, self._pressure_stale_after(), now),
            flow=self._with_freshness(self.latest_flow, self._flow_stale_after(), now),
            simulated=self.simulation,
            recordable=False,
        )

    def reset_counters(self) -> None:
        self.valid_messages = self.invalid_messages = 0
        self.counters_changed.emit(0, 0)

    def _check_timeout(self) -> None:
        now = datetime.now()
        if self.last_message_at and not self._timeout_announced:
            age = (now - self.last_message_at).total_seconds()
        else:
            age = 0.0
        if age > self._pressure_stale_after():
            self._timeout_announced = True
            self.latest_pressure = replace(
                self.latest_pressure, quality=ReadingQuality.STALE, device_status="STALE"
            )
            self._dirty = True
            message = f"Pressão sem atualização há {age:.1f} s"
            self.timeout_detected.emit(message)
            self.pressure_updated.emit(self.latest_pressure)
            self.sensor_status_changed.emit("pressao", "STALE")
            alarm = self.alarm_service.communication_alarm(message)
            if alarm:
                self.alarm_raised.emit(alarm)
        flow_age = self.latest_flow.age_seconds(now)
        if (
            flow_age is not None
            and flow_age > self._flow_stale_after()
            and not self._flow_stale_announced
            and self.latest_flow.quality != ReadingQuality.DISCONNECTED
        ):
            self._flow_stale_announced = True
            self.latest_flow = replace(
                self.latest_flow, quality=ReadingQuality.STALE, device_status="STALE"
            )
            self._dirty = True
            message = f"Vazão sem atualização há {flow_age:.1f} s"
            self.timeout_detected.emit(message)
            self.flow_updated.emit(self.latest_flow)
            self.sensor_status_changed.emit("vazao", "STALE")
            alarm = self.alarm_service.communication_alarm(message)
            if alarm:
                self.alarm_raised.emit(alarm)

    def stop(self) -> None:
        self.timeout_timer.stop()
        self.combine_timer.stop()
