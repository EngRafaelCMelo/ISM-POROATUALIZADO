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
        self._sequence = 0

    def run(self) -> None:
        self._started_at = time.monotonic()
        self.state_changed.emit(True, "SIMULAÇÃO ATIVA")
        while not self._stop_event.is_set():
            elapsed = time.monotonic() - self._started_at
            if not self.communication_loss:
                self.line_generated.emit(json.dumps(self._sample(elapsed), ensure_ascii=False))
            self._stop_event.wait(self.interval_s)
        self.state_changed.emit(False, "Simulação interrompida")

    def _sample(self, elapsed: float) -> dict[str, object]:
        cycle = elapsed % 150
        pressure = min(9.2, 0.08 * cycle) if cycle < 115 else max(0.3, 9.2 - 0.25 * (cycle - 115))
        flow = min(50.0, pressure * 3.8)
        pressure += random.gauss(0, self.noise)
        flow += random.gauss(0, self.noise * 5)

        def to_ma(value: float, maximum: float) -> float:
            return 4.0 + max(0.0, value) / maximum * 16.0

        pressure_ma = to_ma(pressure, 10.0)
        flow_valid = True
        if self.current_fault == "abaixo":
            flow_valid = False
        elif self.current_fault == "critico_baixo":
            flow_valid = False
        elif self.current_fault == "acima":
            flow_valid = False
        elif self.current_fault == "critico_alto":
            flow_valid = False
        if self.sensor_disconnected:
            pressure_ma = None
            pressure = None
        result = {
            "schema_version": 1, "sequence": self._sequence, "uptime_ms": int(elapsed * 1000),
            "pressao": {"ads_raw": None, "voltage_v": None, "current_ma": pressure_ma, "value": pressure, "unit": "bar", "valid": pressure is not None},
            "vazao": {"raw_register": round(flow * 10), "value": flow, "unit": "L/min", "valid": flow_valid},
            "status": "OK", "alarms": [] if flow_valid else ["SIM_FLOW_FAULT"],
            "firmware_version": "simulador-2.0.0",
        }
        self._sequence += 1
        return result

    def stop(self) -> None:
        self._stop_event.set()
        self.wait(2000)
