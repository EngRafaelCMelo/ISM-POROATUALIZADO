from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.models import Measurement


@dataclass(frozen=True, slots=True)
class PreflightResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def run_preflight(
    config: dict[str, Any],
    measurement: Measurement,
    *,
    esp32_connected: bool,
    flowmeter_connected: bool,
    database_writable: bool,
    configuration_errors: list[str] | None = None,
    calibration_available: bool = True,
) -> PreflightResult:
    errors = list(configuration_errors or [])
    esp_port = str(config.get("comunicacao", {}).get("porta", "")).strip()
    flow_port = str(config.get("flowmeter", {}).get("porta", "")).strip()
    if not esp32_connected:
        errors.append("Conecte o ESP32 e aguarde uma leitura de pressão")
    if not flowmeter_connected:
        errors.append("Conecte o flowmeter pelo adaptador USB–RS485 e feche o QModMaster")
    if esp_port and flow_port and esp_port.casefold() == flow_port.casefold():
        errors.append("Selecione portas COM diferentes para ESP32 e flowmeter")
    if not measurement.pressure.valid:
        errors.append("A pressão precisa estar válida e recente")
    if not measurement.flow.valid:
        errors.append("A vazão precisa estar válida e recente")
    for label, reading, sensor_key in (
        ("pressão", measurement.pressure, "pressao"),
        ("vazão", measurement.flow, "vazao"),
    ):
        critical = config.get("sensores", {}).get(sensor_key, {}).get("critico")
        if reading.valid and critical is not None and reading.value is not None:
            if reading.value >= float(critical):
                errors.append(
                    f"A {label} está em condição crítica ({reading.value:g} >= {float(critical):g})"
                )
    if not database_writable:
        errors.append("O banco de dados não está gravável")
    if config.get("preflight", {}).get("exigir_calibracao", False) and not calibration_available:
        errors.append("Cadastre e ative a calibração obrigatória")
    return PreflightResult(tuple(dict.fromkeys(errors)))
