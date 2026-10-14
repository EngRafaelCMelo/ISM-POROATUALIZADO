from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.models import Measurement


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PreflightResult:
    errors: tuple[str, ...]
    checks: tuple[PreflightCheck, ...] = ()

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
    communication_stable: bool | None = None,
    sample_selected: bool | None = None,
    required_parameters_filled: bool | None = None,
    confinement_pressure_setpoint: float | None = None,
    blanket_temperature_setpoint: float | None = None,
    report_path_available: bool | None = None,
) -> PreflightResult:
    errors = list(configuration_errors or [])
    checks: list[PreflightCheck] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append(PreflightCheck(name, ok, detail))
        if not ok:
            errors.append(detail)

    esp_port = str(config.get("comunicacao", {}).get("porta", "")).strip()
    flow_port = str(config.get("flowmeter", {}).get("porta", "")).strip()
    check("ESP32 conectado", esp32_connected, "Conecte o ESP32 e aguarde uma leitura de pressão")
    check(
        "Flowmeter conectado",
        flowmeter_connected,
        "Conecte o flowmeter pelo adaptador USB-RS485 e feche o QModMaster",
    )
    check(
        "Comunicação estável",
        True if communication_stable is None else communication_stable,
        "Aguarde uma sequência estável de leituras do ESP32 e do flowmeter",
    )
    ports_ok = not (esp_port and flow_port and esp_port.casefold() == flow_port.casefold())
    check(
        "Portas independentes", ports_ok, "Selecione portas COM diferentes para ESP32 e flowmeter"
    )
    check(
        "Pressão válida e recente",
        measurement.pressure.valid,
        "A pressão precisa estar válida e recente",
    )
    check(
        "Vazão válida e recente", measurement.flow.valid, "A vazão precisa estar válida e recente"
    )
    check(
        "Amostra selecionada",
        True if sample_selected is None else sample_selected,
        "Selecione a amostra antes de iniciar o ensaio",
    )
    check(
        "Parâmetros obrigatórios preenchidos",
        True if required_parameters_filled is None else required_parameters_filled,
        "Preencha os parâmetros obrigatórios da amostra, do gás e da aquisição",
    )

    conditions = config.get("condicoes_operacionais", {})
    confinement_ok = True
    if confinement_pressure_setpoint is not None:
        confinement_ok = (
            float(conditions.get("pressao_confinamento_min_psi", 0.0))
            <= confinement_pressure_setpoint
            <= float(conditions.get("pressao_confinamento_max_psi", 1000.0))
        )
    check(
        "Pressão de confinamento válida",
        confinement_ok,
        "Informe um setpoint de pressão de confinamento dentro da faixa configurada",
    )
    temperature_ok = True
    if blanket_temperature_setpoint is not None:
        temperature_ok = (
            float(conditions.get("temperatura_min_c", 0.0))
            <= blanket_temperature_setpoint
            <= float(conditions.get("temperatura_max_c", 200.0))
        )
    check(
        "Temperatura da manta válida",
        temperature_ok,
        "Informe um setpoint de temperatura da manta dentro da faixa configurada",
    )
    check(
        "Caminho do relatório disponível",
        True if report_path_available is None else report_path_available,
        "Escolha um diretório de relatório gravável",
    )
    for label, reading, sensor_key in (
        ("pressão", measurement.pressure, "pressao"),
        ("vazão", measurement.flow, "vazao"),
    ):
        critical = config.get("sensores", {}).get(sensor_key, {}).get("critico")
        if (
            reading.valid
            and critical is not None
            and reading.value is not None
            and reading.value >= float(critical)
        ):
            errors.append(
                f"A {label} está em condição crítica ({reading.value:g} >= {float(critical):g})"
            )
    check("Banco de dados acessível", database_writable, "O banco de dados não está gravável")
    calibration_ok = (
        not config.get("preflight", {}).get("exigir_calibracao", False) or calibration_available
    )
    check("Calibração disponível", calibration_ok, "Cadastre e ative a calibração obrigatória")
    return PreflightResult(tuple(dict.fromkeys(errors)), tuple(checks))
