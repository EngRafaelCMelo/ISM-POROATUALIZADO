from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from core.constants import ReadingQuality
from core.models import Measurement, SensorReading
from core.models import TestDefinition as Definition
from database.database import Database
from database.repositories import CalculationRepository, EventRepository
from database.repositories import TestRepository as Repository
from services.export_service import ExportService


def test_export_csv(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    tests = Repository(database)
    events = EventRepository(database)
    session = tests.create(Definition(code="ENS-2026-0001", sample_name="A"))
    tests.save_measurement(
        session.id,
        Measurement(
            datetime.now(),
            pressure=SensorReading(2, 7.2, ReadingQuality.VALID),
            flow=SensorReading(1, None, ReadingQuality.VALID),
        ),
    )
    target = ExportService(tests, events).export_csv(session.id, tmp_path / "exports")
    assert target.exists()
    frame = pd.read_csv(target, sep=";")
    assert len(frame) == 1
    assert "Pressão (psi)" in frame.columns


def test_export_xlsx_json_and_pdf(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    tests = Repository(database)
    events = EventRepository(database)
    session = tests.create(Definition(code="ENS-2026-0002", sample_name="Amostra B"))
    tests.save_measurement(
        session.id,
        Measurement(
            datetime.now(),
            pressure=SensorReading(4, 10.4, ReadingQuality.VALID),
            flow=SensorReading(2, None, ReadingQuality.VALID),
        ),
    )
    tests.finish(session.id, "Ensaio de validação")
    CalculationRepository(database).save(
        session.id,
        "Permeabilidade a gás",
        {"gas": "Helio"},
        {"permeability_md": 20.0},
    )
    service = ExportService(tests, events)
    xlsx = service.export_xlsx(session.id, tmp_path / "exports")
    json_file = service.export_json(session.id, tmp_path / "exports")
    pdf = service.export_pdf(session.id, tmp_path / "exports")
    assert xlsx.exists() and xlsx.stat().st_size > 0
    assert json_file.exists() and '"medicoes"' in json_file.read_text(encoding="utf-8")
    assert '"calculos"' in json_file.read_text(encoding="utf-8")
    exported_json = json_file.read_text(encoding="utf-8")
    assert '"vazao"' in exported_json
    assert '"vazao_alta"' not in exported_json
    assert "NaN" not in exported_json
    json.loads(exported_json, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    assert pdf.exists() and pdf.stat().st_size > 500
    assert {"Resumo", "Medições", "Alarmes", "Marcações", "Calibração", "Cálculos"} == set(
        pd.ExcelFile(xlsx).sheet_names
    )
    measurement_columns = pd.read_excel(xlsx, sheet_name="Medições").columns
    assert "vazao" in measurement_columns
    assert "vazao_alta" not in measurement_columns


def test_legacy_flow_is_coalesced_without_duplicate_columns() -> None:
    frame = pd.DataFrame(
        {
            "vazao": [2.0, None],
            "vazao_baixa": [1.0, 1.5],
            "vazao_alta": [9.0, 9.0],
        }
    )
    current = ExportService._current_measurements(frame)
    assert list(current.columns).count("vazao") == 1
    assert current["vazao"].tolist() == [2.0, 1.5]
    assert not any(column.startswith("vazao_baixa") for column in current.columns)


def test_json_records_replace_pandas_missing_values_with_null() -> None:
    records = ExportService._records(pd.DataFrame({"vazao": [1.0, float("nan")]}))
    assert records == [{"vazao": 1.0}, {"vazao": None}]
