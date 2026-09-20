"""Regressões de rastreabilidade das unidades, pausas e pontos."""

from datetime import datetime, timedelta

import pytest
from pypdf import PdfReader
from PySide6.QtWidgets import QMessageBox

from communication.modbus import FLOW_PROTOCOL_UNIT, append_crc, parse_flow_response
from core.constants import ReadingQuality
from core.models import Measurement, SensorReading
from core.models import TestDefinition as Definition
from core.units import flow_for_permeability
from database.database import Database
from database.repositories import CalculationRepository, EventRepository
from database.repositories import TestRepository as Repository
from services.export_service import ExportService
from services.test_service import TestService as Service
from ui.calculation_page import CalculationPage


def test_modbus_unit_and_reference_conversion():
    frame = parse_flow_response(append_crc(bytes.fromhex("01 03 04 00 00 03 E8")))
    assert frame.raw_uint32 == 1000
    assert frame.unit == FLOW_PROTOCOL_UNIT
    assert frame.flow_l_min == 1
    actual, pressure = flow_for_permeability(
        1,
        "NL/min",
        measurement_pressure_kpa_abs=150,
        measurement_temperature_c=20,
        normal_pressure_kpa_abs=101.325,
        normal_temperature_c=0,
    )
    assert actual == pytest.approx(293.15 / 273.15)
    assert pressure == 101.325
    assert flow_for_permeability(
        1000,
        "mL/min",
        measurement_pressure_kpa_abs=150,
        measurement_temperature_c=20,
    ) == (1, 150)
    with pytest.raises(ValueError, match="NL/min exige"):
        flow_for_permeability(
            1,
            "NL/min",
            measurement_pressure_kpa_abs=150,
            measurement_temperature_c=20,
        )


@pytest.mark.parametrize("paused", [0, 3, 8])
def test_persisted_durations_and_pdf(tmp_path, paused):
    database = Database(tmp_path / "duration.db")
    database.initialize()
    tests = Repository(database)
    session = tests.create(Definition(f"DURATION-{paused}", "Amostra"))
    start = datetime.fromisoformat(tests.get(session.id)["inicio"])
    tests.finish(session.id, paused_seconds=paused, finished_at=start + timedelta(seconds=20))
    row = tests.get(session.id)
    assert row["duracao_segundos"] == 20 - paused
    assert row["duracao_decorrida_segundos"] == 20
    assert row["duracao_pausada_segundos"] == paused
    pdf = ExportService(tests, EventRepository(database)).export_pdf(session.id, tmp_path)
    text = " ".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert "Tempo ativo de aquisição" in text
    assert "Tempo pausado" in text
    assert "Tempo total decorrido" in text
    database.close()


def test_finish_during_pause_accumulates_current_interval(tmp_path):
    database = Database(tmp_path / "pause.db")
    database.initialize()
    tests = Repository(database)
    service = Service(tests, EventRepository(database))
    session = service.start(Definition("PAUSE-1", "Amostra"))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE ensaios SET inicio=? WHERE id=?",
            ((datetime.now() - timedelta(seconds=10)).isoformat(), session.id),
        )
    service.toggle_pause()
    service._paused_at = datetime.now() - timedelta(seconds=4)
    service.finish()
    row = tests.get(session.id)
    assert 3.9 <= row["duracao_pausada_segundos"] <= 5
    assert 5 <= row["duracao_segundos"] <= 7
    assert row["duracao_decorrida_segundos"] == pytest.approx(
        row["duracao_segundos"] + row["duracao_pausada_segundos"]
    )
    database.close()


def test_multiple_pauses_accumulate(tmp_path):
    database = Database(tmp_path / "pauses.db")
    database.initialize()
    tests = Repository(database)
    service = Service(tests, EventRepository(database))
    session = service.start(Definition("PAUSE-2", "Amostra"))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE ensaios SET inicio=? WHERE id=?",
            ((datetime.now() - timedelta(seconds=10)).isoformat(), session.id),
        )
    for _ in range(2):
        service.toggle_pause()
        service._paused_at = datetime.now() - timedelta(milliseconds=100)
        service.toggle_pause()
    service.finish()
    assert 0.19 <= tests.get(session.id)["duracao_pausada_segundos"] <= 0.5
    database.close()


def test_v4_duration_migration_preserves_legacy_meaning(tmp_path):
    database = Database(tmp_path / "old.db")
    database.initialize()
    tests = Repository(database)
    session = tests.create(Definition("OLD-1", "Amostra"))
    tests.finish(session.id)
    with database.transaction() as connection:
        connection.execute("UPDATE ensaios SET duracao_segundos=123 WHERE id=?", (session.id,))
        connection.execute("ALTER TABLE ensaios DROP COLUMN duracao_decorrida_segundos")
        connection.execute("ALTER TABLE ensaios DROP COLUMN duracao_pausada_segundos")
        connection.execute("UPDATE schema_version SET version=4")
    database.initialize()
    row = tests.get(session.id)
    assert row["duracao_segundos"] == 123
    assert row["duracao_decorrida_segundos"] is None
    assert row["duracao_pausada_segundos"] is None
    with database.read_connection() as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchone()[0] == 5
    database.close()


def test_transaction_rolls_back_non_sql_exception(tmp_path):
    database = Database(tmp_path / "rollback.db")
    database.initialize()
    with pytest.raises(RuntimeError):
        with database.transaction() as connection:
            connection.execute("INSERT INTO usuarios(nome) VALUES ('Temporario')")
            raise RuntimeError("falha de aplicação")
    with database.read_connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM usuarios WHERE nome='Temporario'").fetchone()[
                0
            ]
            == 0
        )
    database.close()


def test_klinkenberg_duplicate_and_invalidation(qt_application, monkeypatch):
    page = CalculationPage({"calculos": {"pressao_atmosferica_kpa": 101.325}})
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    page.last_permeability = ({}, {"mean_pressure_kpa_abs": 100, "permeability_md": 12})
    page._calculation_identity = ("snapshot-1", (1,))
    page._add_point()
    page._add_point()
    assert page.points.rowCount() == 1
    assert messages == ["Este resultado já foi adicionado"]
    page._calculation_identity = ("snapshot-2", (1,))
    page.last_permeability = ({}, {"mean_pressure_kpa_abs": 200, "permeability_md": 11})
    page._add_point()
    page._klinkenberg()
    assert page.last_klinkenberg is not None
    page.points.selectRow(0)
    page._remove_point()
    assert page.last_klinkenberg is None
    assert not page.save_klinkenberg.isEnabled()


def test_normal_unit_survives_capture_storage_and_exports(qt_application, tmp_path):
    settings = {
        "calculos": {"pressao_atmosferica_kpa": 101.325},
        "flowmeter": {"normal_pressure_kpa_abs": 101.325, "normal_temperature_c": 0},
    }
    page = CalculationPage(settings)
    definition = Definition(
        "UNIT-1",
        "Amostra",
        sample_length_mm=50,
        sample_diameter_mm=25,
        pressure_unit="kPa",
        pressure_reference="absoluta",
        flow_unit="NL/min",
    )
    page.set_session(definition)
    now = datetime.now()
    measurement = Measurement(
        now,
        pressure=SensorReading(value=200, unit="kPa", quality=ReadingQuality.VALID, timestamp=now),
        flow=SensorReading(value=2, unit="NL/min", quality=ReadingQuality.VALID, timestamp=now),
        communication_state="OK",
    )
    page.update_measurement(measurement)
    page.outlet.setValue(100)
    page._capture()
    page._calculate()
    assert page._captured_snapshot.flow_unit == "NL/min"
    _, inputs, results, _ = page.pending_results()[0]
    assert inputs["flow_unit"] == "NL/min"
    assert inputs["flow_reference_temperature_c"] == 0
    database = Database(tmp_path / "units.db")
    database.initialize()
    tests = Repository(database)
    session = tests.create(definition)
    tests.save_measurement(session.id, measurement)
    CalculationRepository(database).save(session.id, "Permeabilidade a gás", inputs, results)
    tests.finish(session.id)
    assert tests.measurements(session.id)[0]["unidade_vazao"] == "NL/min"
    exports = ExportService(tests, EventRepository(database))
    csv = exports.export_csv(session.id, tmp_path)
    json_file = exports.export_json(session.id, tmp_path)
    xlsx = exports.export_xlsx(session.id, tmp_path)
    pdf = exports.export_pdf(session.id, tmp_path)
    assert "NL/min" in csv.read_text(encoding="utf-8")
    assert '"unidade_vazao": "NL/min"' in json_file.read_text(encoding="utf-8")
    assert xlsx.exists()
    text = " ".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert "NL/min" in text and "vazão normal referida" in text
    database.close()
