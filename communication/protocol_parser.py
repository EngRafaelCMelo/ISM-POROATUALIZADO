from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from core.calculations import apply_gain_offset, current_to_engineering
from core.constants import ReadingQuality, SENSOR_KEYS, SENSOR_MA_KEYS
from core.models import Measurement, SensorReading
from core.validation import classify_current, classify_value, optional_number


class ProtocolError(ValueError):
    """Mensagem recebida não segue o protocolo esperado."""


class ProtocolParser:
    def __init__(self, sensor_config: dict[str, dict[str, Any]], value_source: str = "comparar"):
        self.sensor_config = sensor_config
        self.value_source = value_source

    def parse(self, raw: str, simulated: bool = False) -> Measurement:
        try:
            payload = json.loads(raw.strip())
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"JSON inválido: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ProtocolError("A mensagem precisa ser um objeto JSON")
        # Os nomes antigos continuam aceitos para não exigir atualização
        # simultânea do firmware e do supervisório já instalados.
        payload = dict(payload)
        if "vazao" not in payload and "vazao_baixa" in payload:
            payload["vazao"] = payload["vazao_baixa"]
        if "vazao_ma" not in payload and "vazao_baixa_ma" in payload:
            payload["vazao_ma"] = payload["vazao_baixa_ma"]
        if "vazao_status" not in payload and "vazao_baixa_status" in payload:
            payload["vazao_status"] = payload["vazao_baixa_status"]
        if not any(key in payload for key in (*SENSOR_KEYS, *SENSOR_MA_KEYS.values())):
            raise ProtocolError("Nenhum campo de sensor reconhecido")

        readings = {
            key: self._reading(
                key,
                payload.get(key),
                payload.get(SENSOR_MA_KEYS[key]),
                payload.get(f"{key}_status"),
                simulated,
            )
            for key in SENSOR_KEYS
        }
        timestamp = payload.get("timestamp_ms")
        try:
            timestamp_ms = int(timestamp) if timestamp is not None else None
        except (TypeError, ValueError) as exc:
            raise ProtocolError("timestamp_ms inválido") from exc
        return Measurement(
            received_at=datetime.now(),
            device_timestamp_ms=timestamp_ms,
            pressure=readings["pressao"],
            flow=readings["vazao"],
            communication_state=str(payload.get("status", "OK")),
            raw_message=raw.strip(),
            simulated=simulated,
        )

    def _reading(
        self,
        key: str,
        device_raw: Any,
        current_raw: Any,
        status_raw: Any,
        simulated: bool,
    ) -> SensorReading:
        try:
            device_value = optional_number(device_raw)
            current = optional_number(current_raw)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"Campo numérico inválido em {key}") from exc
        cfg = self.sensor_config[key]
        calculated = None
        if current is not None:
            calculated = apply_gain_offset(
                current_to_engineering(
                    current,
                    float(cfg["limite_inferior"]),
                    float(cfg["limite_superior"]),
                    float(cfg.get("corrente_min", 4.0)),
                    float(cfg.get("corrente_max", 20.0)),
                ),
                float(cfg.get("ganho", 1.0)),
                float(cfg.get("offset", 0.0)),
            )
        if self.value_source == "software":
            value = calculated if calculated is not None else device_value
        else:
            value = device_value if device_value is not None else calculated
        quality = classify_current(current, simulated)
        if current is None and device_value is not None:
            quality = ReadingQuality.SIMULATED if simulated else ReadingQuality.VALID
        if (
            self.value_source == "comparar"
            and device_value is not None
            and calculated is not None
            and quality != ReadingQuality.INVALID
            and abs(device_value - calculated) > float(cfg.get("tolerancia", 0.0))
        ):
            quality = ReadingQuality.WARNING
        quality = classify_value(
            value, float(cfg["limite_inferior"]), float(cfg["limite_superior"]), quality
        )
        return SensorReading(
            value=value,
            current_ma=current,
            quality=quality,
            device_value=device_value,
            calculated_value=calculated,
            device_status=str(status_raw) if status_raw is not None else "",
        )
