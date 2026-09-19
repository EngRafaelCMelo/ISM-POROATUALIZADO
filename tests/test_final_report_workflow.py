from __future__ import annotations

from datetime import datetime

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from config.settings import AppPaths, ConfigManager
from core.constants import ReadingQuality
from core.models import SensorReading
from core.models import TestDefinition as Definition
from database.database import Database
from ui.main_window import MainWindow


def test_finishing_test_generates_pdf_automatically(tmp_path, monkeypatch) -> None:
    paths = AppPaths(
        root=tmp_path,
        data=tmp_path / "data",
        logs=tmp_path / "logs",
        exports=tmp_path / "exports",
        config=tmp_path / "config",
    )
    for directory in (paths.data, paths.logs, paths.exports, paths.config):
        directory.mkdir()
    config = ConfigManager(paths)
    database = Database(config.database_path)
    database.initialize()
    window = MainWindow(config, database, paths)
    assert len(window.advanced_nav_buttons) == 3
    session = window.test_service.start(
        Definition(
            code="ENS-2026-0200",
            sample_name="Amostra relatório",
            test_type="Permeabilidade",
            export_directory=str(paths.exports),
        )
    )
    window.calculation_test_id = session.id
    window.calculations.set_session(session.definition, "active")
    window.calculations.last_permeability = (
        {"gas": "Helio", "data_origin": "entrada_manual"},
        {"permeability_md": 12.5, "mean_pressure_kpa_abs": 150.0},
    )
    window.calculations._dirty_results.add("Permeabilidade a gás")
    now = datetime.now()
    window.acquisition.latest_pressure = SensorReading(
        value=150.0,
        quality=ReadingQuality.VALID,
        device_status="OK",
        unit="psi",
        timestamp=now,
    )
    window.acquisition.latest_flow = SensorReading(
        value=2.5,
        quality=ReadingQuality.VALID,
        device_status="OK",
        unit="NL/min",
        timestamp=now,
    )
    window.acquisition._dirty = True

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *args, **kwargs: ("Ensaio concluído", True)),
    )

    window._finish_test()

    assert window.test_service.current is None
    for _ in range(800):
        generated = list(paths.exports.glob("ENS-2026-0200_relatorio_final*.pdf"))
        if generated and generated[0].stat().st_size > 500 and not window.export_workers:
            break
        QTest.qWait(25)
    reports = list(paths.exports.glob("ENS-2026-0200_relatorio_final*.pdf"))
    assert len(reports) == 1
    assert reports[0].stat().st_size > 500
    saved = window.calculation_repository.list(session.id)
    assert len(saved) == 1
    assert saved[0]["tipo"] == "Permeabilidade a gás"
    measurements = window.test_repository.measurements(session.id)
    assert len(measurements) == 1
    assert measurements[0]["pressao"] == 150.0
    assert window.overview._report_ready
    window.close()
