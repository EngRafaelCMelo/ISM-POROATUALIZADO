from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from communication.protocol_parser import ProtocolError, ProtocolParser
from core.constants import ReadingQuality
from services.acquisition_service import AcquisitionService


def message(**changes) -> str:
    payload = {
        "schema_version": 1, "sequence": 152, "uptime_ms": 152000,
        "pressao": {"ads_raw": 12000, "voltage_v": 1.502, "current_ma": 10.033, "value": 3.77, "unit": "bar", "valid": True},
        "vazao": {"raw_register": 1326, "value": 132.6, "unit": "L/min", "valid": True},
        "status": "OK", "alarms": [], "firmware_version": "2.0.0",
    }
    payload.update(changes)
    return json.dumps(payload)


def test_new_versioned_protocol(config_data: dict) -> None:
    measurement = ProtocolParser(config_data["sensores"]).parse(message())
    assert measurement.sequence == 152
    assert measurement.pressure.value == pytest.approx(3.77)
    assert measurement.flow.value == pytest.approx(132.6)
    assert measurement.pressure.quality == ReadingQuality.VALID


def test_legacy_protocol_is_adapted_to_one_flow_meter(config_data: dict) -> None:
    measurement = ProtocolParser(config_data["sensores"]).parse(
        '{"timestamp_ms":10,"pressao":3.42,"vazao_baixa":0.85,"vazao_alta":12.6,"status":"OK"}'
    )
    assert measurement.flow.value == pytest.approx(0.85)
    assert measurement.firmware_version == "legado"


@pytest.mark.parametrize("raw", ['{"pressao":', "[]", '{"status":"OK"}', '{"schema_version":1,"pressao":{},"vazao":[])'])
def test_invalid_or_incomplete_message(raw: str, config_data: dict) -> None:
    with pytest.raises(ProtocolError):
        ProtocolParser(config_data["sensores"]).parse(raw)


def test_missing_sensor_and_error_status_are_not_valid(config_data: dict) -> None:
    parser = ProtocolParser(config_data["sensores"])
    missing = parser.parse(message(vazao={"value": None, "unit": "L/min", "valid": False}))
    assert missing.flow.quality == ReadingQuality.MISSING
    failed = parser.parse(message(status="ERROR", alarms=["MODBUS_TIMEOUT"]))
    assert not failed.pressure.valid and not failed.flow.valid


def test_timeout_before_first_message_and_recovery(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    timeouts: list[str] = []
    service.timeout_detected.connect(timeouts.append)
    service.monitoring_started_at = datetime.now() - timedelta(seconds=4)
    service._check_timeout()
    assert timeouts
    service.process_real(message())
    assert not service._timeout_announced


def test_lost_and_repeated_sequences(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    service.process_real(message(sequence=10))
    service.process_real(message(sequence=12))
    service.process_real(message(sequence=12))
    assert service.lost_sequences == 1
    assert service.repeated_sequences == 1
