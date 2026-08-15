from __future__ import annotations

from enum import StrEnum


class ReadingQuality(StrEnum):
    VALID = "válida"
    WARNING = "atenção"
    INVALID = "inválida"
    MISSING = "ausente"
    SIMULATED = "simulada"


class Severity(StrEnum):
    INFO = "informação"
    WARNING = "atenção"
    ALARM = "alarme"
    CRITICAL = "crítico"


class TestStatus(StrEnum):
    RUNNING = "em_andamento"
    PAUSED = "pausado"
    FINISHED = "finalizado"
    INTERRUPTED = "interrompido"
    INVALID = "inválido"


SENSOR_KEYS = ("pressao", "vazao")
SERIAL_SCHEMA_VERSION = 1
