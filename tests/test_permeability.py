import pytest
from core.permeability import absolute_pressure_kpa, calculate_gas_permeability, calculate_klinkenberg

def test_compressible_gas_permeability_known_result():
    result = calculate_gas_permeability(flow_l_min=1, viscosity_upa_s=18, length_mm=100, diameter_mm=25.4, inlet_pressure_kpa_abs=300, outlet_pressure_kpa_abs=100, flow_reference_pressure_kpa_abs=100)
    assert result.permeability_m2 == pytest.approx(1.480e-13, rel=0.01)
    assert result.permeability_darcy == pytest.approx(result.permeability_m2 / 9.869233e-13)
    assert result.permeability_md == pytest.approx(result.permeability_darcy * 1000)

def test_gauge_and_absolute_pressure():
    assert absolute_pressure_kpa(1, "bar", "manometrica", 101.325) == pytest.approx(201.325)
    assert absolute_pressure_kpa(1, "bar", "absoluta", 101.325) == 100

def test_klinkenberg_intercept():
    result = calculate_klinkenberg([(100, 12), (200, 11)])
    assert result.intrinsic_permeability_md == pytest.approx(10)
    assert result.slip_factor_kpa == pytest.approx(20)
