from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from statistics import pstdev
from typing import Any

from core.constants import Severity
from core.models import Alarm, Measurement, SensorReading


class AlarmService:
    def __init__(self, sensor_config: dict[str, dict[str, Any]]):
        self.config = sensor_config
        self.history: dict[str, deque[tuple[datetime, float]]] = defaultdict(
            lambda: deque(maxlen=30)
        )
        self._last_alarm_key: dict[str, datetime] = {}

    def evaluate(self, measurement: Measurement) -> list[Alarm]:
        alarms: list[Alarm] = []
        mapping = {
            "pressao": measurement.pressure,
            "vazao": measurement.flow,
        }
        for sensor, reading in mapping.items():
            alarms.extend(self._sensor_alarms(sensor, reading, measurement.received_at))
        return [alarm for alarm in alarms if self._not_duplicate(alarm)]

    def communication_alarm(self, message: str = "Perda de comunicação") -> Alarm | None:
        alarm = Alarm(
            datetime.now(), "Comunicação", Severity.CRITICAL, "comunicação", message
        )
        return alarm if self._not_duplicate(alarm, cooldown=5.0) else None

    def _sensor_alarms(
        self, sensor: str, reading: SensorReading, timestamp: datetime
    ) -> list[Alarm]:
        label = self.config[sensor]["nome"]
        alarms: list[Alarm] = []
        current = reading.current_ma
        if current is not None:
            if current < 3.6:
                alarms.append(Alarm(timestamp, label, Severity.CRITICAL, "corrente",
                                    "Corrente abaixo de 3,6 mA", current, 3.6))
            elif current < 4.0:
                alarms.append(Alarm(timestamp, label, Severity.WARNING, "corrente",
                                    "Corrente abaixo da faixa nominal", current, 4.0))
            elif current > 20.5:
                alarms.append(Alarm(timestamp, label, Severity.CRITICAL, "corrente",
                                    "Corrente acima de 20,5 mA", current, 20.5))
            elif current > 20.0:
                alarms.append(Alarm(timestamp, label, Severity.ALARM, "corrente",
                                    "Corrente acima da faixa nominal", current, 20.0))
        value = reading.value
        if value is None:
            return alarms
        cfg = self.config[sensor]
        lower, upper = cfg.get("limite_inferior"), cfg.get("limite_superior")
        if lower is not None and value < float(lower) or upper is not None and value > float(upper):
            limit = lower if lower is not None and value < float(lower) else upper
            alarms.append(Alarm(timestamp, label, Severity.ALARM, "faixa",
                                "Valor fora da faixa configurada", value, float(limit)))
        elif cfg.get("critico") is not None and value >= float(cfg["critico"]):
            alarms.append(Alarm(timestamp, label, Severity.CRITICAL, "processo",
                                "Limite crítico atingido", value, float(cfg["critico"])))
        elif cfg.get("alerta") is not None and value >= float(cfg["alerta"]):
            alarms.append(Alarm(timestamp, label, Severity.WARNING, "processo",
                                "Limite de atenção atingido", value, float(cfg["alerta"])))

        history = self.history[sensor]
        if history:
            previous_time, previous = history[-1]
            dt = max(0.001, (timestamp - previous_time).total_seconds())
            tolerance = float(cfg.get("tolerancia", 0.1))
            if abs(value - previous) / dt > tolerance * 10:
                alarms.append(Alarm(timestamp, label, Severity.WARNING, "variação",
                                    "Mudança muito brusca", value, tolerance * 10))
        history.append((timestamp, value))
        values = [item[1] for item in history]
        if len(values) >= 10 and pstdev(values) > float(cfg.get("tolerancia", 0.1)) * 3:
            alarms.append(Alarm(timestamp, label, Severity.WARNING, "ruído",
                                "Ruído elevado", pstdev(values), float(cfg.get("tolerancia", 0.1)) * 3))
        if len(values) >= 20 and max(values) - min(values) < 1e-6:
            alarms.append(Alarm(timestamp, label, Severity.WARNING, "constante",
                                "Valor constante por tempo excessivo", value, None))
        return alarms

    def _not_duplicate(self, alarm: Alarm, cooldown: float = 20.0) -> bool:
        key = f"{alarm.sensor}:{alarm.category}:{alarm.message}"
        previous = self._last_alarm_key.get(key)
        if previous and (alarm.timestamp - previous).total_seconds() < cooldown:
            return False
        self._last_alarm_key[key] = alarm.timestamp
        return True
