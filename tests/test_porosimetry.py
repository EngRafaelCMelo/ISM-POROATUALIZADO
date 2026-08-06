from __future__ import annotations

import pytest

from core.porosimetry import (
    DARCY_M2,
    absolute_pressure_kpa,
    calculate_boyle_cycle,
    calculate_gas_permeability,
    calculate_klinkenberg,
    cylindrical_volume_cm3,
    summarize_boyle_cycles,
)


def test_cylindrical_bulk_volume() -> None:
    assert cylindrical_volume_cm3(50, 25.4) == pytest.approx(25.335, rel=1e-4)


def test_boyle_cycle_sample_chamber_expansion() -> None:
    # Vc=50; amostra=20; espaço livre=30. Com Vr=20, P0=100 e P1=300,
    # conservação fornece P2=220 kPa.
    result = calculate_boyle_cycle(
        sample_chamber_volume_cm3=50,
        expansion_volume_cm3=20,
        initial_sample_pressure_kpa_abs=300,
        equilibrium_pressure_kpa_abs=220,
        initial_expansion_pressure_kpa_abs=100,
        bulk_volume_cm3=25,
        sample_mass_g=50,
    )
    assert result.free_volume_cm3 == pytest.approx(30)
    assert result.skeletal_volume_cm3 == pytest.approx(20)
    assert result.pore_volume_cm3 == pytest.approx(5)
    assert result.porosity_percent == pytest.approx(20)
    assert result.skeletal_density_g_cm3 == pytest.approx(2.5)
    assert result.bulk_density_g_cm3 == pytest.approx(2.0)


def test_boyle_summary_repeatability() -> None:
    cycles = [
        calculate_boyle_cycle(
            sample_chamber_volume_cm3=50, expansion_volume_cm3=20,
            initial_sample_pressure_kpa_abs=300, equilibrium_pressure_kpa_abs=p2,
            initial_expansion_pressure_kpa_abs=100,
        )
        for p2 in (220.0, 220.05, 219.95)
    ]
    summary = summarize_boyle_cycles(cycles, 0.5)
    assert summary.cycles == 3
    assert summary.repeatability_ok
    assert summary.skeletal_volume_mean_cm3 == pytest.approx(20, rel=1e-3)


def test_absolute_gauge_conversion() -> None:
    assert absolute_pressure_kpa(1.0, "bar", "manometrica", 101.325) == pytest.approx(201.325)


def test_compressible_gas_permeability() -> None:
    result = calculate_gas_permeability(
        flow_l_min=1.0,
        viscosity_upa_s=20.0,
        length_mm=50.0,
        diameter_mm=25.4,
        inlet_pressure_kpa_abs=300.0,
        outlet_pressure_kpa_abs=100.0,
    )
    expected = 2 * 20e-6 * 0.05 * (1e-3 / 60) * 100_000 / (
        (3.141592653589793 * 0.0254**2 / 4) * (300_000**2 - 100_000**2)
    )
    assert result.permeability_m2 == pytest.approx(expected)
    assert result.permeability_darcy == pytest.approx(expected / DARCY_M2)


def test_klinkenberg_linear_fit() -> None:
    # k_app = 100 + 5000/Pmean (mD, kPa)
    points = [(100.0, 150.0), (200.0, 125.0), (400.0, 112.5)]
    result = calculate_klinkenberg(points)
    assert result.intrinsic_permeability_md == pytest.approx(100)
    assert result.slip_factor_kpa == pytest.approx(50)
    assert result.r_squared == pytest.approx(1)
