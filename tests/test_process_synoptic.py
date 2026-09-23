from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QSize

from core.constants import ReadingQuality
from core.models import SensorReading
from ui.resources import resource_path
from ui.widgets.process_synoptic import ProcessSynoptic


@pytest.mark.parametrize(
    ("quality", "label"),
    [
        (ReadingQuality.VALID, "OK"),
        (ReadingQuality.STALE, "STALE"),
        (ReadingQuality.INVALID, "INVALID"),
        (ReadingQuality.DISCONNECTED, "DISCONNECTED"),
        (ReadingQuality.SIMULATED, "SIMULATED"),
    ],
)
def test_synoptic_pressure_states_and_tooltip(qt_application, quality, label) -> None:
    widget = ProcessSynoptic()
    reading = SensorReading(
        value=125.4,
        current_ma=9.4,
        quality=quality,
        raw_value=12345,
        device_status=label,
        unit="psi",
        timestamp=datetime.now() - timedelta(seconds=3),
    )
    widget.update_pressure(reading)
    text = widget.instruments["pressure"].text.toPlainText()
    tooltip = widget.instruments["pressure"].toolTip()
    assert label in text
    if quality == ReadingQuality.DISCONNECTED:
        assert "125,40 psi" not in text
        assert "—" in text
    else:
        assert "125,40 psi" in text
    assert "Valor bruto: 12345" in tooltip
    assert "ESP32 / ADS1115" in tooltip


def test_synoptic_flow_animation_starts_and_stops(qt_application) -> None:
    widget = ProcessSynoptic()
    valid = SensorReading(
        value=64.051,
        quality=ReadingQuality.VALID,
        unit="L/min",
        timestamp=datetime.now(),
    )
    widget.update_flow(valid)
    assert widget.animation_running
    assert "64,051 L/min" in widget.instruments["flow"].text.toPlainText()
    assert "USB–RS485 / Modbus RTU" in widget.instruments["flow"].toolTip()
    widget.update_flow(
        SensorReading(
            value=64.051,
            quality=ReadingQuality.DISCONNECTED,
            unit="L/min",
            timestamp=valid.timestamp,
        )
    )
    assert not widget.animation_running
    text = widget.instruments["flow"].text.toPlainText()
    assert "64,051 L/min" not in text
    assert "—" in text
    assert "DISCONNECTED" in text


def test_synoptic_resize_sample_test_and_reset(qt_application) -> None:
    widget = ProcessSynoptic()
    for size in (QSize(900, 500), QSize(1200, 650), QSize(700, 390)):
        widget.resize(size)
        widget.show()
        qt_application.processEvents()
        assert widget.transform().m11() > 0
    widget.set_sample("ENS-42", "Amostra de arenito")
    widget.set_test_state("PAUSADO")
    widget.set_runtime("00:12:34", 321)
    assert "ENS-42" in widget.instruments["sample"].text.toPlainText()
    assert "PAUSADO" in widget.instruments["sample"].text.toPlainText()
    assert widget._samples == 321
    assert not hasattr(widget, "status_text")
    widget.reset()
    assert "SEM ENSAIO" in widget.instruments["sample"].text.toPlainText()
    assert not widget.animation_running


def test_synoptic_missing_sensor_and_resource(qt_application) -> None:
    widget = ProcessSynoptic()
    assert "SEM LEITURA" in widget.instruments["pressure"].text.toPlainText()
    assert not widget.animation_running
    assert len(widget.equipment_items) == 7
    assert all(
        item.__class__.__name__ == "EquipmentItem" for item in widget.equipment_items.values()
    )
    assert widget.pipe.__class__.__name__ == "PipeItem"
    for asset in (
        "filter_regulator.svg",
        "flowmeter.svg",
        "pressure_regulator.svg",
        "pressure_transmitter.svg",
        "sample_holder.svg",
        "pump.svg",
        "valve.svg",
    ):
        assert resource_path("assets", "synoptic", "equipment", asset).is_file()
    spec = resource_path("PermeabilimetroSupervisorio.spec").read_text(encoding="utf-8")
    assert '"assets/synoptic"' in spec
