from __future__ import annotations

import pytest
import serial

from communication.modbus import (
    ModbusErrorCode,
    ModbusFrameError,
    append_crc,
    build_read_request,
    crc16,
    expected_response_size,
    parse_flow_response,
)
from communication.serial_manager import FlowmeterWorker


def valid_response(raw: int = 240) -> bytes:
    return append_crc(bytes((1, 3, 4)) + raw.to_bytes(4, "big"))


def test_crc_and_read_request_are_exact() -> None:
    assert build_read_request() == bytes.fromhex("01 03 00 3A 00 02 E4 06")
    assert crc16(bytes.fromhex("01 03 00 3A 00 02")) == 0x06E4


def test_valid_uint32_big_endian_is_divided_by_1000() -> None:
    parsed = parse_flow_response(valid_response(240))
    assert parsed.raw_uint32 == 240
    assert parsed.flow_l_min == pytest.approx(0.240)


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (b"", ModbusErrorCode.TIMEOUT),
        (b"\x01\x03\x04", ModbusErrorCode.SHORT_RESPONSE),
        (bytes.fromhex("01 03 04 00 00 00 F0"), ModbusErrorCode.SHORT_RESPONSE),
        (valid_response()[:-1] + b"\x00", ModbusErrorCode.CRC_INVALID),
        (append_crc(bytes.fromhex("02 03 04 00 00 00 F0")), ModbusErrorCode.SLAVE_MISMATCH),
        (append_crc(bytes.fromhex("01 04 04 00 00 00 F0")), ModbusErrorCode.FUNCTION_MISMATCH),
    ],
)
def test_invalid_responses_have_specific_error(response: bytes, code: ModbusErrorCode) -> None:
    with pytest.raises(ModbusFrameError) as error:
        parse_flow_response(response)
    assert error.value.code == code


def test_five_byte_modbus_exception_is_handled() -> None:
    response = append_crc(bytes.fromhex("01 83 02"))
    assert len(response) == 5
    assert expected_response_size(response[:2]) == 5
    with pytest.raises(ModbusFrameError) as error:
        parse_flow_response(response)
    assert error.value.code == ModbusErrorCode.EXCEPTION
    assert error.value.exception_code == 2


def test_partial_response_size_is_derived_from_byte_count() -> None:
    assert expected_response_size(bytes.fromhex("01 03")) is None
    assert expected_response_size(bytes.fromhex("01 03 04")) == 9


def worker_config() -> dict[str, object]:
    return {
        "porta": "COM_TEST",
        "slave_id": 1,
        "baud_rate": 9600,
        "funcao": 3,
        "registrador_inicial": 58,
        "quantidade_registradores": 2,
        "tipo_dado": "uint32",
        "ordem_bytes": "big",
        "fator_escala": 0.001,
        "timeout_s": 0.75,
        "intervalo_ms": 125,
        "reconexao_automatica": True,
    }


def test_worker_assembles_partial_serial_reads() -> None:
    class PartialPort:
        chunks = [bytes.fromhex("01"), bytes.fromhex("03 04"), valid_response()[3:]]

        def read(self, _size: int) -> bytes:
            return self.chunks.pop(0) if self.chunks else b""

    worker = FlowmeterWorker(worker_config())
    worker._serial = PartialPort()  # type: ignore[assignment]
    assert worker._read_frame(0.75) == valid_response()


def test_worker_counts_reconnection(monkeypatch) -> None:
    worker = FlowmeterWorker(worker_config())
    attempts = 0

    def open_port() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            worker._stop_event.set()

    def poll_once() -> None:
        raise serial.SerialException("device disconnected")

    monkeypatch.setattr(worker, "_open_port", open_port)
    monkeypatch.setattr(worker, "_close_port", lambda: None)
    monkeypatch.setattr(worker, "_poll_once", poll_once)
    worker.run()
    assert attempts == 2
    assert worker.statistics.reconnects == 1


def test_worker_counts_reconnection_after_initial_open_failure(monkeypatch) -> None:
    worker = FlowmeterWorker(worker_config())
    attempts = 0

    def open_port() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise serial.SerialException("device disconnected")
        worker._stop_event.set()

    monkeypatch.setattr(worker, "_open_port", open_port)
    monkeypatch.setattr(worker, "_close_port", lambda: None)
    worker.run()
    assert attempts == 2
    assert worker.statistics.reconnects == 1
