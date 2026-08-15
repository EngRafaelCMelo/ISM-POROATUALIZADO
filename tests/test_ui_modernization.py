from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QTabWidget

from config.settings import AppPaths, ConfigManager
from database.database import Database
from ui.main_window import MainWindow


def build_window(tmp_path: Path) -> MainWindow:
    paths = AppPaths(tmp_path, tmp_path / "data", tmp_path / "logs", tmp_path / "exports", tmp_path / "config")
    for folder in (paths.data, paths.logs, paths.exports, paths.config):
        folder.mkdir(parents=True, exist_ok=True)
    config = ConfigManager(paths); database = Database(config.database_path); database.initialize()
    return MainWindow(config, database, paths)


def test_navigation_has_local_icons_and_required_pages(tmp_path) -> None:
    window = build_window(tmp_path)
    labels = [button.text() for button in window.nav_buttons]
    for expected in ("Visão geral", "Novo ensaio", "Histórico", "Cálculos", "Calibração", "Configurações", "Sobre"):
        assert expected in labels
    assert all(not button.icon().isNull() for button in window.nav_buttons)
    assert set(window.overview.cards) == {"pressao", "vazao"}
    window.close()


def test_layout_keeps_primary_controls_visible_at_supported_sizes(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = build_window(tmp_path); window.show()
    for width, height in ((1366, 768), (1600, 900), (1920, 1080)):
        window.resize(width, height); app.processEvents()
        assert window.overview.start_button.isVisible()
        assert window.overview.finish_button.isVisible()
        assert window.connect_button.isVisible()
        assert window.stack.geometry().width() > 800
    window.close()


def test_settings_expose_all_technical_groups(tmp_path) -> None:
    window = build_window(tmp_path)
    assert window.settings.tabs.tabPosition() == QTabWidget.TabPosition.North
    assert window.settings.tabs.count() >= 6
    labels = [window.settings.tabs.tabText(index) for index in range(window.settings.tabs.count())]
    assert {"Conexão", "Transdutor", "Modbus", "ADS1115", "Cálculos", "Dados"}.issubset(labels)
    window.close()
