from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from core.calculations import apply_gain_offset, current_to_engineering
from core.constants import ReadingQuality, SERIAL_SCHEMA_VERSION
from core.models import Measurement, SensorReading
from core.validation import classify_current, optional_number


class ProtocolError(ValueError):
    """Mensagem recebida não segue o contrato serial suportado."""


class LegacyProtocolAdapter:
    """Compatibilidade temporária centralizada com o protocolo antigo."""

    @staticmethod
    def supports(payload: dict[str, Any]) -> bool:
        return "schema_version" not in payload and any(key in payload for key in ("pressao", "pressao_ma", "vazao", "vazao_baixa", "vazao_alta"))

    @staticmethod
    def adapt(payload: dict[str, Any]) -> dict[str, Any]:
        flow = payload.get("vazao", payload.get("vazao_baixa", payload.get("vazao_alta")))
        return {
            "schema_version": SERIAL_SCHEMA_VERSION, "sequence": payload.get("sequence"),
            "uptime_ms": payload.get("uptime_ms", payload.get("timestamp_ms")),
            "pressao": {"current_ma": payload.get("pressao_ma"), "value": payload.get("pressao"), "unit": payload.get("unidade_pressao", "bar"), "valid": payload.get("pressao") is not None or payload.get("pressao_ma") is not None},
            "vazao": {"value": flow, "unit": payload.get("unidade_vazao", "L/min"), "valid": flow is not None},
            "status": payload.get("status", "OK"), "alarms": payload.get("alarms", []),
            "firmware_version": payload.get("firmware_version", "legado"),
        }


class ProtocolParser:
    def __init__(self, sensor_config: dict[str, dict[str, Any]], value_source: str = "comparar"):
        self.sensor_config = sensor_config
        self.value_source = value_source

    def parse(self, raw: str, simulated: bool = False) -> Measurement:
        try:
            payload = json.loads(raw.strip())
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"JSON inválido ou truncado: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ProtocolError("A mensagem precisa ser um objeto JSON")
        if LegacyProtocolAdapter.supports(payload):
            payload = LegacyProtocolAdapter.adapt(payload)
        if payload.get("schema_version") != SERIAL_SCHEMA_VERSION:
            raise ProtocolError("schema_version ausente ou não suportado")
        if not isinstance(payload.get("pressao"), dict) or not isinstance(payload.get("vazao"), dict):
            raise ProtocolError("Objetos pressao e vazao são obrigatórios")
        status = str(payload.get("status", "ERROR")).upper()
        force_invalid = status != "OK" and not simulated
        sequence = self._optional_int(payload.get("sequence"), "sequence")
        uptime = self._optional_int(payload.get("uptime_ms"), "uptime_ms")
        alarms = payload.get("alarms", [])
        if not isinstance(alarms, list) or not all(isinstance(item, str) for item in alarms):
            raise ProtocolError("alarms deve ser uma lista de textos")
        return Measurement(
            received_at=datetime.now(), device_timestamp_ms=uptime,
            pressure=self._pressure(payload["pressao"], simulated, force_invalid),
            flow=self._flow(payload["vazao"], simulated, force_invalid),
            communication_state=status, raw_message=raw.strip(), simulated=simulated,
            schema_version=SERIAL_SCHEMA_VERSION, sequence=sequence, uptime_ms=uptime,
            alarms=tuple(alarms), firmware_version=str(payload.get("firmware_version", "")),
        )

    @staticmethod
    def _optional_int(value: Any, field: str) -> int | None:
        if value is None:
            return None
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"{field} inválido") from exc
        if result < 0:
            raise ProtocolError(f"{field} não pode ser negativo")
        return result

    def _pressure(self, data: dict[str, Any], simulated: bool, force_invalid: bool) -> SensorReading:
        try:
            current, value = optional_number(data.get("current_ma")), optional_number(data.get("value"))
            raw_value = optional_number(data.get("ads_raw"))
        except (TypeError, ValueError) as exc:
            raise ProtocolError("Campo numérico inválido em pressao") from exc
        cfg = self.sensor_config["pressao"]
        calculated = None
        lower, upper = cfg.get("limite_inferior"), cfg.get("limite_superior")
        if current is not None and lower is not None and upper is not None:
            calculated = apply_gain_offset(current_to_engineering(current, float(lower), float(upper)), float(cfg.get("ganho", 1.0)), float(cfg.get("offset", 0.0)))
        if self.value_source == "software" and calculated is not None:
            value = calculated
        quality = classify_current(current, simulated)
        if current is None and value is not None:
            quality = ReadingQuality.SIMULATED if simulated else ReadingQuality.VALID
        if force_invalid or data.get("valid") is not True or value is None:
            quality = ReadingQuality.INVALID if value is not None else ReadingQuality.MISSING
        valid = quality in (ReadingQuality.VALID, ReadingQuality.SIMULATED)
        return SensorReading(value, current, quality, value, calculated, str(data.get("unit", cfg.get("unidade", ""))), valid, raw_value)

    def _flow(self, data: dict[str, Any], simulated: bool, force_invalid: bool) -> SensorReading:
        try:
            value, raw_value = optional_number(data.get("value")), optional_number(data.get("raw_register"))
        except (TypeError, ValueError) as exc:
            raise ProtocolError("Campo numérico inválido em vazao") from exc
        valid = data.get("valid") is True and value is not None and not force_invalid
        quality = (ReadingQuality.SIMULATED if simulated else ReadingQuality.VALID) if valid else (ReadingQuality.MISSING if value is None else ReadingQuality.INVALID)
        return SensorReading(value=value, quality=quality, device_value=value, unit=str(data.get("unit", self.sensor_config["vazao"].get("unidade", ""))), valid=valid, raw_value=raw_value)
