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
        pressure = min(9.2, 0.08 * cycle) if cycle < 115 else max(0.3, 9.2 - 0.25 * (cycle - 115))
        low = min(5.0, pressure * 0.58)
        high = pressure * 3.8
        pressure += random.gauss(0, self.noise)
        low += random.gauss(0, self.noise)
        high += random.gauss(0, self.noise * 5)

        def to_ma(value: float, maximum: float) -> float:
            return 4.0 + max(0.0, value) / maximum * 16.0

        pressure_ma = to_ma(pressure, 10.0)
        low_ma = to_ma(low, 5.0)
        high_ma = to_ma(high, 50.0)
        if self.current_fault == "abaixo":
            low_ma = 3.7
        elif self.current_fault == "critico_baixo":
            low_ma = 3.2
        elif self.current_fault == "acima":
            low_ma = 20.2
        elif self.current_fault == "critico_alto":
            low_ma = 21.0
        if self.sensor_disconnected:
            pressure_ma = None
            pressure = None
        return {
            "timestamp_ms": int(elapsed * 1000),
            "pressao_ma": pressure_ma,
            "pressao": pressure,
            "vazao_baixa_ma": low_ma,
            "vazao_baixa": low,
            "vazao_alta_ma": high_ma,
            "vazao_alta": high,
            "status": "SIMULADO",
        }

    def stop(self) -> None:
        self._stop_event.set()
        self.wait(2000)
