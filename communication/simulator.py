from __future__ import annotations

import json
import random
import threading
import time

from PySide6.QtCore import QThread, Signal


class SimulatorWorker(QThread):
    line_generated = Signal(str)
    flow_generated = Signal(float)
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
                sample = self._sample(elapsed)
                self.line_generated.emit(json.dumps(sample, ensure_ascii=False))
                if sample["pressao"] is not None:
                    flow = 5.0 + float(sample["pressao"]) / 400.0 * 995.0
                    flow += random.gauss(0, self.noise)
                    self.flow_generated.emit(max(0.0, flow))
            self._stop_event.wait(self.interval_s)
        self.state_changed.emit(False, "Simulação interrompida")

    def _sample(self, elapsed: float) -> dict[str, float | int | str | None]:
        cycle = elapsed % 150
        pressure = (
            min(368.0, 3.2 * cycle) if cycle < 115 else max(12.0, 368.0 - 10.0 * (cycle - 115))
        )
        pressure += random.gauss(0, self.noise * 40)

        def to_ma(value: float, maximum: float) -> float:
            return 3.95 + max(0.0, value) / maximum * (20.0 - 3.95)

        pressure_ma = to_ma(pressure, 400.0)
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
        self._sequence += 1
        return {
            "schema_version": 1,
            "timestamp_ms": int(elapsed * 1000),
            "sequence": self._sequence,
            "firmware_version": "SIMULADOR-2.2.0",
            "pressao_raw": None
            if pressure_ma is None
            else int(pressure_ma / 1000 * 149.7 / 4.096 * 32768),
            "pressao_ma": pressure_ma,
            "pressao": pressure,
            "pressao_unidade": "psi",
            "pressao_valida": pressure is not None,
            "pressao_status": "SIMULADO" if pressure is not None else "SENSOR_DESCONECTADO",
            "status": "SIMULADO" if pressure is not None else "PRESSURE_INVALID",
        }

    def stop(self) -> None:
        self._stop_event.set()
        self.wait(2000)
