from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from communication.protocol_parser import ProtocolError, ProtocolParser
from core.constants import ReadingQuality
from services.acquisition_service import AcquisitionService


def test_complete_json_message(config_data: dict) -> None:
    parser = ProtocolParser(config_data["sensores"], "comparar")
    raw = json.dumps({
        "timestamp_ms": 152340,
        "pressao_ma": 12.0,
        "pressao": 5.0,
        "vazao_baixa_ma": 8.0,
        "vazao_baixa": 1.25,
        "vazao_alta_ma": 10.0,
        "vazao_alta": 18.75,
        "status": "OK",
    })
    measurement = parser.parse(raw)
    assert measurement.device_timestamp_ms == 152340
    assert measurement.pressure.value == 5.0
    assert measurement.pressure.calculated_value == pytest.approx(5.0)
    assert measurement.pressure.quality == ReadingQuality.VALID


def test_reduced_message_is_accepted(config_data: dict) -> None:
    parser = ProtocolParser(config_data["sensores"])
    measurement = parser.parse('{"pressao":3.42,"vazao_baixa":0.85,"vazao_alta":12.6}')
    assert measurement.pressure.current_ma is None
    assert measurement.pressure.quality == ReadingQuality.VALID
    assert measurement.low_flow.value == pytest.approx(0.85)


@pytest.mark.parametrize("raw", [
    '{"pressao":',
    "[]",
    '{"status":"OK"}',
    '{"pressao":"não-numérico"}',
])
def test_invalid_or_incomplete_message(raw: str, config_data: dict) -> None:
    with pytest.raises(ProtocolError):
        ProtocolParser(config_data["sensores"]).parse(raw)


def test_software_conversion_mode(config_data: dict) -> None:
    parser = ProtocolParser(config_data["sensores"], "software")
    measurement = parser.parse('{"pressao_ma":12,"pressao":99}')
    assert measurement.pressure.value == pytest.approx(5)


def test_acquisition_recovers_after_communication_loss(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    timeouts: list[str] = []
    service.timeout_detected.connect(timeouts.append)
    service.process_real('{"pressao":1}')
    service.last_message_at = datetime.now() - timedelta(seconds=4)
    service._check_timeout()
    assert service._timeout_announced
    assert timeouts
    service.process_real('{"pressao":2}')
    assert not service._timeout_announced
    assert service.valid_messages == 2
