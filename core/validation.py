from __future__ import annotations

import math
from typing import Any

from core.constants import ReadingQuality


def optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Valor booleano não é uma leitura")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Leitura não finita")
    return number


def classify_current(current_ma: float | None, simulated: bool = False) -> ReadingQuality:
    if current_ma is None:
        return ReadingQuality.MISSING
    if current_ma < 3.6 or current_ma > 20.5:
        return ReadingQuality.INVALID
    if current_ma < 4.0 or current_ma > 20.0:
        return ReadingQuality.WARNING
    return ReadingQuality.SIMULATED if simulated else ReadingQuality.VALID


def classify_value(
    value: float | None, lower: float, upper: float, base: ReadingQuality
) -> ReadingQuality:
    if value is None:
        return ReadingQuality.MISSING
    if value < lower or value > upper:
        return ReadingQuality.INVALID
    return base
