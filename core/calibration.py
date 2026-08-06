from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev


@dataclass(frozen=True)
class CalibrationResult:
    gain: float
    offset: float
    error_rmse: float
    stable: bool
    average_current: float
    standard_deviation: float
    minimum: float
    maximum: float


def sample_stability(currents: list[float], max_stddev: float = 0.05) -> dict[str, float | bool]:
    if not currents:
        raise ValueError("Nenhuma amostra de calibração")
    deviation = pstdev(currents) if len(currents) > 1 else 0.0
    return {
        "mean": mean(currents),
        "stddev": deviation,
        "min": min(currents),
        "max": max(currents),
        "stable": deviation <= max_stddev,
    }


def fit_calibration(points: list[tuple[float, float]], stability: list[float] | None = None) -> CalibrationResult:
    if len(points) < 2:
        raise ValueError("São necessários pelo menos dois pontos")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_mean, y_mean = mean(xs), mean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        raise ValueError("Os pontos de corrente precisam ser distintos")
    gain = sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
    offset = y_mean - gain * x_mean
    rmse = (sum((gain * x + offset - y) ** 2 for x, y in points) / len(points)) ** 0.5
    if stability:
        status = sample_stability(stability)
    else:
        status = {
            "mean": mean(xs),
            "stddev": 0.0,
            "min": min(xs),
            "max": max(xs),
            "stable": True,
        }
    return CalibrationResult(
        gain=gain,
        offset=offset,
        error_rmse=rmse,
        stable=bool(status["stable"]),
        average_current=float(status["mean"]),
        standard_deviation=float(status["stddev"]),
        minimum=float(status["min"]),
        maximum=float(status["max"]),
    )
