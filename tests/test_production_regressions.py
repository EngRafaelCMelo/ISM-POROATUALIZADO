from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest
from pypdf import PdfReader
from PySide6.QtWidgets import QDialog, QMessageBox

from config.settings import AppPaths, ConfigManager
from core.constants import ReadingQuality
from core.models import Measurement, SensorReading
from core.models import TestDefinition as Definition
from database.database import Database
from database.repositories import EventRepository
from database.repositories import TestRepository as Repository
from services.chart_service import ChartService
from services.export_service import ExportService
from ui.calculation_page import CalculationPage
from ui.dialogs.test_dialog import TestSetupDialog as SetupDialog
from ui.main_window import MainWindow
from ui.pages import GraphsPage
from ui.pages import TestPage as SessionPage


def app_paths(tmp_path) -> AppPaths:
    paths = AppPaths(
        tmp_path,
        tmp_path / "data",
        tmp_path / "logs",
        tmp_path / "exports",
        tmp_path / "config",
    )
    for directory in (paths.data, paths.logs, paths.exports, paths.config):
        directory.mkdir()
    return paths


def combined_measurement(
    pressure: float = 200.0,
    flow: float = 2.0,
    *,
    timestamp: datetime | None = None,
    quality: ReadingQuality = ReadingQuality.VALID,
    state: str = "OK",
    sequence: int = 1,
) -> Measurement:
    timestamp = timestamp or datetime.now()
    return Measurement(
        timestamp,
        pressure=SensorReading(
            value=pressure,
            quality=quality,
            timestamp=timestamp,
            device_status=quality.name,
            raw_value=123,
            current_ma=12.0,
        ),
        flow=SensorReading(
            value=flow,
            quality=quality,
            timestamp=timestamp + timedelta(milliseconds=100),
            device_status=quality.name,
            raw_value=456,
            unit="L/min",
        ),
        communication_state=state,
        sequence=sequence,
        schema_version=1,
        firmware_version="2.2.0",
    )


def calculation_page() -> CalculationPage:
    page = CalculationPage(
        {
            "calculos": {"pressao_atmosferica_kpa": 101.325},
            "aquisicao": {"intervalo_s": 1.0},
        }
    )
    page.set_session(
        Definition(
            "CALC-1",
            "Amostra",
            sample_length_mm=50,
            sample_diameter_mm=25,
            pressure_unit="kPa",
        )
    )
    page.outlet_mode.setCurrentIndex(page.outlet_mode.findData("atmosphere"))
    page.flow_ref.setValue(101.325)
    return page


def test_start_test_through_main_window_uses_active_mode(tmp_path, monkeypatch) -> None:
    paths = app_paths(tmp_path)
    config = ConfigManager(paths)
    database = Database(config.database_path)
    database.initialize()
    window = MainWindow(config, database, paths)
    window.simulating = True
    definition = Definition(
        "ACTIVE-1",
        "Amostra",
        pressure_unit="bar",
        flow_unit="L/min",
        sample_length_mm=50,
        sample_diameter_mm=25,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )
    monkeypatch.setattr(SetupDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(SetupDialog, "definition", lambda self: definition)

    window._start_test()

    assert window.test_service.current is not None
    assert window.calculations._read_only is False
    assert window.calculations.capture_button.isEnabled()
    assert window.calculations.calculate_button.isEnabled()
    assert window.graphs.pressure_unit == "bar"
    assert window.graphs.flow_unit == "L/min"
    window.test_service.current = None
    window.close()


def test_historical_test_remains_read_only(tmp_path, monkeypatch) -> None:
    paths = app_paths(tmp_path)
    config = ConfigManager(paths)
    database = Database(config.database_path)
    database.initialize()
    window = MainWindow(config, database, paths)
    session = window.test_repository.create(Definition("HISTORY-1", "Amostra"))
    window.test_repository.finish(session.id)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok),
    )

    window._open_test_details(session.id)

    assert window.calculations._read_only is True
    assert not window.calculations.capture_button.isEnabled()
    assert not window.calculations.calculate_button.isEnabled()
    assert window.graphs._historical_test_id == session.id
    window.close()


def test_captured_measurement_is_immutable_when_new_reading_arrives() -> None:
    page = calculation_page()
    first_time = datetime(2026, 9, 18, 10, 0, 0)
    page.update_measurement(combined_measurement(timestamp=first_time, sequence=10))
    page._capture()
    page.update_measurement(
        combined_measurement(
            pressure=250, flow=3, timestamp=first_time + timedelta(seconds=1), sequence=11
        )
    )
    page._calculate()

    _, inputs, _, _ = page.pending_results()[0]
    assert inputs["inlet_pressure_entered"] == 200
    assert inputs["flow_l_min"] == 2
    assert inputs["reading_timestamps"]["pressure"] == first_time.isoformat()
    assert inputs["captured_measurement"]["sequence"] == 10
    assert inputs["data_origin"] == "leitura_combinada"


def test_manual_change_after_capture_marks_mixed_origin() -> None:
    page = calculation_page()
    page.update_measurement(combined_measurement())
    page._capture()
    page.flow.setValue(2.5)
    page._calculate()
    assert page.pending_results()[0][1]["data_origin"] == "mista"


@pytest.mark.parametrize(
    ("quality", "state"),
    [
        (ReadingQuality.INVALID, "INVALID"),
        (ReadingQuality.STALE, "STALE"),
        (ReadingQuality.DISCONNECTED, "DISCONNECTED"),
        (ReadingQuality.MISSING, "INVALID"),
    ],
)
def test_invalid_capture_is_blocked(quality, state, monkeypatch) -> None:
    page = calculation_page()
    page.update_measurement(combined_measurement(quality=quality, state=state))
    messages = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: messages.append(args[2])),
    )
    page._capture()
    assert page._captured_snapshot is None
    assert messages


@pytest.mark.parametrize(
    ("quality", "included"),
    [
        (ReadingQuality.VALID, True),
        (ReadingQuality.WARNING, True),
        (ReadingQuality.SIMULATED, True),
        (ReadingQuality.INVALID, False),
        (ReadingQuality.STALE, False),
        (ReadingQuality.DISCONNECTED, False),
        (ReadingQuality.MISSING, False),
    ],
)
def test_realtime_statistics_follow_central_validity_policy(quality, included) -> None:
    page = SessionPage()
    measurement = combined_measurement(quality=quality, state=quality.name)
    page.add_measurement(measurement)
    assert bool(page.values["Pressão"]) is included
    assert bool(page.values["Vazão"]) is included


def test_graph_units_controls_and_reset_do_not_leak_state() -> None:
    page = GraphsPage()
    page.set_units("MPa", "mL/min")
    assert page.pressure_unit == "MPa"
    assert page.flow_unit == "mL/min"
    assert page.plots[0].getAxis("left").labelUnits == "MPa"
    assert page.plots[1].getAxis("left").labelUnits == "mL/min"
    page.auto_zoom.setChecked(False)
    assert not any(page.plots[0].vb.state["autoRange"])

    page.visual_pause.setChecked(True)
    page.add_pressure(combined_measurement().pressure)
    assert page.curves["pressure"].xData is None
    page.visual_pause.setChecked(False)
    assert len(page.curves["pressure"].xData) == 1

    page.permeability_plots[2].setTitle("resultado anterior")
    page.reset()
    assert page.permeability_plots[2].titleLabel.text == "Klinkenberg: permeabilidade × 1/Pm"
    assert not page.pressure
    assert not page.klinkenberg_x


def test_klinkenberg_legacy_points_ignore_malformed_values() -> None:
    record = {
        "inputs": {
            "points": [
                {"inverse_pressure_kpa": 0.01, "permeability_md": 10},
                {"mean_pressure_kpa_abs": 200, "permeability_md": 9},
                {"mean_pressure_kpa_abs": None, "permeability_md": 8},
                {"mean_pressure_kpa_abs": 0, "permeability_md": 8},
                {"inverse_pressure_kpa": float("nan"), "permeability_md": 8},
            ]
        },
        "results": {},
    }
    assert ChartService.klinkenberg_points(record) == [(0.01, 10.0), (0.005, 9.0)]


def test_combined_pairs_current_legacy_and_missing_timestamps() -> None:
    start = datetime(2026, 9, 18, 10, 0, 0)
    records = pd.DataFrame(
        [
            {
                "pressao": 100,
                "vazao": 10,
                "pressao_valida": 1,
                "vazao_valida": 1,
                "timestamp_pressao": start,
                "timestamp_vazao": start + timedelta(milliseconds=200),
                "timestamp_computador": start,
                "estado_comunicacao": "OK",
                "versao_schema": 1,
            },
            {
                "pressao": 101,
                "vazao": 11,
                "pressao_valida": 1,
                "vazao_valida": 1,
                "timestamp_pressao": start,
                "timestamp_vazao": start + timedelta(seconds=3),
                "timestamp_computador": start,
                "estado_comunicacao": "OK",
                "versao_schema": 1,
            },
            {
                "pressao": 102,
                "vazao": 12,
                "pressao_valida": 1,
                "vazao_valida": 1,
                "timestamp_pressao": None,
                "timestamp_vazao": None,
                "timestamp_computador": start + timedelta(seconds=4),
                "estado_comunicacao": "conectado",
                "versao_schema": 0,
            },
            {
                "pressao": 103,
                "vazao": 13,
                "pressao_valida": 0,
                "vazao_valida": 1,
                "timestamp_computador": start + timedelta(seconds=5),
                "estado_comunicacao": "conectado",
                "versao_schema": 0,
            },
            {
                "pressao": 104,
                "vazao": 14,
                "pressao_valida": 1,
                "vazao_valida": 1,
                "timestamp_pressao": None,
                "timestamp_vazao": None,
                "timestamp_computador": start + timedelta(seconds=6),
                "estado_comunicacao": "OK",
                "versao_schema": 1,
            },
        ]
    )
    pairs = ChartService(sync_tolerance_seconds=1).combined_pairs(records)
    assert pairs["pressure"].tolist() == [100, 102]


def test_full_statistics_match_xlsx_for_more_than_2500_points(tmp_path, monkeypatch) -> None:
    database = Database(tmp_path / "stats.db")
    database.initialize()
    repository = Repository(database)
    events = EventRepository(database)
    session = repository.create(
        Definition("STATS-1", "Amostra", pressure_unit="kPa", flow_unit="L/min")
    )
    test = repository.get(session.id)
    start = datetime(2026, 9, 18)
    count = 3_200
    frame = pd.DataFrame(
        {
            "timestamp_computador": [start + timedelta(seconds=i) for i in range(count)],
            "timestamp_pressao": [start + timedelta(seconds=i) for i in range(count)],
            "timestamp_vazao": [start + timedelta(seconds=i) for i in range(count)],
            "pressao": list(range(count)),
            "vazao": [value / 10 for value in range(count)],
            "pressao_valida": [0 if i in (100, 200) else 1 for i in range(count)],
            "vazao_valida": 1,
            "status_pressao": ["STALE" if i == 300 else "OK" for i in range(count)],
            "status_vazao": "OK",
            "estado_comunicacao": "OK",
            "versao_schema": 1,
        }
    )
    service = ExportService(repository, events)
    stats = service.measurement_statistics(frame, test)
    pressure = stats.loc[stats["Grandeza"] == "Pressão"].iloc[0]
    expected = frame.loc[
        frame["pressao_valida"].eq(1) & frame["status_pressao"].eq("OK"), "pressao"
    ]
    assert pressure["N válido"] == len(expected)
    assert pressure["Média"] == pytest.approx(expected.mean())
    assert len(service.charts.plot_sensor_series(frame, "pressao")) < len(expected)

    calculations = pd.DataFrame(
        [
            {
                "timestamp": (start + timedelta(minutes=i)).isoformat(),
                "tipo": "Permeabilidade a gás",
                "entradas_json": json.dumps(
                    {
                        "gas": "Helio",
                        "reading_timestamps": {"pressure": start.isoformat()},
                        "captured_measurement": {"sequence": i, "delta_seconds": 0.1},
                    }
                ),
                "resultados_json": json.dumps(
                    {"permeability_md": 10 + i, "mean_pressure_kpa_abs": 100 + i}
                ),
                "observacoes": "",
            }
            for i in range(12)
        ]
    )
    empty = pd.DataFrame()
    monkeypatch.setattr(
        service,
        "_data",
        lambda test_id: (test, frame, empty, empty, calculations),
    )
    xlsx = service.export_xlsx(session.id, tmp_path)
    pdf = service.export_pdf(session.id, tmp_path)
    xlsx_stats = pd.read_excel(xlsx, sheet_name="Resumo", skiprows=4)
    xlsx_pressure = xlsx_stats.loc[xlsx_stats["Grandeza"] == "Pressão"].iloc[0]
    assert xlsx_pressure["N válido"] == len(expected)
    assert xlsx_pressure["Média"] == pytest.approx(expected.mean())
    assert pdf.stat().st_size > 20_000
    assert pdf.read_bytes().count(b"/Subtype /Image") >= 3
    extracted = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert "NaN" not in extracted
    database.close()
