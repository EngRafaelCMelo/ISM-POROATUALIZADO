"""Ponto de entrada do Supervisor de Porosímetro."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from config.settings import AppPaths, ConfigManager
from database.database import Database
from ui.main_window import MainWindow


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
    app.setApplicationName("Supervisor de Porosímetro")
    app.setOrganizationName("ISM")
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar)

    try:
        config = ConfigManager(paths)
        if config.get("dados.backup_automatico", True):
            try:
                config.backup_database()
            except OSError:
                logging.exception("Não foi possível criar o backup antes da migração")
        database = Database(config.database_path)
        database.initialize()
        window = MainWindow(config, database, paths)
        window.show()
        return app.exec()
    except Exception as exc:  # proteção da borda da aplicação
        logging.exception("Falha fatal ao iniciar a aplicação")
        QMessageBox.critical(
            None,
            "Não foi possível iniciar",
            f"O Supervisor de Porosímetro não pôde ser iniciado.\n\n{exc}\n\n"
            f"Consulte os logs em:\n{paths.logs}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
