from __future__ import annotations

PRESSURE_TO_PA = {"Pa": 1.0, "kPa": 1_000.0, "MPa": 1_000_000.0, "bar": 100_000.0, "psi": 6_894.757293168}
FLOW_TO_L_MIN = {"L/min": 1.0, "mL/min": 0.001}


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
