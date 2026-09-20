from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime

import serial
from PySide6.QtCore import QThread, Signal
from serial.tools import list_ports

from communication.modbus import (
    ModbusErrorCode,
    ModbusFrameError,
    build_read_request,
    expected_response_size,
    parse_flow_response,
)
from core.units import FLOW_PROTOCOL_UNIT

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PortDescriptor:
    device: str
    description: str
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None

    @property
    def identity(self) -> str:
        if self.vid is None or self.pid is None:
            return self.device
        return f"{self.vid:04X}:{self.pid:04X}:{self.serial_number or ''}"


@dataclass(frozen=True, slots=True)
class FlowReading:
    value: float
    raw_uint32: int
    timestamp: datetime
    valid: bool = True
    status: str = "OK"
    unit: str = FLOW_PROTOCOL_UNIT


@dataclass(slots=True)
class FlowmeterStatistics:
    successes: int = 0
    timeouts: int = 0
    crc_errors: int = 0
    exceptions: int = 0
    reconnects: int = 0
    short_responses: int = 0
    protocol_errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def available_port_details() -> list[PortDescriptor]:
    return [
        PortDescriptor(port.device, port.description, port.vid, port.pid, port.serial_number)
        for port in list_ports.comports()
    ]


def available_ports() -> list[tuple[str, str]]:
    return [(port.device, port.description) for port in available_port_details()]


def resolve_port(device: str, identity: str = "") -> str:
    ports = available_port_details()
    if identity:
        match = next((port.device for port in ports if port.identity == identity), None)
        if match:
            return match
    return device


class SerialWorker(QThread):
    line_received = Signal(str)
    state_changed = Signal(bool, str)
    communication_error = Signal(str)

    def __init__(
        self, port: str, baud_rate: int, read_timeout: float = 0.5, reconnect: bool = True
    ):
        super().__init__()
        self.port, self.baud_rate, self.read_timeout = port, baud_rate, read_timeout
        self.reconnect = reconnect
        self._stop_event = threading.Event()
        self._serial: serial.Serial | None = None

    def run(self) -> None:
        retry_delay = 0.5
        while not self._stop_event.is_set():
            try:
                self._serial = serial.Serial(self.port, self.baud_rate, timeout=self.read_timeout)
                logger.info("Porta do ESP32 aberta: %s @ %s", self.port, self.baud_rate)
                self.state_changed.emit(True, f"ESP32 conectado a {self.port}")
                retry_delay = 0.5
                while not self._stop_event.is_set():
                    raw = self._serial.readline()
                    if raw:
                        self.line_received.emit(raw.decode("utf-8", errors="replace").strip())
            except (serial.SerialException, OSError) as exc:
                logger.warning("Falha serial do ESP32 em %s: %s", self.port, exc)
                self.communication_error.emit(_friendly_serial_error(exc))
            finally:
                self._close_port()
                self.state_changed.emit(False, "ESP32 desconectado")
            if not self.reconnect or self._stop_event.wait(retry_delay):
                break
            retry_delay = min(retry_delay * 2.0, 5.0)

    def _close_port(self) -> None:
        port, self._serial = self._serial, None
        if port and port.is_open:
            try:
                port.close()
            except serial.SerialException:
                logger.exception("Falha ao fechar porta do ESP32")
        logger.info("Porta do ESP32 fechada: %s", self.port)

    def stop(self) -> None:
        self._stop_event.set()
        if self._serial:
            try:
                self._serial.cancel_read()
            except (AttributeError, serial.SerialException):
                pass
        if not self.wait(3000):
            logger.error("Thread do ESP32 não encerrou dentro do prazo")

    def is_connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)


class FlowmeterWorker(QThread):
    """Leitor somente leitura do flowmeter USB–RS485 (função Modbus 03)."""

    reading_received = Signal(object)
    state_changed = Signal(bool, str)
    communication_error = Signal(str)
    statistics_changed = Signal(object)
    frame_logged = Signal(str, str)

    def __init__(self, config: dict[str, object]):
        super().__init__()
        self.config = config
        self.port = str(config["porta"])
        self._stop_event = threading.Event()
        self._serial: serial.Serial | None = None
        self.statistics = FlowmeterStatistics()
        self._last_error_key = ""
        self._last_error_at = 0.0
        self._validate_config()

    def _validate_config(self) -> None:
        expected = {
            "slave_id": 1,
            "baud_rate": 9600,
            "funcao": 3,
            "registrador_inicial": 58,
            "quantidade_registradores": 2,
            "tipo_dado": "uint32",
            "ordem_bytes": "big",
            "fator_escala": 0.001,
        }
        mismatches = [
            f"{key}={self.config.get(key)!r} (esperado {value!r})"
            for key, value in expected.items()
            if str(self.config.get(key)).lower() != str(value).lower()
        ]
        timeout = float(self.config.get("timeout_s", 1.0))
        if not 0.75 <= timeout <= 1.5:
            mismatches.append("timeout_s deve estar entre 0,75 e 1,5")
        if mismatches:
            raise ValueError("Configuração Modbus não suportada: " + "; ".join(mismatches))

    def run(self) -> None:
        retry_delay = 0.5
        connection_attempted = False
        while not self._stop_event.is_set():
            try:
                if connection_attempted:
                    self.statistics.reconnects += 1
                    self._emit_statistics()
                connection_attempted = True
                self._open_port()
                retry_delay = 0.5
                self.state_changed.emit(True, f"Flowmeter conectado a {self.port}")
                self._emit_statistics()
                while not self._stop_event.is_set():
                    self._poll_once()
                    if self._stop_event.wait(float(self.config.get("intervalo_ms", 1000)) / 1000.0):
                        break
            except (serial.SerialException, OSError) as exc:
                message = _friendly_serial_error(exc)
                logger.warning("Falha na porta do flowmeter %s: %s", self.port, exc)
                code = (
                    ModbusErrorCode.PORT_BUSY
                    if "ocupada" in message.lower()
                    else ModbusErrorCode.PORT_DISCONNECTED
                )
                self._emit_error(code, message)
            finally:
                self._close_port()
                self.state_changed.emit(False, "Flowmeter desconectado")
            if not bool(self.config.get("reconexao_automatica", True)) or self._stop_event.wait(
                retry_delay
            ):
                break
            retry_delay = min(retry_delay * 2.0, 5.0)

    def _open_port(self) -> None:
        self._serial = serial.Serial(
            self.port,
            9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            write_timeout=0.5,
        )
        logger.info("Porta do flowmeter aberta: %s @ 9600 8N1", self.port)

    def _poll_once(self) -> None:
        if self._serial is None:
            return
        request = build_read_request()
        try:
            self._serial.reset_input_buffer()
            self._serial.write(request)  # somente Read Holding Registers (03)
            self._serial.flush()
            if bool(self.config.get("log_frames", False)):
                self.frame_logged.emit("TX", request.hex(" ").upper())
                logger.info("Flowmeter TX: %s", request.hex(" ").upper())
            response = self._read_frame(float(self.config.get("timeout_s", 1.0)))
            if bool(self.config.get("log_frames", False)):
                self.frame_logged.emit("RX", response.hex(" ").upper() or "<timeout>")
                logger.info("Flowmeter RX: %s", response.hex(" ").upper() or "<timeout>")
            parsed = parse_flow_response(response)
            self.statistics.successes += 1
            self._last_error_key = ""
            self.reading_received.emit(
                FlowReading(parsed.value, parsed.raw_uint32, datetime.now(), unit=parsed.unit)
            )
            self._emit_statistics()
        except ModbusFrameError as exc:
            self._count_frame_error(exc.code)
            self._emit_error(exc.code, str(exc))

    def _read_frame(self, timeout_s: float) -> bytes:
        assert self._serial is not None
        deadline = time.monotonic() + timeout_s
        response = bytearray()
        target_size: int | None = None
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            chunk = self._serial.read(max(1, (target_size or 3) - len(response)))
            if chunk:
                response.extend(chunk)
                target_size = expected_response_size(response)
                if target_size is not None and len(response) >= target_size:
                    return bytes(response[:target_size])
        return bytes(response)

    def _count_frame_error(self, code: ModbusErrorCode) -> None:
        if code == ModbusErrorCode.TIMEOUT:
            self.statistics.timeouts += 1
        elif code == ModbusErrorCode.CRC_INVALID:
            self.statistics.crc_errors += 1
        elif code == ModbusErrorCode.EXCEPTION:
            self.statistics.exceptions += 1
        elif code == ModbusErrorCode.SHORT_RESPONSE:
            self.statistics.short_responses += 1
        else:
            self.statistics.protocol_errors += 1
        self._emit_statistics()

    def _emit_error(self, code: ModbusErrorCode, message: str) -> None:
        key = f"{code}:{message}"
        now = time.monotonic()
        if key != self._last_error_key or now - self._last_error_at >= 5.0:
            self.communication_error.emit(f"{code.value}: {message}")
            logger.warning("Flowmeter %s: %s", code.value, message)
            self._last_error_key, self._last_error_at = key, now

    def _emit_statistics(self) -> None:
        self.statistics_changed.emit(self.statistics.as_dict())

    def _close_port(self) -> None:
        port, self._serial = self._serial, None
        if port and port.is_open:
            try:
                port.close()
            except serial.SerialException:
                logger.exception("Falha ao fechar porta do flowmeter")
        logger.info("Porta do flowmeter fechada: %s", self.port)

    def stop(self) -> None:
        self._stop_event.set()
        if self._serial:
            try:
                self._serial.cancel_read()
            except (AttributeError, serial.SerialException):
                pass
        if not self.wait(3000):
            logger.error("Thread do flowmeter não encerrou dentro do prazo")


def _friendly_serial_error(exc: BaseException) -> str:
    raw = str(exc)
    lowered = raw.lower()
    if "access is denied" in lowered or "permission" in lowered or "acesso negado" in lowered:
        return "Porta ocupada. Feche o QModMaster ou outro programa que esteja usando a COM."
    if "could not open" in lowered or "cannot find" in lowered or "não foi possível" in lowered:
        return "Porta desconectada ou indisponível. Verifique o cabo USB."
    return f"Falha de comunicação serial: {raw}"
