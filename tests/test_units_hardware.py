from __future__ import annotations

import pytest

from core.calculations import current_to_engineering
from core.units import ads1115_raw_to_voltage, convert_flow, convert_pressure, voltage_to_current_ma


def test_ads1115_voltage_and_shunt_current() -> None:
    raw = 12000
    voltage = ads1115_raw_to_voltage(raw)
    assert voltage == pytest.approx(1.5)
    assert voltage_to_current_ma(voltage) == pytest.approx(10.02004, rel=1e-5)


@pytest.mark.parametrize("current,voltage", [(4.0, 0.5988), (20.0, 2.994)])
def test_shunt_149_7_at_endpoints(current: float, voltage: float) -> None:
    assert voltage_to_current_ma(voltage, 149.7) == pytest.approx(current)


def test_pressure_calibration_and_real_unit_conversions() -> None:
    assert current_to_engineering(12, 0, 16) == pytest.approx(8)
    assert convert_pressure(1, "bar", "kPa") == pytest.approx(100)
    assert convert_pressure(1, "MPa", "bar") == pytest.approx(10)
    assert convert_pressure(1, "bar", "psi") == pytest.approx(14.5037738)
    assert convert_flow(1, "L/min", "mL/min") == pytest.approx(1000)
