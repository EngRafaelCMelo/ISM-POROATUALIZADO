from __future__ import annotations

from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import pandas as pd
from pypdf import PdfReader

from core.constants import ReadingQuality, Severity
from core.models import Alarm, Measurement, SensorReading
from core.models import TestDefinition as Definition
from core.permeability import calculate_klinkenberg
from database.database import Database
from database.repositories import CalculationRepository, EventRepository
from database.repositories import TestRepository as Repository
from services.chart_service import ChartService
from services.export_service import ExportService
from ui.pages import GraphsPage


def measurement_frame() -> pd.DataFrame:
    start = datetime(2026, 9, 18, 10, 0, 0)
    return pd.DataFrame(
        [
            {
                "timestamp_computador": (start + timedelta(seconds=index)).isoformat(),
                "timestamp_pressao": (start + timedelta(seconds=index)).isoformat(),
                "timestamp_vazao": (start + timedelta(seconds=index, milliseconds=100)).isoformat(),
                "pressao": 100 + index,
                "vazao": 10 + index,
                "pressao_valida": index != 2,
                "vazao_valida": index != 2,
                "status_pressao": "STALE" if index == 2 else "OK",
                "status_vazao": "STALE" if index == 2 else "OK",
                "estado_comunicacao": "STALE" if index == 2 else "OK",
            }
            for index in range(5)
        ]
    )


def calculation_frame() -> pd.DataFrame:
    start = datetime(2026, 9, 18, 10, 0, 0)
    rows = []
    points = []
    for index, (pressure, permeability) in enumerate(((100.0, 15.0), (200.0, 12.5))):
        rows.append(
            {
                "timestamp": (start + timedelta(minutes=index)).isoformat(),
                "tipo": "Permeabilidade a gás",
                "entradas_json": "{}",
                "resultados_json": (
                    '{"permeability_md": %s, "mean_pressure_kpa_abs": %s}'
                    % (permeability, pressure)
                ),
            }
        )
        points.append((pressure, permeability))
    result = calculate_klinkenberg(points).as_dict()
    import json

    rows.append(
        {
            "timestamp": (start + timedelta(minutes=3)).isoformat(),
            "tipo": "Klinkenberg",
            "entradas_json": json.dumps({"points": result["points_used"]}),
            "resultados_json": json.dumps(result),
        }
    )
    return pd.DataFrame(rows)


def test_process_charts_use_valid_data_and_two_axes() -> None:
    service = ChartService()
    frame = measurement_frame()
    pressure = service.sensor_time_chart(frame, "pressao", "psi")
    flow = service.sensor_time_chart(frame, "vazao", "NL/min")
    combined = service.combined_time_chart(frame, "psi", "NL/min")
    pairs = service.combined_pairs(frame)
    assert pressure and pressure.image.getvalue().startswith(b"\x89PNG")
    assert flow and flow.image.getvalue().startswith(b"\x89PNG")
    assert combined and combined.image.getvalue().startswith(b"\x89PNG")
    assert len(pairs) == 4
    assert 102 not in pairs["pressure"].tolist()


def test_invalid_reading_creates_visible_gap() -> None:
    series = ChartService().sensor_series(measurement_frame(), "pressao")
    assert pd.isna(series.iloc[2]["value"])
    assert series["value"].notna().sum() == 4


def test_process_chart_uses_dates_when_test_spans_multiple_days() -> None:
    frame = measurement_frame()
    frame.loc[4, "timestamp_pressao"] = datetime(2026, 9, 19, 10).isoformat()
    series = ChartService().sensor_series(frame, "pressao")
    assert ChartService._time_formatter(series).fmt == "%d/%m %H:%M"


def test_permeability_and_klinkenberg_charts() -> None:
    service = ChartService()
    calculations = calculation_frame()
    assert service.permeability_time_chart(calculations) is not None
    assert service.permeability_pressure_chart(calculations) is not None
    assert service.klinkenberg_chart(calculations) is not None


def test_insufficient_data_does_not_create_empty_chart() -> None:
    service = ChartService()
    assert service.sensor_time_chart(pd.DataFrame(), "pressao", "psi") is None
    assert service.flow_pressure_chart(measurement_frame().iloc[:1], "psi", "NL/min") is None
    assert service.klinkenberg_chart(pd.DataFrame()) is None


def test_long_dataset_reduction_preserves_ends_extremes_and_closes_figures() -> None:
    start = datetime(2026, 9, 18)
    frame = pd.DataFrame(
        {
            "timestamp_pressao": [start + timedelta(seconds=i) for i in range(10_000)],
            "pressao": list(range(5000)) + list(range(5000, 0, -1)),
            "pressao_valida": 1,
            "status_pressao": "OK",
        }
    )
    service = ChartService(max_points=300)
    complete = service.validated_sensor_series(frame, "pressao")
    reduced = service.plot_sensor_series(frame, "pressao")
    before = set(plt.get_fignums())
    assert service.sensor_time_chart(frame, "pressao", "psi") is not None
    assert set(plt.get_fignums()) == before
    assert len(complete) == 10_000
    assert complete["value"].mean() == frame["pressao"].mean()
    assert len(reduced) <= 304
    assert reduced.iloc[0]["timestamp"] == frame.iloc[0]["timestamp_pressao"]
    assert reduced.iloc[-1]["timestamp"] == frame.iloc[-1]["timestamp_pressao"]
    assert reduced["value"].max() == 5000


def _database_with_report_data(tmp_path):
    database = Database(tmp_path / "charts.db")
    database.initialize()
    tests = Repository(database)
    events = EventRepository(database)
    session = tests.create(
        Definition(
            code="ENS-CHARTS",
            sample_name="Amostra",
            sample_length_mm=50,
            sample_diameter_mm=25,
        )
    )
    start = datetime.now()
    for index in range(3):
        tests.save_measurement(
            session.id,
            Measurement(
                start + timedelta(seconds=index),
                pressure=SensorReading(
                    value=100 + index,
                    quality=ReadingQuality.VALID,
                    timestamp=start + timedelta(seconds=index),
                    device_status="OK",
                ),
                flow=SensorReading(
                    value=10 + index,
                    quality=ReadingQuality.VALID,
                    timestamp=start + timedelta(seconds=index, milliseconds=100),
                    device_status="OK",
                ),
                communication_state="OK",
            ),
        )
    calculations = CalculationRepository(database)
    for pressure, permeability in ((100.0, 15.0), (200.0, 12.5)):
        calculations.save(
            session.id,
            "Permeabilidade a gás",
            {"gas": "Helio"},
            {"permeability_md": permeability, "mean_pressure_kpa_abs": pressure},
        )
    kb = calculate_klinkenberg(((100.0, 15.0), (200.0, 12.5))).as_dict()
    calculations.save(session.id, "Klinkenberg", {"points": kb["points_used"]}, kb)
    events.add_alarm(
        session.id,
        Alarm(datetime.now(), "pressao", Severity.WARNING, "limite", "Atenção", 102),
    )
    events.add_marker(session.id, "Estabilidade", "Trecho estável")
    tests.finish(session.id, "Finalizado")
    return database, tests, events, session.id


def test_pdf_contains_chart_images_alarms_and_markers(tmp_path) -> None:
    database, tests, events, test_id = _database_with_report_data(tmp_path)
    target = ExportService(tests, events).export_pdf(test_id, tmp_path)
    content = target.read_bytes()
    assert content.count(b"/Subtype /Image") >= 6
    assert content.count(b"/Type /Page") >= 2
    assert target.stat().st_size > 20_000
    database.close()


def test_pdf_without_measurements_or_calculations_is_valid(tmp_path) -> None:
    database = Database(tmp_path / "empty.db")
    database.initialize()
    tests = Repository(database)
    events = EventRepository(database)
    session = tests.create(Definition(code="ENS-EMPTY", sample_name="Sem dados"))
    tests.finish(session.id)
    target = ExportService(tests, events).export_pdf(session.id, tmp_path)
    assert target.read_bytes().startswith(b"%PDF")
    assert target.stat().st_size > 1000
    assert "Firmware não disponível" in PdfReader(target).pages[0].extract_text()
    database.close()


def test_historical_graphs_load_and_reset(qt_application, tmp_path) -> None:
    database, tests, events, test_id = _database_with_report_data(tmp_path)
    page = GraphsPage()
    page.load_history(
        test_id,
        tests.measurements(test_id),
        CalculationRepository(database).list(test_id),
        "psi",
        "NL/min",
    )
    assert len(page.pressure) == 3
    assert len(page.flow_pressure_x) == 3
    assert len(page.permeability_values) == 2
    assert len(page.klinkenberg_x) == 2
    page.reset()
    assert not page.pressure
    assert not page.permeability_values
    database.close()


def test_pyinstaller_spec_includes_headless_matplotlib() -> None:
    spec = open("PermeabilimetroSupervisorio.spec", encoding="utf-8").read()
    assert "matplotlib.backends.backend_agg" in spec
