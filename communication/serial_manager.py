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
