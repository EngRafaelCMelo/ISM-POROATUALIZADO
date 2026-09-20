from __future__ import annotations

import math

PRESSURE_TO_PA = {
    "Pa": 1.0,
    "kPa": 1_000.0,
    "MPa": 1_000_000.0,
    "bar": 100_000.0,
    "psi": 6_894.757293168,
}
FLOW_TO_L_MIN = {"L/min": 1.0, "mL/min": 0.001}
FLOW_PROTOCOL_UNIT = "NL/min"


def flow_for_permeability(
    value: float,
    unit: str,
    *,
    measurement_pressure_kpa_abs: float,
    measurement_temperature_c: float,
    normal_pressure_kpa_abs: float | None = None,
    normal_temperature_c: float | None = None,
) -> tuple[float, float]:
    """Return (L/min at reference, reference kPa abs) for the gas Darcy equation.

    L/min and mL/min denote volume at measurement conditions. NL/min denotes
    volume at an explicitly supplied normal pressure and temperature. The
    isothermal Darcy equation uses Qref*Pref*Tmeasurement/Tref for normal flow.
    """
    numbers = (value, measurement_pressure_kpa_abs, measurement_temperature_c)
    if any(not math.isfinite(number) for number in numbers):
        raise ValueError("Vazão e condições de medição devem ser finitas")
    if value <= 0 or measurement_pressure_kpa_abs <= 0 or measurement_temperature_c <= -273.15:
        raise ValueError("Vazão, pressão absoluta e temperatura Kelvin devem ser positivas")
    if unit in FLOW_TO_L_MIN:
        return convert_flow(value, unit, "L/min"), measurement_pressure_kpa_abs
    if unit != FLOW_PROTOCOL_UNIT:
        raise ValueError(f"Unidade de vazão não suportada: {unit}")
    if normal_pressure_kpa_abs is None or normal_temperature_c is None:
        raise ValueError("NL/min exige pressão e temperatura normais de referência confirmadas")
    if not math.isfinite(normal_pressure_kpa_abs) or not math.isfinite(normal_temperature_c):
        raise ValueError("Referência de NL/min deve ser finita")
    if normal_pressure_kpa_abs <= 0 or normal_temperature_c <= -273.15:
        raise ValueError(
            "Referência de NL/min exige pressão absoluta e temperatura Kelvin positivas"
        )
    return (
        value * (measurement_temperature_c + 273.15) / (normal_temperature_c + 273.15),
        normal_pressure_kpa_abs,
    )


def convert_pressure(value: float, source: str, target: str) -> float:
    try:
        return value * PRESSURE_TO_PA[source] / PRESSURE_TO_PA[target]
    except KeyError as exc:
        raise ValueError(f"Unidade de pressão não suportada: {exc.args[0]}") from exc


def convert_flow(value: float, source: str, target: str) -> float:
    try:
        return value * FLOW_TO_L_MIN[source] / FLOW_TO_L_MIN[target]
    except KeyError as exc:
        raise ValueError(f"Unidade de vazão não suportada: {exc.args[0]}") from exc


def ads1115_raw_to_voltage(raw: int, full_scale_v: float = 4.096) -> float:
    if not -32768 <= raw <= 32767:
        raise ValueError("Leitura ADS1115 fora da faixa de 16 bits")
    return raw * full_scale_v / 32768.0


def voltage_to_current_ma(voltage_v: float, shunt_ohm: float = 149.7) -> float:
    if shunt_ohm <= 0:
        raise ValueError("Resistência shunt deve ser positiva")
    return voltage_v / shunt_ohm * 1000.0
