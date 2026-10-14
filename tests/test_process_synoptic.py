from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsItem

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


def test_manual_setpoints_are_independent_from_line_pressure_and_lock(qt_application) -> None:
    widget = ProcessSynoptic()
    widget.set_setpoints(180.0, 72.0)
    widget.update_pressure(
        SensorReading(
            value=125.4,
            quality=ReadingQuality.VALID,
            unit="psi",
            timestamp=datetime.now(),
        )
    )
    assert widget.setpoints() == (180.0, 72.0)
    assert "125,40 psi" in widget.instruments["pressure"].text.toPlainText()
    widget.set_setpoints_locked(True)
    assert not widget.confinement_control.isEnabled()
    assert not widget.temperature_control.isEnabled()


def test_holder_pipes_end_at_svg_ports_and_discharge_label_stays_clear(qt_application) -> None:
    widget = ProcessSynoptic()

    process_points = {
        (
            round(widget.pipe.path().elementAt(index).x, 2),
            round(widget.pipe.path().elementAt(index).y, 2),
        )
        for index in range(widget.pipe.path().elementCount())
    }
    confinement_points = {
        (
            round(widget.confinement_pipe.path().elementAt(index).x, 2),
            round(widget.confinement_pipe.path().elementAt(index).y, 2),
        )
        for index in range(widget.confinement_pipe.path().elementCount())
    }

    for port in ("inlet", "outlet"):
        point = tuple(round(value, 2) for value in widget.holder_ports[port])
        assert point in process_points
    confinement = tuple(round(value, 2) for value in widget.holder_ports["confinement"])
    assert confinement in confinement_points

    discharge_bounds = widget.discharge_label.sceneBoundingRect()
    discharge_line_y = widget._equipment_port("valve", "right").y()
    assert discharge_bounds.top() > discharge_line_y
    assert discharge_bounds.bottom() < widget.scene.sceneRect().bottom()
    widget.close()


def test_layout_editor_moves_items_and_reconnects_holder_pipes(qt_application) -> None:
    widget = ProcessSynoptic()
    original_inlet = widget.holder_ports["inlet"]
    widget.set_layout_editing(True)
    movable = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
    assert all(item.flags() & movable for item in widget.layout_items.values())
    assert not widget.confinement_control.isEnabled()

    widget.equipment_items["sample"].moveBy(24, -12)
    widget._rebuild_connections()
    assert widget.holder_ports["inlet"] == pytest.approx(
        (original_inlet[0] + 24, original_inlet[1] - 12)
    )

    saved = widget.layout_positions()
    restored = ProcessSynoptic()
    restored.apply_layout(saved)
    assert restored.equipment_items["sample"].pos() == widget.equipment_items["sample"].pos()
    assert restored.holder_ports["inlet"] == pytest.approx(widget.holder_ports["inlet"])

    restored.reset_layout()
    assert restored.equipment_items["sample"].pos().x() == 436.5
    assert restored.equipment_items["sample"].pos().y() == 315.8
    widget.close()
    restored.close()


def test_layout_editor_can_drag_embedded_setpoint_control(qt_application) -> None:
    widget = ProcessSynoptic()
    widget.resize(1200, 480)
    widget.show()
    qt_application.processEvents()
    widget.set_layout_editing(True)
    control = widget.confinement_proxy
    before = control.pos()
    start = widget.mapFromScene(control.sceneBoundingRect().center())
    target = start + QPoint(24, 12)

    QTest.mousePress(widget.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(widget.viewport(), target, 50)
    QTest.mouseRelease(widget.viewport(), Qt.MouseButton.LeftButton, pos=target)
    qt_application.processEvents()

    assert control.pos() != before
    widget.close()


def test_synoptic_missing_sensor_and_resource(qt_application) -> None:
    widget = ProcessSynoptic()
    assert "SEM LEITURA" in widget.instruments["pressure"].text.toPlainText()
    assert not widget.animation_running
    assert len(widget.equipment_items) == 6
    assert "regulator" not in widget.equipment_items
    assert "card.local_reading" not in widget.layout_items
    assert all(
        item.__class__.__name__ == "EquipmentItem" for item in widget.equipment_items.values()
    )
    assert widget.pipe.__class__.__name__ == "PipeItem"
    for asset in (
        "filter_regulator.svg",
        "flowmeter.svg",
        "pressure_transmitter.svg",
        "sample_holder.svg",
        "pump.svg",
        "valve.svg",
    ):
        assert resource_path("assets", "synoptic", "equipment", asset).is_file()
    spec = resource_path("PermeabilimetroSupervisorio.spec").read_text(encoding="utf-8")
    assert '"assets/synoptic"' in spec
