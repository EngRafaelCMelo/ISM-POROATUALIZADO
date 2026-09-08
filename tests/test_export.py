from __future__ import annotations

from datetime import datetime

import pandas as pd

from core.constants import ReadingQuality
from core.models import Measurement, SensorReading, TestDefinition as Definition
from database.database import Database
from database.repositories import CalculationRepository, EventRepository, TestRepository as Repository
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
    assert "Pressão (bar)" in frame.columns


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
        session.id, "Permeabilidade a gás", {"gas": "Helio"},
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
    assert pdf.exists() and pdf.stat().st_size > 500
    assert {"Resumo", "Medições", "Alarmes", "Marcações", "Calibração", "Cálculos"} == set(
        pd.ExcelFile(xlsx).sheet_names
    )
    measurement_columns = pd.read_excel(xlsx, sheet_name="Medições").columns
    assert "vazao" in measurement_columns
    assert "vazao_alta" not in measurement_columns
