from __future__ import annotations

from datetime import datetime

from core.constants import ReadingQuality
from core.models import Measurement, SensorReading
from services.preflight_service import run_preflight


def valid_measurement() -> Measurement:
    now = datetime.now()
    return Measurement(
        now,
        pressure=SensorReading(10.0, quality=ReadingQuality.VALID, timestamp=now),
        flow=SensorReading(0.2, quality=ReadingQuality.VALID, timestamp=now),
    )


def test_preflight_accepts_ready_real_system(config_data: dict) -> None:
    config_data["comunicacao"]["porta"] = "COM3"
    config_data["flowmeter"]["porta"] = "COM4"
    result = run_preflight(
        config_data,
        valid_measurement(),
        esp32_connected=True,
        flowmeter_connected=True,
        database_writable=True,
    )
    assert result.ok


def test_real_mode_does_not_require_manual_f53_confirmation(tmp_path) -> None:
    from config.settings import AppPaths, ConfigManager

    paths = AppPaths(
        tmp_path,
        tmp_path / "data",
        tmp_path / "logs",
        tmp_path / "exports",
        tmp_path / "config",
    )
    for folder in (paths.data, paths.logs, paths.exports, paths.config):
        folder.mkdir()
    manager = ConfigManager(paths)
    manager.data["comunicacao"]["porta"] = "COM3"
    manager.data["flowmeter"]["porta"] = "COM7"
    manager.data["sensores"]["vazao"]["f53_confirmado"] = False
    assert not any("F53" in error for error in manager.real_mode_errors())


def test_preflight_blocks_same_com_and_stale_sensor(config_data: dict) -> None:
    config_data["comunicacao"]["porta"] = "COM3"
    config_data["flowmeter"]["porta"] = "com3"
    measurement = valid_measurement()
    measurement.pressure.quality = ReadingQuality.STALE
    result = run_preflight(
        config_data,
        measurement,
        esp32_connected=True,
        flowmeter_connected=True,
        database_writable=True,
    )
    assert not result.ok
    assert any("diferentes" in error for error in result.errors)
    assert any("pressão" in error.lower() for error in result.errors)


def test_preflight_blocks_active_critical_condition(config_data: dict) -> None:
    measurement = valid_measurement()
    measurement.pressure.value = config_data["sensores"]["pressao"]["critico"]
    result = run_preflight(
        config_data,
        measurement,
        esp32_connected=True,
        flowmeter_connected=True,
        database_writable=True,
    )
    assert not result.ok
    assert any("condição crítica" in error for error in result.errors)
