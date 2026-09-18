from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from communication.protocol_parser import ProtocolError, ProtocolParser
from communication.serial_manager import FlowReading
from core.constants import ReadingQuality
from services.acquisition_service import AcquisitionService


def payload(**changes) -> dict:
    message = {
        "schema_version": 1,
        "timestamp_ms": 152340,
        "sequence": 42,
        "firmware_version": "2.2.0",
        "pressao_raw": 12345,
        "pressao_ma": 12.0,
        "pressao": (12.0 - 3.95) / (20.0 - 3.95) * 400.0,
        "pressao_unidade": "psi",
        "pressao_valida": True,
        "pressao_status": "OK",
        "status": "OK",
    }
    message.update(changes)
    return message


def test_flat_pressure_contract(config_data: dict) -> None:
    measurement = ProtocolParser(config_data["sensores"], "comparar").parse(json.dumps(payload()))
    assert measurement.device_timestamp_ms == 152340
    assert measurement.sequence == 42
    assert measurement.schema_version == 1
    assert measurement.firmware_version == "2.2.0"
    assert measurement.pressure.value == pytest.approx((12.0 - 3.95) / (20.0 - 3.95) * 400.0)
    assert measurement.pressure.raw_value == 12345
    assert measurement.pressure.unit == "psi"
    assert measurement.pressure.quality == ReadingQuality.VALID
    assert measurement.flow.value is None


@pytest.mark.parametrize(
    "raw",
    [
        '{"pressao":',
        "[]",
        json.dumps({"status": "OK"}),
        json.dumps(payload(pressao="não-numérico")),
        json.dumps(payload(schema_version=99)),
        json.dumps(payload(pressao_valida="sim")),
    ],
)
def test_invalid_partial_or_missing_json(raw: str, config_data: dict) -> None:
    with pytest.raises(ProtocolError):
        ProtocolParser(config_data["sensores"]).parse(raw)


def test_declared_invalid_pressure_is_not_accepted(config_data: dict) -> None:
    measurement = ProtocolParser(config_data["sensores"]).parse(
        json.dumps(
            payload(pressao=None, pressao_valida=False, pressao_status="ADS1115_UNAVAILABLE")
        )
    )
    assert measurement.pressure.value is None
    assert not measurement.pressure.valid
    assert measurement.pressure.quality == ReadingQuality.INVALID


def test_software_conversion_mode(config_data: dict) -> None:
    measurement = ProtocolParser(config_data["sensores"], "software").parse(
        json.dumps(payload(pressao_ma=12, pressao=99))
    )
    assert measurement.pressure.value == pytest.approx((12.0 - 3.95) / (20.0 - 3.95) * 400.0)


def test_compare_mode_warns_when_values_disagree(config_data: dict) -> None:
    measurement = ProtocolParser(config_data["sensores"], "comparar").parse(
        json.dumps(payload(pressao_ma=12, pressao=60))
    )
    assert measurement.pressure.quality == ReadingQuality.WARNING


def test_flow_event_does_not_change_pressure_timestamp(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    service.process_real(json.dumps(payload()))
    pressure_timestamp = service.latest_pressure.timestamp
    flow_timestamp = datetime.now() + timedelta(seconds=1)
    service.process_flow(FlowReading(0.240, 240, flow_timestamp))
    combined = service.emit_combined_measurement()
    assert combined is not None
    assert combined.pressure.timestamp == pressure_timestamp
    assert combined.flow.timestamp == flow_timestamp
    service.stop()


def test_pressure_event_does_not_change_flow_timestamp(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    flow_timestamp = datetime.now() - timedelta(milliseconds=200)
    service.process_flow(FlowReading(0.240, 240, flow_timestamp))
    service.process_real(json.dumps(payload(sequence=43)))
    combined = service.emit_combined_measurement()
    assert combined is not None
    assert combined.flow.timestamp == flow_timestamp
    service.stop()


def test_combined_measurement_rejects_timestamps_outside_sync_window(
    config_data: dict,
) -> None:
    service = AcquisitionService(config_data)
    service.process_real(json.dumps(payload()))
    service.process_flow(FlowReading(0.240, 240, datetime.now() + timedelta(seconds=2)))
    combined = service.emit_combined_measurement()
    assert combined is not None
    assert combined.pressure.valid and combined.flow.valid
    assert combined.communication_state == "UNSYNCHRONIZED"
    service.stop()


def test_flow_is_not_rejected_by_a_presumed_maximum(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    service.process_flow(FlowReading(1250.0, 1_250_000, datetime.now()))
    assert service.latest_flow.valid
    assert service.latest_flow.value == 1250.0
    service.stop()


def test_stale_pressure_is_not_valid(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    service.process_real(json.dumps(payload()))
    service.latest_pressure.timestamp = datetime.now() - timedelta(seconds=10)
    service.process_flow(FlowReading(0.240, 240, datetime.now()))
    combined = service.emit_combined_measurement()
    assert combined is not None
    assert combined.pressure.quality == ReadingQuality.STALE
    assert not combined.pressure.valid
    service.stop()


def test_acquisition_recovers_after_communication_loss(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    timeouts: list[str] = []
    service.timeout_detected.connect(timeouts.append)
    service.process_real(json.dumps(payload()))
    service.last_message_at = datetime.now() - timedelta(seconds=4)
    service._check_timeout()
    assert service._timeout_announced and timeouts
    service.process_real(json.dumps(payload(sequence=43)))
    assert not service._timeout_announced
    assert service.valid_messages == 2
    service.stop()


def test_flow_protocol_error_preserves_timestamp_but_invalidates_reading(
    config_data: dict,
) -> None:
    service = AcquisitionService(config_data)
    timestamp = datetime.now()
    service.process_flow(FlowReading(0.240, 240, timestamp))
    service.process_flow_error("crc_invalido: CRC inválido")
    assert service.latest_flow.timestamp == timestamp
    assert service.latest_flow.value == pytest.approx(0.240)
    assert service.latest_flow.quality == ReadingQuality.INVALID
    assert service.latest_flow.device_status == "CRC_INVALIDO"
    service.stop()


def test_flow_disconnect_and_automatic_stale_are_distinct(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    service.process_flow(FlowReading(0.240, 240, datetime.now() - timedelta(seconds=10)))
    service._check_timeout()
    assert service.latest_flow.quality == ReadingQuality.STALE

    service.process_flow_error("porta_desconectada: cabo removido")
    assert service.latest_flow.quality == ReadingQuality.DISCONNECTED
    service.stop()


def test_esp32_disconnect_invalidates_pressure_immediately(config_data: dict) -> None:
    service = AcquisitionService(config_data)
    service.process_real(json.dumps(payload()))
    timestamp = service.latest_pressure.timestamp
    service.process_pressure_connection(False, "cabo removido")
    assert service.latest_pressure.timestamp == timestamp
    assert service.latest_pressure.quality == ReadingQuality.DISCONNECTED
    service.stop()
