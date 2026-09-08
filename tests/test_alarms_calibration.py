from __future__ import annotations

from datetime import datetime

import pytest

from core.calibration import fit_calibration, sample_stability
from core.models import Measurement, SensorReading
from services.alarm_service import AlarmService


def test_alarm_current_below_36(config_data: dict) -> None:
    measurement = Measurement(
        received_at=datetime.now(),
        pressure=SensorReading(value=-0.2, current_ma=3.2),
        flow=SensorReading(value=1),
    )
    alarms = AlarmService(config_data["sensores"]).evaluate(measurement)
    assert any(a.severity.value == "crítico" and "3,6" in a.message for a in alarms)


def test_missing_flow_raises_diagnostic_alarm(config_data: dict) -> None:
    measurement = Measurement(
        received_at=datetime.now(),
        pressure=SensorReading(value=50, current_ma=12),
        flow=SensorReading(device_status="ERRO_MODBUS_0xE2"),
    )
    alarms = AlarmService(config_data["sensores"]).evaluate(measurement)
    assert any(
        alarm.sensor == "Vazão"
        and alarm.severity.value == "crítico"
        and "ERRO_MODBUS_0xE2" in alarm.message
        for alarm in alarms
    )


def test_two_point_calibration() -> None:
    result = fit_calibration([(4.0, 0.0), (20.0, 10.0)])
    assert result.gain == pytest.approx(0.625)
    assert result.offset == pytest.approx(-2.5)
    assert result.error_rmse == pytest.approx(0)


def test_unstable_samples() -> None:
    result = sample_stability([4.0, 4.4, 3.6], max_stddev=0.05)
    assert result["stable"] is False
