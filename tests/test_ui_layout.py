from __future__ import annotations

import os
from pathlib import Path
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from ui.pages import (
    DiagnosticsPage,
    GraphsPage,
    OverviewPage,
    SettingsPage,
    TestPage as SupervisorTestPage,
)
from ui.dialogs.test_dialog import TestSetupDialog as SetupDialog


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
        (Path(__file__).parents[1] / "config" / "default_config.json").read_text(
            encoding="utf-8"
        )
    )
    overview = OverviewPage(config["sensores"])
    graphs = GraphsPage()
    test_page = SupervisorTestPage()
    settings = SettingsPage(config)
    diagnostics = DiagnosticsPage()

    assert set(overview.cards) == {"pressao", "vazao"}
    assert set(test_page.values) == {"Pressão", "Vazão"}
    assert settings.sensor_table.rowCount() == 2
    assert settings.calculation_minimum_cycles.value() == 3
    assert "high" not in graphs.curves
    assert "ma_low" not in diagnostics.values
    assert "ma_high" not in diagnostics.values
    assert {"pressure_state", "flow_state"}.issubset(diagnostics.values)
    assert not test_page.control_buttons["Finalizar"].isEnabled()
    assert not test_page.control_buttons["Calcular porosidade"].isEnabled()

    for widget in (overview, graphs, test_page, settings, diagnostics):
        widget.close()
    app.processEvents()


def test_new_test_dialog_guides_porosity_geometry(tmp_path) -> None:
    dialog = SetupDialog("ENS-2026-0300", tmp_path)
    assert dialog.tabs.tabText(0) == "1. Dados básicos"
    assert dialog.tabs.tabText(2) == "3. Opções avançadas"
    dialog.sample.setText("Amostra")

    dialog._validate()

    assert dialog.tabs.currentWidget() is dialog.physical_page
    assert "Informe o volume" in dialog.geometry_preview.text()
    dialog.close()
