from __future__ import annotations

import sqlite3
from datetime import datetime

from config.settings import AppPaths, ConfigManager
from core.constants import ReadingQuality
from core.models import Measurement, SensorReading, TestDefinition as Definition
from database.database import Database
from database.repositories import EventRepository, TestRepository as Repository
from services.test_service import TestService as Service


def test_invalid_values_do_not_update_maxima(tmp_path) -> None:
    db = Database(tmp_path / "max.db"); db.initialize(); repo = Repository(db)
    session = repo.create(Definition("ENS-1", "A"))
    repo.save_measurement(session.id, Measurement(datetime.now(), pressure=SensorReading(value=999, quality=ReadingQuality.INVALID), flow=SensorReading(value=999, quality=ReadingQuality.INVALID)))
    row = repo.get(session.id)
    assert row["pressao_maxima"] is None and row["vazao_maxima"] is None


def test_pause_is_excluded_from_duration(tmp_path) -> None:
    db = Database(tmp_path / "pause.db"); db.initialize(); service = Service(Repository(db), EventRepository(db))
    session = service.start(Definition("ENS-2", "A")); session.started_at = datetime.now()
    service.toggle_pause(); service._paused_at = datetime.now()
    assert service.elapsed_seconds() < 0.1


def test_wal_backup_and_integrity(tmp_path) -> None:
    paths = AppPaths(tmp_path, tmp_path / "data", tmp_path / "logs", tmp_path / "exports", tmp_path / "config")
    for folder in (paths.data, paths.logs, paths.exports, paths.config): folder.mkdir()
    manager = ConfigManager(paths); db = Database(manager.database_path); db.initialize()
    backup = manager.backup_database()
    assert backup is not None
    with sqlite3.connect(backup) as con: assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_old_database_migrates_without_losing_flow(tmp_path) -> None:
    path = tmp_path / "old.db"
    db = Database(path); db.initialize()
    with db.transaction() as con:
        con.execute("INSERT INTO ensaios(codigo,amostra_nome,operador,inicio,status) VALUES('OLD','A','O','2026-01-01','finalizado')")
        con.execute("INSERT INTO medicoes(ensaio_id,timestamp_computador,vazao_baixa,qualidade) VALUES(1,'2026-01-01',1.25,'válida')")
    db.initialize()
    assert Repository(db).measurements(1)[0]["vazao"] == 1.25
