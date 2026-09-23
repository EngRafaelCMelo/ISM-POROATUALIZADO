"""Gera capturas determinísticas do sinótico para revisão visual."""

# ruff: noqa: E402

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from config.settings import AppPaths, ConfigManager
from core.constants import ReadingQuality, Severity
from core.models import Alarm, SensorReading
from database.database import Database
from ui.main_window import MainWindow
from ui.pages import OverviewPage

OUTPUT = ROOT / "artifacts" / "synoptic"


def reading(value, unit, quality, *, age=0, status="OK") -> SensorReading:
    return SensorReading(
        value=value,
        quality=quality,
        raw_value=int(value * 1000) if value is not None else None,
        current_ma=12.4 if unit == "psi" else None,
        device_status=status,
        unit=unit,
        timestamp=datetime.now() - timedelta(seconds=age),
    )


def configure(window: MainWindow, state: str) -> None:
    page: OverviewPage = window.overview
    page.reset_test()
    page.alarm_table.setRowCount(0)
    page._update_alarm_summary()
    page.simulation_banner.hide()
    synoptic = page.synoptic
    window.simulating = False
    pressure_connected = state not in {"sem-conexao", "somente-flowmeter"}
    flow_connected = state not in {
        "sem-conexao",
        "somente-pressao",
        "flowmeter-desconectado",
    }
    window.connected = pressure_connected
    window.flow_connected = flow_connected
    window._update_connection_summary()
    synoptic.set_pressure_connection("OK" if pressure_connected else "DISCONNECTED")
    synoptic.set_flow_connection("OK" if flow_connected else "DISCONNECTED")
    if pressure_connected:
        page.update_pressure(reading(125.4, "psi", ReadingQuality.VALID))
    if flow_connected:
        page.update_flow(reading(64.051, "L/min", ReadingQuality.VALID))
    if state in {
        "sem-conexao",
        "conectado-sem-ensaio",
        "somente-pressao",
        "somente-flowmeter",
    }:
        return
    synoptic.set_sample("ENS-2026-042", "Arenito Botucatu A-17")
    page.set_test_active(True)
    synoptic.set_runtime("00:18:42", 1123)
    page.duration.setText("00:18:42")
    page.samples.setText("1123")
    if state == "ensaio-real":
        return
    if state == "pausado":
        page.set_test_active(True, True)
    elif state == "pressao-stale":
        page.update_pressure(reading(125.4, "psi", ReadingQuality.STALE, age=18, status="STALE"))
    elif state == "flowmeter-desconectado":
        page.update_flow(
            reading(64.051, "L/min", ReadingQuality.DISCONNECTED, age=21, status="DISCONNECTED")
        )
        synoptic.set_flow_connection("DISCONNECTED")
    elif state == "simulacao":
        window.simulating = True
        window._update_connection_summary()
        page.simulation_banner.show()
        page.update_pressure(reading(125.4, "psi", ReadingQuality.SIMULATED))
        page.update_flow(reading(64.051, "L/min", ReadingQuality.SIMULATED))
        synoptic.set_test_state("SIMULADO")
    elif state == "alarme-critico":
        page.update_pressure(reading(400.0, "psi", ReadingQuality.INVALID, status="CRITICAL"))
        synoptic.set_critical_alarm(True)
        page.add_alarm(
            1,
            Alarm(
                datetime.now(),
                "Pressão",
                Severity.CRITICAL,
                "limite",
                "Pressão acima do limite operacional",
                400.0,
            ),
        )


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    for font in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        QFontDatabase.addApplicationFont(str(ROOT / "assets" / "fonts" / font))
    app.setStyleSheet((ROOT / "ui" / "styles.qss").read_text(encoding="utf-8"))
    states = (
        "sem-conexao",
        "conectado-sem-ensaio",
        "somente-pressao",
        "somente-flowmeter",
        "ensaio-real",
        "pausado",
        "pressao-stale",
        "flowmeter-desconectado",
        "simulacao",
        "alarme-critico",
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ism-synoptic-") as temp:
        base = Path(temp)
        paths = AppPaths(
            base,
            base / "data",
            base / "logs",
            base / "exports",
            base / "config",
        )
        for folder in (paths.data, paths.logs, paths.exports, paths.config):
            folder.mkdir(parents=True, exist_ok=True)
        config = ConfigManager(paths)
        database = Database(config.database_path)
        database.initialize()
        window = MainWindow(config, database, paths)
        for width, height in ((1366, 768), (1600, 900), (1920, 1080)):
            for state in states:
                configure(window, state)
                if state == "simulacao":
                    window.mode_badge.set_state("SIMULAÇÃO", "warn")
                    window.connection_badge.set_state("Simulação ativa", "warn")
                else:
                    window.mode_badge.set_state("MODO REAL", "info")
                window.resize(width, height)
                window.show()
                app.processEvents()
                target = OUTPUT / f"{width}x{height}-{state}.png"
                if not window.grab().save(str(target), "PNG"):
                    raise RuntimeError(f"Falha ao salvar {target}")
        window.close()
    print(f"{len(states) * 3} capturas geradas em {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
