from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median, pstdev
from typing import Iterable


def current_to_engineering(
    current_ma: float,
    lower: float,
    upper: float,
    current_min: float = 4.0,
    current_max: float = 20.0,
) -> float:
    if current_max == current_min:
        raise ValueError("A faixa de corrente não pode ter amplitude zero")
    return lower + ((current_ma - current_min) / (current_max - current_min)) * (
        upper - lower
    )


def apply_gain_offset(value: float, gain: float = 1.0, offset: float = 0.0) -> float:
    return value * gain + offset


def range_percent(value: float | None, lower: float, upper: float) -> float | None:
    if value is None or upper == lower:
        return None
    return max(0.0, min(100.0, (value - lower) * 100.0 / (upper - lower)))


@dataclass(frozen=True)
class Statistics:
    current: float | None = None
    average: float | None = None
    median: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    amplitude: float | None = None
    standard_deviation: float | None = None
    valid_count: int = 0
    invalid_count: int = 0
    rate_of_change: float | None = None
    last_valid: float | None = None


def calculate_statistics(
    values: Iterable[float | None], invalid_count: int = 0, elapsed_seconds: float | None = None
) -> Statistics:
    valid = [float(value) for value in values if value is not None]
    if not valid:
        return Statistics(invalid_count=invalid_count)
    rate = None
    if elapsed_seconds and elapsed_seconds > 0 and len(valid) > 1:
        rate = (valid[-1] - valid[0]) / elapsed_seconds
    return Statistics(
        current=valid[-1],
        average=mean(valid),
        median=median(valid),
        minimum=min(valid),
        maximum=max(valid),
        amplitude=max(valid) - min(valid),
        standard_deviation=pstdev(valid) if len(valid) > 1 else 0.0,
        valid_count=len(valid),
        invalid_count=invalid_count,
        rate_of_change=rate,
        last_valid=valid[-1],
    )
