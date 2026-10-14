from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from ui.dialogs.test_dialog import TestSetupDialog as SetupDialog
from ui.pages import (
    DiagnosticsPage,
    GraphsPage,
    OverviewPage,
    SettingsPage,
)
from ui.pages import (
    TestPage as SupervisorTestPage,
)
from ui.widgets.process_synoptic import ProcessSynoptic


def test_buttons_reserve_vertical_space_for_font() -> None:
    app = QApplication.instance() or QApplication([])
    button = QPushButton("Iniciar ensaio")
    with open("ui/styles.qss", encoding="utf-8") as handle:
        button.setStyleSheet(handle.read())
    button.show()
    app.processEvents()
    assert button.height() >= button.fontMetrics().height() + 18
    button.close()


def test_hardware_pages_show_one_pressure_and_one_flow() -> None:
    app = QApplication.instance() or QApplication([])
    config = json.loads(
        (Path(__file__).parents[1] / "config" / "default_config.json").read_text(encoding="utf-8")
    )
    overview = OverviewPage(config["sensores"])
    graphs = GraphsPage()
    test_page = SupervisorTestPage()
    settings = SettingsPage(config)
    diagnostics = DiagnosticsPage()

    assert set(overview.cards) == {"pressao", "vazao"}
    assert set(test_page.values) == {"Pressão", "Vazão"}
    assert settings.sensor_table.rowCount() == 2
    assert "high" not in graphs.curves
    assert "ma_low" not in diagnostics.values
    assert "ma_high" not in diagnostics.values

    for widget in (overview, graphs, test_page, settings, diagnostics):
        widget.close()
    app.processEvents()


def test_new_test_dialog_opens(tmp_path) -> None:
    dialog = SetupDialog(
        "ENS-2026-0300",
        tmp_path,
        temperature_setpoint_c=63.5,
        confinement_pressure_setpoint_psi=175.0,
    )
    assert dialog.temperature.value() == 63.5
    assert dialog.confinement_pressure.value() == 175.0
    dialog.sample.setText("Amostra")
    dialog._validate()
    assert dialog.sample.text() == "Amostra"
    definition = dialog.definition()
    assert definition.temperature_c == 63.5
    assert definition.confinement_pressure_setpoint_psi == 175.0
    dialog.close()


def test_confirmed_dialog_conditions_return_to_overview_setpoints(tmp_path) -> None:
    synoptic = ProcessSynoptic()
    synoptic.set_setpoints(150.0, 60.0)
    pressure, temperature = synoptic.setpoints()
    dialog = SetupDialog(
        "ENS-2026-0301",
        tmp_path,
        temperature_setpoint_c=temperature,
        confinement_pressure_setpoint_psi=pressure,
    )
    dialog.temperature.setValue(75.0)
    dialog.confinement_pressure.setValue(210.0)
    definition = dialog.definition()
    synoptic.set_setpoints(
        definition.confinement_pressure_setpoint_psi,
        definition.temperature_c,
    )
    assert synoptic.setpoints() == (210.0, 75.0)
    dialog.close()
    synoptic.close()
