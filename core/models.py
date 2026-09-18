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
    raw_value: int | float | None = None
    unit: str = ""
    timestamp: datetime | None = None

    @property
    def valid(self) -> bool:
        return self.value is not None and self.quality in (
            ReadingQuality.VALID,
            ReadingQuality.WARNING,
            ReadingQuality.SIMULATED,
        )

    def age_seconds(self, now: datetime | None = None) -> float | None:
        if self.timestamp is None:
            return None
        return max(0.0, ((now or datetime.now()) - self.timestamp).total_seconds())


@dataclass(slots=True)
class Measurement:
    received_at: datetime
    device_timestamp_ms: int | None = None
    pressure: SensorReading = field(default_factory=SensorReading)
    flow: SensorReading = field(default_factory=SensorReading)
    flowmeter_ok: bool | None = None
    communication_state: str = "conectado"
    raw_message: str = ""
    simulated: bool = False
    recordable: bool = True
    sequence: int | None = None
    schema_version: int | None = None
    firmware_version: str = ""

    def to_db_tuple(self, test_id: int) -> tuple[Any, ...]:
        qualities = {
            self.pressure.quality.value,
            self.flow.quality.value,
        }
        overall = (
            ReadingQuality.DISCONNECTED.value
            if ReadingQuality.DISCONNECTED.value in qualities
            else ReadingQuality.STALE.value
            if ReadingQuality.STALE.value in qualities
            else ReadingQuality.INVALID.value
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
            self.pressure.raw_value,
            self.pressure.unit,
            int(self.pressure.valid),
            self.pressure.timestamp.isoformat(timespec="milliseconds")
            if self.pressure.timestamp
            else None,
            self.pressure.device_status,
            self.flow.raw_value,
            self.flow.value,
            self.flow.unit,
            int(self.flow.valid),
            self.flow.timestamp.isoformat(timespec="milliseconds") if self.flow.timestamp else None,
            self.flow.device_status,
            self.sequence,
            self.schema_version,
            self.firmware_version,
            int(self.simulated),
            overall,
            self.communication_state,
            self.raw_message,
        )


@dataclass(frozen=True, slots=True)
class MeasurementSnapshot:
    """Cópia imutável da medição combinada usada por um cálculo."""

    captured_at: datetime
    received_at: datetime
    pressure_value: float
    flow_value: float
    pressure_timestamp: datetime
    flow_timestamp: datetime
    pressure_status: str
    flow_status: str
    pressure_quality: str
    flow_quality: str
    pressure_valid: bool
    flow_valid: bool
    pressure_raw: int | float | None
    flow_raw: int | float | None
    pressure_current_ma: float | None
    device_timestamp_ms: int | None
    sequence: int | None
    schema_version: int | None
    firmware_version: str
    communication_state: str
    delta_seconds: float
    simulated: bool
    origin: str = "leitura_combinada"

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("captured_at", "received_at", "pressure_timestamp", "flow_timestamp"):
            result[key] = result[key].isoformat()
        return result


@dataclass(slots=True)
class TestDefinition:
    code: str
    sample_name: str
    sample_identification: str = ""
    operator: str = "Operador"
    description: str = ""
    test_type: str = "Permeabilidade"
    notes: str = ""
    expected_pressure_range: str = ""
    pressure_unit: str = "psi"
    flow_unit: str = "NL/min"
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
    configuration_snapshot: str = ""
    firmware_version: str = ""
    simulated: bool = False


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
