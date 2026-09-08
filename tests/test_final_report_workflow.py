from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox

from config.settings import AppPaths, ConfigManager
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
    assert all(button.isHidden() for button in window.advanced_nav_buttons)
    assert window.connection_options.isHidden()
    window.advanced_toggle.setChecked(True)
    assert all(not button.isHidden() for button in window.advanced_nav_buttons)
    window.advanced_toggle.setChecked(False)
    session = window.test_service.start(Definition(
        code="ENS-2026-0200",
        sample_name="Amostra relatório",
        test_type="Permeabilidade",
        export_directory=str(paths.exports),
    ))
    window.calculation_test_id = session.id
    window.calculations.set_session(session.definition, "active")

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
    reports = list(paths.exports.glob("ENS-2026-0200_relatorio_final*.pdf"))
    assert len(reports) == 1
    assert reports[0].stat().st_size > 500
    assert window.overview._report_ready
    window.close()
