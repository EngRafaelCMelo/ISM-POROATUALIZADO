"""Ponto de entrada do Supervisório ISM – Permeabilímetro."""
from __future__ import annotations

import logging
import sys
import ctypes
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from config.settings import AppPaths, ConfigManager
from database.database import Database
from ui.main_window import MainWindow
from ui.resources import branding_path


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
    app.setApplicationName("Supervisório ISM – Permeabilímetro")
    app.setOrganizationName("ISM")
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar)
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ISM.Permeabilimetro.Supervisor.2.1")
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
        "Supervisório ISM – Permeabilímetro · inicializando…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        Qt.GlobalColor.darkBlue,
    )
    splash.show(); app.processEvents()

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
    raise SystemExit(main())
