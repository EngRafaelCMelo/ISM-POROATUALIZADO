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
            flow=SensorReading(value=10, quality=ReadingQuality.VALID, valid=True),
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
            flow=SensorReading(value=20, quality=ReadingQuality.VALID, valid=True),
        ),
    )
    tests.finish(session.id, "Ensaio de validação")
    CalculationRepository(database).save(
        session.id, "Lei de Boyle", {"gas": "Helio"},
        {"skeletal_volume_mean_cm3": 20.0, "porosity_mean_percent": 20.0},
    )
    service = ExportService(tests, events)
    xlsx = service.export_xlsx(session.id, tmp_path / "exports")
    json_file = service.export_json(session.id, tmp_path / "exports")
    pdf = service.export_pdf(session.id, tmp_path / "exports")
    assert xlsx.exists() and xlsx.stat().st_size > 0
    assert json_file.exists() and '"medicoes"' in json_file.read_text(encoding="utf-8")
    assert '"calculos"' in json_file.read_text(encoding="utf-8")
    assert pdf.exists() and pdf.stat().st_size > 500
    assert {"Resumo", "Medições", "Alarmes", "Marcações", "Calibração", "Cálculos"} == set(
        pd.ExcelFile(xlsx).sheet_names
    )
