from __future__ import annotations

import pytest

from core.models import TestDefinition as Definition
from ui.calculation_page import CalculationPage


def test_guided_porosity_workflow_creates_pending_result(config_data: dict) -> None:
    page = CalculationPage(config_data)
    definition = Definition(
        code="ENS-2026-0100",
        sample_name="Testemunho",
        test_type="Porosimetria por gás",
        pressure_unit="kPa",
        pressure_reference="absoluta",
        bulk_volume_cm3=25.0,
        sample_mass_g=50.0,
    )
    page.set_session(definition, "active")
    page.sample_chamber.setValue(50.0)
    page.expansion_chamber.setValue(20.0)
    page.p0.setValue(100.0)

    for equilibrium_pressure in (220.0, 220.05, 219.95):
        page.p1.setValue(300.0)
        page.p2.setValue(equilibrium_pressure)
        page._add_boyle_cycle()

    page._calculate_boyle()

    assert page.last_boyle is not None
    assert page.last_boyle[1]["porosity_mean_percent"] == pytest.approx(20.0, rel=2e-3)
    assert page.boyle_quality.text() == "Repetibilidade aprovada"
    assert page.save_boyle_button.isEnabled()
    assert [result[0] for result in page.pending_results()] == ["Lei de Boyle"]

    page.mark_saved("Lei de Boyle")
    assert page.pending_results() == []
    assert not page.save_boyle_button.isEnabled()
    page.close()


def test_new_session_clears_results_from_previous_test(config_data: dict) -> None:
    page = CalculationPage(config_data)
    first = Definition(code="ENS-1", sample_name="A")
    second = Definition(code="ENS-2", sample_name="B")
    page.set_session(first)
    page.last_boyle = ({"p0": 1}, {"porosity_mean_percent": 10})
    page._dirty_results.add("Lei de Boyle")

    page.set_session(second)

    assert page.last_boyle is None
    assert page.pending_results() == []
    assert page.boyle_cycles.rowCount() == 0
    page.close()
