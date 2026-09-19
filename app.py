"""Ponto de entrada do Supervisório ISM – Permeabilímetro."""

from __future__ import annotations

import ctypes
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from config.settings import AppPaths, ConfigManager
from core.constants import ReadingQuality
from core.models import Measurement, SensorReading, TestDefinition
from core.version import APP_NAME, APP_VERSION
from database.database import Database
from database.repositories import EventRepository, TestRepository
from services.export_service import ExportService
from ui.main_window import MainWindow
from ui.resources import branding_path


def report_smoke(directory: Path) -> Path:
    """Exercita a exportação no executável sem acessar dados reais do operador."""
    with TemporaryDirectory(prefix="ism-report-smoke-") as temporary:
        database = Database(Path(temporary) / "smoke.db")
        database.initialize()
        tests = TestRepository(database)
        events = EventRepository(database)
        session = tests.create(
            TestDefinition(
                code="ENS-PACOTE-SIMULADO",
                sample_name="Amostra de validação",
                operator="Teste de empacotamento",
                simulated=True,
            )
        )
        now = datetime.now()
        for index in range(3):
            timestamp = now + timedelta(seconds=index)
            tests.save_measurement(
                session.id,
                Measurement(
                    received_at=timestamp,
                    pressure=SensorReading(
                        value=100.0 + index,
                        quality=ReadingQuality.SIMULATED,
                        device_status="OK",
                        timestamp=timestamp,
                    ),
                    flow=SensorReading(
                        value=10.0 + index,
                        quality=ReadingQuality.SIMULATED,
                        device_status="OK",
                        timestamp=timestamp + timedelta(milliseconds=100),
                    ),
                    communication_state="OK",
                    simulated=True,
                    schema_version=1,
                ),
            )
        tests.finish(session.id, "Validação de á é í ó ú ç ° ² Δ ∞ × R²")
        return ExportService(tests, events).export_pdf(session.id, directory)


def configure_logging(paths: AppPaths) -> None:
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(
        paths.logs / "supervisor.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[handler, logging.StreamHandler()],
    )


def main() -> int:
    paths = AppPaths.create()
    configure_logging(paths)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ISM")
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar)
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"ISM.Permeabilimetro.Supervisor.{APP_VERSION}"
            )
        except (AttributeError, OSError):
            logging.warning("Não foi possível definir AppUserModelID")
    app_icon = QIcon(str(branding_path("ism_app_icon.ico")))
    app.setWindowIcon(app_icon)
    splash_pixmap = QPixmap(str(branding_path("ism_logo_horizontal.png"))).scaled(
        620, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    splash = QSplashScreen(splash_pixmap)
    splash.setWindowIcon(app_icon)
    splash.showMessage(
        f"{APP_NAME} · inicializando…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        Qt.GlobalColor.darkBlue,
    )
    splash.show()
    app.processEvents()

    try:
        config = ConfigManager(paths)
        migrated = config.migrate_legacy_database()
        if migrated:
            logging.info("Banco legado migrado com cópia preservada: %s", migrated)
        if config.get("dados.backup_automatico", True):
            try:
                config.backup_database()
            except OSError:
                logging.exception("Não foi possível criar o backup antes da migração")
        database = Database(config.database_path)
        database.initialize()
        window = MainWindow(config, database, paths)
        window.setWindowIcon(app_icon)
        window.show()
        splash.finish(window)
        if config.warnings:
            QMessageBox.warning(
                window, "Configuração local recuperada", "\n\n".join(config.warnings)
            )
        return app.exec()
    except Exception as exc:  # proteção da borda da aplicação
        logging.exception("Falha fatal ao iniciar a aplicação")
        QMessageBox.critical(
            None,
            "Não foi possível iniciar",
            f"O Supervisório ISM – Permeabilímetro não pôde ser iniciado.\n\n{exc}\n\n"
            f"Consulte os logs em:\n{paths.logs}",
        )
        return 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--report-smoke":
        report_smoke(Path(sys.argv[2]))
    else:
        raise SystemExit(main())
