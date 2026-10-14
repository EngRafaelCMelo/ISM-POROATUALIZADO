from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from config.settings import AppPaths, ConfigManager
from core.constants import ReadingQuality, Severity
from core.constants import TestStatus as Status
from core.models import Alarm, Measurement, SensorReading
from core.models import TestDefinition as Definition
from core.models import TestSession as Session
from database.database import Database
from database.repositories import EventRepository
from database.repositories import TestRepository as Repository
from services.alarm_service import AlarmSoundController
from services.preflight_service import run_preflight
from services.test_service import TestService as Service


def paths_for(tmp_path):
    paths = AppPaths(
        tmp_path, tmp_path / "data", tmp_path / "logs", tmp_path / "exports", tmp_path / "config"
    )
    for folder in (paths.data, paths.logs, paths.exports, paths.config):
        folder.mkdir(parents=True, exist_ok=True)
    return paths


def test_interrupted_test_requires_recovery_or_explicit_end(tmp_path) -> None:
    database = Database(tmp_path / "recovery.db")
    database.initialize()
    tests = Repository(database)
    events = EventRepository(database)
    session = tests.create(Definition("ENS-RECOVERY", "Amostra"))
    tests.mark_interrupted(session.id)

    interrupted = tests.get(session.id)
    assert interrupted["status"] == Status.INTERRUPTED.value
    assert any(row["categoria"] == "interrupção" for row in events.events(session.id))

    recovered = Session(
        session.id,
        session.definition,
        Status.INTERRUPTED,
        session.started_at,
    )
    service = Service(tests, events)
    service.recover(recovered)
    assert tests.get(session.id)["status"] == Status.RUNNING.value
    assert any(row["categoria"] == "recuperação" for row in events.events(session.id))

    service.finish("finalizado após recuperação")
    assert tests.get(session.id)["status"] == Status.FINISHED.value


def test_backup_restore_validates_file_and_keeps_safety_copy(tmp_path) -> None:
    paths = paths_for(tmp_path)
    manager = ConfigManager(paths)
    database = Database(manager.database_path)
    database.initialize()
    backup = manager.backup_database(tmp_path / "selected")
    assert backup is not None
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO ensaios(codigo,amostra_nome,operador,inicio,status) VALUES(?,?,?,?,?)",
            ("CURRENT", "A", "Operador", datetime.now().isoformat(), Status.FINISHED.value),
        )
    database.close()
    safety = manager.restore_database(backup)
    assert safety is not None and safety.exists()
    with sqlite3.connect(manager.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ensaios").fetchone()[0] == 0

    invalid = tmp_path / "invalid.db"
    invalid.write_text("not sqlite", encoding="utf-8")
    with pytest.raises(ValueError):
        manager.restore_database(invalid)


def test_alarm_sound_is_critical_only_and_has_cooldown() -> None:
    controller = AlarmSoundController(enabled=True, cooldown_s=10)
    timestamp = datetime.now()
    warning = Alarm(timestamp, "Pressão", Severity.WARNING, "processo", "atenção")
    critical = Alarm(timestamp, "Pressão", Severity.CRITICAL, "processo", "crítico")
    assert not controller.should_sound(warning)
    assert controller.should_sound(critical)
    assert not controller.should_sound(
        Alarm(timestamp + timedelta(seconds=5), "Pressão", Severity.CRITICAL, "processo", "crítico")
    )
    assert controller.should_sound(
        Alarm(
            timestamp + timedelta(seconds=11),
            "Pressão",
            Severity.CRITICAL,
            "processo",
            "crítico",
        )
    )


def test_preflight_reports_the_required_production_checklist(config_data) -> None:
    now = datetime.now()
    measurement = Measurement(
        now,
        pressure=SensorReading(10.0, quality=ReadingQuality.VALID, timestamp=now),
        flow=SensorReading(2.0, quality=ReadingQuality.VALID, timestamp=now),
    )
    result = run_preflight(
        config_data,
        measurement,
        esp32_connected=True,
        flowmeter_connected=True,
        database_writable=True,
        communication_stable=False,
        sample_selected=False,
        required_parameters_filled=False,
        confinement_pressure_setpoint=2000.0,
        blanket_temperature_setpoint=-10.0,
        report_path_available=False,
    )
    assert not result.ok
    names = {check.name for check in result.checks if not check.ok}
    assert {
        "Comunicação estável",
        "Amostra selecionada",
        "Parâmetros obrigatórios preenchidos",
        "Pressão de confinamento válida",
        "Temperatura da manta válida",
        "Caminho do relatório disponível",
    } <= names
