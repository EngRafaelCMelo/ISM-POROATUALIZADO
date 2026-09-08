from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from core.constants import ReadingQuality, Severity, TestStatus


@dataclass(slots=True)
class SensorReading:
    value: float | None = None
    current_ma: float | None = None
    quality: ReadingQuality = ReadingQuality.MISSING
    device_value: float | None = None
    calculated_value: float | None = None
    device_status: str = ""


@dataclass(slots=True)
class Measurement:
    received_at: datetime
    device_timestamp_ms: int | None = None
    pressure: SensorReading = field(default_factory=SensorReading)
    flow: SensorReading = field(default_factory=SensorReading)
    communication_state: str = "conectado"
    raw_message: str = ""
    simulated: bool = False

    def to_db_tuple(self, test_id: int) -> tuple[Any, ...]:
        qualities = {
            self.pressure.quality.value,
            self.flow.quality.value,
        }
        overall = (
            ReadingQuality.INVALID.value
            if ReadingQuality.INVALID.value in qualities
            else ReadingQuality.WARNING.value
            if ReadingQuality.WARNING.value in qualities
            else ReadingQuality.MISSING.value
            if ReadingQuality.MISSING.value in qualities
            else ReadingQuality.SIMULATED.value
            if self.simulated
            else ReadingQuality.VALID.value
        )
        return (
            test_id,
            self.received_at.isoformat(timespec="milliseconds"),
            self.device_timestamp_ms,
            self.pressure.current_ma,
            self.pressure.value,
            self.flow.current_ma,
            self.flow.value,
            None,  # coluna legada vazao_alta_ma
            None,  # coluna legada vazao_alta
            "unica",  # coluna legada flow_meter_ativo
            overall,
            self.communication_state,
            self.raw_message,
        )


@dataclass(slots=True)
class TestDefinition:
    code: str
    sample_name: str
    sample_identification: str = ""
    operator: str = "Operador"
    description: str = ""
    test_type: str = "Porosimetria"
    notes: str = ""
    expected_pressure_range: str = ""
    pressure_unit: str = "bar"
    flow_unit: str = "L/min"
    acquisition_interval: float = 1.0
    export_directory: str = ""
    sample_length_mm: float | None = None
    sample_diameter_mm: float | None = None
    sample_mass_g: float | None = None
    bulk_volume_cm3: float | None = None
    gas_type: str = "Helio"
    temperature_c: float = 20.0
    atmospheric_pressure_kpa: float = 101.325
    pressure_reference: str = "manometrica"


@dataclass(slots=True)
class TestSession:
    id: int
    definition: TestDefinition
    status: TestStatus
    started_at: datetime
    ended_at: datetime | None = None
    paused_seconds: float = 0.0
    sample_count: int = 0


@dataclass(slots=True)
class Alarm:
    timestamp: datetime
    sensor: str
    severity: Severity
    category: str
    message: str
    measured_value: float | None = None
    limit_value: float | None = None
    acknowledged: bool = False
    operator_note: str = ""

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        result["severity"] = self.severity.value
        return result
