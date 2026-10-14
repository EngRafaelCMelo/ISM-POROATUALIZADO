"""Funções puras para o protocolo Modbus RTU do flowmeter validado."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.units import FLOW_PROTOCOL_UNIT

FLOW_SLAVE_ID = 1
FLOW_FUNCTION = 3
FLOW_REGISTER = 0x003A
FLOW_REGISTER_COUNT = 2
FLOW_BYTE_COUNT = 4
FLOW_RESPONSE_SIZE = 9
FLOW_SCALE = 1000.0


class ModbusErrorCode(StrEnum):
    TIMEOUT = "timeout"
    CRC_INVALID = "crc_invalido"
    SHORT_RESPONSE = "resposta_curta"
    SLAVE_MISMATCH = "slave_incorreto"
    FUNCTION_MISMATCH = "funcao_incorreta"
    BYTE_COUNT_INVALID = "byte_count_invalido"
    SIZE_INVALID = "tamanho_invalido"
    EXCEPTION = "excecao_modbus"
    PORT_DISCONNECTED = "porta_desconectada"
    PORT_BUSY = "porta_ocupada"


class ModbusFrameError(ValueError):
    def __init__(self, code: ModbusErrorCode, message: str, exception_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.exception_code = exception_code


@dataclass(frozen=True, slots=True)
class FlowFrame:
    raw_uint32: int
    value: float
    unit: str = FLOW_PROTOCOL_UNIT

    @property
    def flow_l_min(self) -> float:
        """Legacy API alias; callers must use ``unit`` to interpret the value."""
        return self.value


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def append_crc(payload: bytes) -> bytes:
    checksum = crc16(payload)
    return payload + bytes((checksum & 0xFF, checksum >> 8))


def build_read_request() -> bytes:
    payload = bytes(
        (
            FLOW_SLAVE_ID,
            FLOW_FUNCTION,
            FLOW_REGISTER >> 8,
            FLOW_REGISTER & 0xFF,
            0,
            FLOW_REGISTER_COUNT,
        )
    )
    return append_crc(payload)


def expected_response_size(prefix: bytes) -> int | None:
    """Retorna o tamanho completo assim que o cabeçalho permitir determiná-lo."""
    if len(prefix) < 2:
        return None
    if prefix[1] & 0x80:
        return 5
    if len(prefix) < 3:
        return None
    return 3 + prefix[2] + 2


def parse_flow_response(response: bytes, unit: str = FLOW_PROTOCOL_UNIT) -> FlowFrame:
    if not response:
        raise ModbusFrameError(ModbusErrorCode.TIMEOUT, "Flowmeter não respondeu no prazo")
    if len(response) < 5:
        raise ModbusFrameError(
            ModbusErrorCode.SHORT_RESPONSE,
            f"Resposta Modbus curta: {len(response)} byte(s)",
        )
    target_size = expected_response_size(response)
    if target_size is not None and len(response) < target_size:
        raise ModbusFrameError(
            ModbusErrorCode.SHORT_RESPONSE,
            f"Resposta Modbus parcial: {len(response)} de {target_size} bytes",
        )
    if target_size is not None and len(response) > target_size:
        raise ModbusFrameError(
            ModbusErrorCode.SIZE_INVALID,
            f"Resposta Modbus com {len(response)} bytes, esperados {target_size}",
        )
    received_crc = response[-2] | (response[-1] << 8)
    if received_crc != crc16(response[:-2]):
        raise ModbusFrameError(ModbusErrorCode.CRC_INVALID, "CRC da resposta Modbus é inválido")
    if response[0] != FLOW_SLAVE_ID:
        raise ModbusFrameError(
            ModbusErrorCode.SLAVE_MISMATCH,
            f"Resposta recebida do slave {response[0]}, esperado {FLOW_SLAVE_ID}",
        )
    if response[1] == (FLOW_FUNCTION | 0x80):
        code = response[2]
        raise ModbusFrameError(
            ModbusErrorCode.EXCEPTION,
            f"Flowmeter retornou exceção Modbus 0x{code:02X}",
            code,
        )
    if response[1] != FLOW_FUNCTION:
        raise ModbusFrameError(
            ModbusErrorCode.FUNCTION_MISMATCH,
            f"Função Modbus 0x{response[1]:02X}, esperada 0x{FLOW_FUNCTION:02X}",
        )
    if response[2] != FLOW_BYTE_COUNT:
        raise ModbusFrameError(
            ModbusErrorCode.BYTE_COUNT_INVALID,
            f"Byte count {response[2]}, esperado {FLOW_BYTE_COUNT}",
        )
    if len(response) != FLOW_RESPONSE_SIZE:
        raise ModbusFrameError(
            ModbusErrorCode.SIZE_INVALID,
            f"Resposta Modbus com {len(response)} bytes, esperados {FLOW_RESPONSE_SIZE}",
        )
    raw = int.from_bytes(response[3:7], byteorder="big", signed=False)
    return FlowFrame(raw_uint32=raw, value=raw / FLOW_SCALE, unit=unit)
