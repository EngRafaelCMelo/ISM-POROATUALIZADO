from __future__ import annotations

import logging
import threading
import time

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

    def __init__(self, port: str, baud_rate: int, read_timeout: float = 0.5):
        super().__init__()
        self.port = port
        self.baud_rate = baud_rate
        self.read_timeout = read_timeout
        self._stop_event = threading.Event()
        self._serial: serial.Serial | None = None

    def run(self) -> None:
        try:
            self._serial = serial.Serial(
                self.port, self.baud_rate, timeout=self.read_timeout
            )
            self.state_changed.emit(True, f"Conectado a {self.port}")
            while not self._stop_event.is_set():
                try:
                    raw = self._serial.readline()
                    if raw:
                        self.line_received.emit(raw.decode("utf-8", errors="replace").strip())
                except serial.SerialException as exc:
                    self.communication_error.emit(str(exc))
                    break
                except UnicodeError as exc:
                    logger.warning("Linha serial inválida: %s", exc)
                    self.communication_error.emit("Dados recebidos não são UTF-8")
                time.sleep(0.005)
        except (serial.SerialException, OSError) as exc:
            logger.exception("Falha ao abrir a porta serial")
            self.communication_error.emit(str(exc))
        finally:
            if self._serial and self._serial.is_open:
                self._serial.close()
            self._serial = None
            self.state_changed.emit(False, "Desconectado")

    def stop(self) -> None:
        self._stop_event.set()
        self.wait(2000)

    def is_connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)
