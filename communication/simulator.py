from __future__ import annotations

import json
import math
import random
import threading
import time

from PySide6.QtCore import QThread, Signal


class SimulatorWorker(QThread):
    line_generated = Signal(str)
    state_changed = Signal(bool, str)

    def __init__(self, interval_s: float = 1.0, noise: float = 0.03):
        super().__init__()
        self.interval_s = interval_s
        self.noise = noise
        self.sensor_disconnected = False
        self.current_fault = "normal"
        self.communication_loss = False
        self._stop_event = threading.Event()
        self._started_at = 0.0

    def run(self) -> None:
        self._started_at = time.monotonic()
        self.state_changed.emit(True, "SIMULAÇÃO ATIVA")
        while not self._stop_event.is_set():
            elapsed = time.monotonic() - self._started_at
            if not self.communication_loss:
                self.line_generated.emit(json.dumps(self._sample(elapsed), ensure_ascii=False))
            self._stop_event.wait(self.interval_s)
        self.state_changed.emit(False, "Simulação interrompida")

    def _sample(self, elapsed: float) -> dict[str, float | int | str | None]:
        cycle = elapsed % 150
        pressure = (
            min(92.0, 0.8 * cycle)
            if cycle < 115
            else max(3.0, 92.0 - 2.5 * (cycle - 115))
        )
        flow = min(5.0, pressure * 0.058)
        pressure += random.gauss(0, self.noise * 10)
        flow += random.gauss(0, self.noise)

        def to_ma(value: float, maximum: float) -> float:
            return 4.0 + max(0.0, value) / maximum * 16.0

        pressure_ma = to_ma(pressure, 100.0)
        if self.current_fault == "abaixo":
            pressure_ma = 3.7
        elif self.current_fault == "critico_baixo":
            pressure_ma = 3.2
        elif self.current_fault == "acima":
            pressure_ma = 20.2
        elif self.current_fault == "critico_alto":
            pressure_ma = 21.0
        if self.sensor_disconnected:
            pressure_ma = None
            pressure = None
        return {
            "timestamp_ms": int(elapsed * 1000),
            "pressao_ma": pressure_ma,
            "pressao": pressure,
            "vazao": flow,
            "status": "SIMULADO",
        }

    def stop(self) -> None:
        self._stop_event.set()
        self.wait(2000)
