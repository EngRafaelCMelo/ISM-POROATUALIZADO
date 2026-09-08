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
        "pressao": 50.0,
        "pressao_status": "OK",
        "vazao": 1.25,
        "vazao_status": "OK",
        "status": "OK",
    })
    measurement = parser.parse(raw)
    assert measurement.device_timestamp_ms == 152340
    assert measurement.pressure.value == 50.0
    assert measurement.pressure.calculated_value == pytest.approx(50.0)
    assert measurement.pressure.quality == ReadingQuality.VALID
    assert measurement.flow.value == pytest.approx(1.25)
    assert measurement.pressure.device_status == "OK"
    assert measurement.flow.device_status == "OK"


def test_reduced_message_is_accepted(config_data: dict) -> None:
    parser = ProtocolParser(config_data["sensores"])
    measurement = parser.parse('{"pressao":34.2,"vazao_baixa":0.85}')
    assert measurement.pressure.current_ma is None
    assert measurement.pressure.quality == ReadingQuality.VALID
    assert measurement.flow.value == pytest.approx(0.85)


def test_current_flow_names_take_precedence_over_legacy_aliases(config_data: dict) -> None:
    parser = ProtocolParser(config_data["sensores"])
    measurement = parser.parse(
        '{"vazao":1.5,"vazao_baixa":0.5,"vazao_ma":12,"vazao_baixa_ma":8}'
    )
    assert measurement.flow.value == pytest.approx(1.5)
    assert measurement.flow.current_ma == pytest.approx(12)


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
    assert measurement.pressure.value == pytest.approx(50)


def test_compare_mode_warns_when_device_and_current_disagree(config_data: dict) -> None:
    parser = ProtocolParser(config_data["sensores"], "comparar")
    measurement = parser.parse('{"pressao_ma":12,"pressao":60,"vazao":1}')
    assert measurement.pressure.value == pytest.approx(60)
    assert measurement.pressure.calculated_value == pytest.approx(50)
    assert measurement.pressure.quality == ReadingQuality.WARNING


def test_current_firmware_message_is_accepted(config_data: dict) -> None:
    parser = ProtocolParser(config_data["sensores"])
    measurement = parser.parse(
        '{"timestamp_ms":1000,"sequence":1,"pressao_ma":12.0,'
        '"pressao":50.0,"pressao_status":"OK","vazao_baixa":null,'
        '"vazao_baixa_status":"AGUARDANDO_PROTOCOLO_RS485",'
        '"status":"PARCIAL_SEM_VAZAO"}'
    )
    assert measurement.pressure.value == pytest.approx(50.0)
    assert measurement.pressure.quality == ReadingQuality.VALID
    assert measurement.flow.value is None
    assert measurement.flow.device_status == "AGUARDANDO_PROTOCOLO_RS485"
    assert measurement.communication_state == "PARCIAL_SEM_VAZAO"
    assert measurement.to_db_tuple(1)[10] == ReadingQuality.MISSING.value


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
