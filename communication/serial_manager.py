from __future__ import annotations

import logging
import threading

import serial
from PySide6.QtCore import QThread, Signal
from serial.tools import list_ports

logger = logging.getLogger(__name__)


def available_ports() -> list[tuple[str, str]]:
    return [(port.device, port.description) for port in list_ports.comports()]


class SerialWorker(QThread):
    line_received = Signal(str)
    state_changed = Signal(bool, str)
    communication_error = Signal(str)

    def __init__(self, port: str, baud_rate: int, read_timeout: float = 0.5, reconnect: bool = True):
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
                self.state_changed.emit(True, f"Conectado a {self.port}")
                retry_delay = 0.5
                while not self._stop_event.is_set():
                    raw = self._serial.readline()
                    if raw:
                        self.line_received.emit(raw.decode("utf-8", errors="replace").strip())
                break
            except (serial.SerialException, OSError) as exc:
                logger.warning("Falha serial em %s: %s", self.port, exc)
                self.communication_error.emit(str(exc))
            finally:
                if self._serial and self._serial.is_open:
                    self._serial.close()
                self._serial = None
                self.state_changed.emit(False, "Desconectado")
            if not self.reconnect or self._stop_event.wait(retry_delay):
                break
            retry_delay = min(retry_delay * 2.0, 5.0)

    def stop(self) -> None:
        self._stop_event.set()
        if self._serial:
            try:
                self._serial.cancel_read()
            except (AttributeError, serial.SerialException):
                pass
        self.wait(3000)

    def is_connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)


class FlowmeterWorker(QThread):
    """Leitor Modbus RTU dedicado ao adaptador USB-RS485 do flowmeter."""
    reading_received = Signal(float)
    state_changed = Signal(bool, str)
    communication_error = Signal(str)

    def __init__(self, port: str):
        super().__init__()
        self.port = port
        self._stop_event = threading.Event()

    @staticmethod
    def _crc(data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        return crc

    def run(self) -> None:
        request = bytes.fromhex("01 03 00 3A 00 02 E4 06")
        try:
            with serial.Serial(self.port, 9600, bytesize=8, parity=serial.PARITY_NONE,
                               stopbits=1, timeout=1.5) as port:
                self.state_changed.emit(True, f"Flowmeter conectado a {self.port}")
                while not self._stop_event.is_set():
                    try:
                        port.reset_input_buffer()
                        port.write(request)
                        response = port.read(9)
                        if len(response) != 9:
                            raise ValueError(f"resposta Modbus com {len(response)} bytes")
                        if response[:3] != bytes((1, 3, 4)):
                            raise ValueError("ID, função ou byte count inválido")
                        received = response[-2] | (response[-1] << 8)
                        if received != self._crc(response[:-2]):
                            raise ValueError("CRC Modbus inválido")
                        self.reading_received.emit(int.from_bytes(response[3:7], "big") / 1000.0)
                    except ValueError as exc:
                        self.communication_error.emit(str(exc))
                    self._stop_event.wait(1.0)
        except Exception as exc:
            self.communication_error.emit(str(exc))
        finally:
            self.state_changed.emit(False, "Flowmeter desconectado")

    def stop(self) -> None:
        self._stop_event.set()
        self.wait(2500)
