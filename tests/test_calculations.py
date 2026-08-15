from __future__ import annotations

import pytest

from core.calculations import (
    apply_gain_offset,
    calculate_statistics,
    current_to_engineering,
)


def test_conversion_4_20_ma() -> None:
    assert current_to_engineering(4.0, 0, 10) == pytest.approx(0)
    assert current_to_engineering(12.0, 0, 10) == pytest.approx(5)
    assert current_to_engineering(20.0, 0, 10) == pytest.approx(10)


def test_gain_and_offset() -> None:
    assert apply_gain_offset(5.0, gain=1.1, offset=-0.2) == pytest.approx(5.3)


def test_statistics_ignore_missing() -> None:
    stats = calculate_statistics([1.0, None, 2.0, 3.0], invalid_count=1, elapsed_seconds=2)
    assert stats.average == pytest.approx(2)
    assert stats.valid_count == 3
    assert stats.invalid_count == 1
    assert stats.rate_of_change == pytest.approx(1)
