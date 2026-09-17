from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from core.calculations import apply_gain_offset, current_to_engineering
from core.constants import ReadingQuality
from core.models import Measurement, SensorReading
from core.validation import classify_current, classify_value, optional_number
from core.version import SUPPORTED_FIRMWARE_SCHEMA


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
        required = {
            "schema_version",
            "timestamp_ms",
            "sequence",
            "firmware_version",
            "pressao_raw",
            "pressao_ma",
            "pressao",
            "pressao_unidade",
            "pressao_valida",
            "pressao_status",
            "status",
        }
        missing = sorted(required.difference(payload))
        if missing:
            raise ProtocolError("Campos obrigatórios ausentes: " + ", ".join(missing))
        if not isinstance(payload["pressao_valida"], bool):
            raise ProtocolError("pressao_valida deve ser booleano")
        if (
            not isinstance(payload["firmware_version"], str)
            or not payload["firmware_version"].strip()
        ):
            raise ProtocolError("firmware_version inválida")
        try:
            schema_version = int(payload["schema_version"])
            timestamp_ms = int(payload["timestamp_ms"])
            sequence = int(payload["sequence"])
        except (TypeError, ValueError) as exc:
            raise ProtocolError(
                "schema_version, timestamp_ms e sequence devem ser inteiros"
            ) from exc
        if schema_version not in SUPPORTED_FIRMWARE_SCHEMA:
            raise ProtocolError(f"schema_version {schema_version} não suportada")
        if timestamp_ms < 0 or sequence < 0:
            raise ProtocolError("timestamp_ms e sequence não podem ser negativos")
        received_at = datetime.now()
        pressure = self._pressure_reading(payload, simulated, received_at)
        return Measurement(
            received_at=received_at,
            device_timestamp_ms=timestamp_ms,
            pressure=pressure,
            communication_state=str(payload["status"]),
            raw_message=raw.strip(),
            simulated=simulated,
            recordable=False,
            sequence=sequence,
            schema_version=schema_version,
            firmware_version=payload["firmware_version"].strip(),
        )

    def _pressure_reading(
        self, payload: dict[str, Any], simulated: bool, received_at: datetime
    ) -> SensorReading:
        try:
            device_value = optional_number(payload["pressao"])
            current = optional_number(payload["pressao_ma"])
            raw_value = optional_number(payload["pressao_raw"])
        except (TypeError, ValueError) as exc:
            raise ProtocolError("Campo numérico inválido na pressão") from exc
        cfg = self.sensor_config["pressao"]
        lower, upper = cfg.get("limite_inferior"), cfg.get("limite_superior")
        range_configured = lower is not None and upper is not None
        calculated = None
        if current is not None and range_configured:
            calculated = apply_gain_offset(
                current_to_engineering(
                    current,
                    float(lower),
                    float(upper),
                    float(cfg.get("corrente_min", 4.0)),
                    float(cfg.get("corrente_max", 20.0)),
                ),
                float(cfg.get("ganho", 1.0)),
                float(cfg.get("offset", 0.0)),
            )
        declared_valid = payload["pressao_valida"]
        if self.value_source == "software":
            value = calculated if calculated is not None else device_value
        else:
            value = device_value if device_value is not None else calculated
        if not declared_valid:
            value = None
        quality = classify_current(current, simulated)
        if not declared_valid:
            quality = ReadingQuality.INVALID
        elif current is None and device_value is not None:
            quality = ReadingQuality.SIMULATED if simulated else ReadingQuality.VALID
        if (
            self.value_source == "comparar"
            and device_value is not None
            and calculated is not None
            and quality != ReadingQuality.INVALID
            and abs(device_value - calculated) > float(cfg.get("tolerancia", 0.0))
        ):
            quality = ReadingQuality.WARNING
        if range_configured and declared_valid:
            quality = classify_value(value, float(lower), float(upper), quality)
        return SensorReading(
            value=value,
            current_ma=current,
            quality=quality,
            device_value=device_value,
            calculated_value=calculated,
            device_status=str(payload["pressao_status"]),
            raw_value=raw_value,
            unit=str(payload["pressao_unidade"]),
            timestamp=received_at,
        )
