from __future__ import annotations

import json
from datetime import datetime

from core.constants import ReadingQuality
from core.models import Measurement, SensorReading
from core.models import TestDefinition as Definition
from database.database import Database
from database.repositories import CalculationRepository
from ui.calculation_page import CalculationPage


def test_permeability_inputs_are_complete_and_persisted(qt_application, tmp_path) -> None:
    page = CalculationPage(
        {
            "calculos": {"pressao_atmosferica_kpa": 101.325},
        }
    )
    definition = Definition(
        code="TRACE-1",
        sample_name="Amostra",
        sample_length_mm=50,
        sample_diameter_mm=25,
        pressure_unit="kPa",
    )
    page.set_session(definition)
    timestamp = datetime.now()
    page.update_measurement(
        Measurement(
            timestamp,
            pressure=SensorReading(
                value=200,
                quality=ReadingQuality.VALID,
                timestamp=timestamp,
            ),
            flow=SensorReading(
                value=2,
                quality=ReadingQuality.VALID,
                timestamp=timestamp,
                unit="L/min",
            ),
            simulated=True,
            communication_state="OK",
        )
    )
    page.outlet_mode.setCurrentIndex(page.outlet_mode.findData("atmosphere"))
    page.flow_ref.setValue(101.325)
    page._capture()
    page._calculate()
    pending = page.pending_results()
    assert len(pending) == 1
    _, inputs, results, _ = pending[0]
    expected = {
        "gas",
        "viscosity_upa_s",
        "temperatura_c",
        "comprimento_mm",
        "diametro_mm",
        "cross_section_area_m2",
        "inlet_pressure_entered",
        "inlet_pressure_kpa_abs",
        "outlet_pressure_entered",
        "outlet_pressure_kpa_abs",
        "modo_pressao_saida",
        "atmospheric_pressure_kpa",
        "pressure_reference",
        "flow_l_min",
        "flow_reference_pressure_kpa_abs",
        "units",
        "data_origin",
        "reading_timestamps",
        "simulado",
    }
    assert expected <= inputs.keys()
    assert inputs["data_origin"] == "leitura_combinada"
    assert inputs["simulado"] is True
    assert {"permeability_m2", "permeability_darcy", "permeability_md"} <= results.keys()

    database = Database(tmp_path / "trace.db")
    database.initialize()
    repository = CalculationRepository(database)
    from database.repositories import TestRepository

    session = TestRepository(database).create(definition)
    repository.save(session.id, "Permeabilidade a gás", inputs, results)
    saved_inputs = json.loads(repository.list(session.id)[0]["entradas_json"])
    assert expected <= saved_inputs.keys()
    database.close()


def test_legacy_calculation_with_missing_fields_remains_readable(qt_application) -> None:
    page = CalculationPage({"calculos": {"pressao_atmosferica_kpa": 101.325}})
    page.populate_history(
        [
            {
                "timestamp": datetime.now().isoformat(),
                "tipo": "Permeabilidade a gás",
                "resultados_json": json.dumps({"permeability_md": 10.0}),
                "observacoes": None,
            }
        ]
    )
    assert page.history.rowCount() == 1
    assert "10.0" in page.history.item(0, 2).text()


def test_klinkenberg_point_identity_belongs_to_calculation_run(qt_application, monkeypatch) -> None:
    page = CalculationPage(
        {
            "calculos": {"pressao_atmosferica_kpa": 101.325},
            "flowmeter": {
                "unit": "L/min",
                "volume_reference_pressure_kpa_abs": 101.325,
            },
        }
    )
    definition = Definition(
        code="REP-1",
        sample_name="Repetição",
        sample_length_mm=50,
        sample_diameter_mm=25,
        pressure_unit="kPa",
        flow_unit="L/min",
    )
    page.set_session(definition)
    now = datetime.now()
    page.update_measurement(
        Measurement(
            now,
            pressure=SensorReading(
                value=200, quality=ReadingQuality.VALID, timestamp=now, unit="kPa"
            ),
            flow=SensorReading(value=2, quality=ReadingQuality.VALID, timestamp=now, unit="L/min"),
            communication_state="OK",
        )
    )
    page.outlet_mode.setCurrentIndex(page.outlet_mode.findData("atmosphere"))
    page.flow_ref.setValue(101.325)
    page._capture()
    monkeypatch.setattr("ui.calculation_page.QMessageBox.information", lambda *args: None)
    page._calculate()
    first_identity = page._calculation_identity
    page._add_point()
    page._add_point()
    assert page.points.rowCount() == 1
    page._calculate()
    assert page._calculation_identity != first_identity
    page._add_point()
    assert page.points.rowCount() == 2
    page.last_klinkenberg = ({}, {})
    page.save_klinkenberg.setEnabled(True)
    page.points.selectRow(0)
    page._remove_point()
    assert page.last_klinkenberg is None
    assert not page.save_klinkenberg.isEnabled()
