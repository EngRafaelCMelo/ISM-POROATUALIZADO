from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

from app import report_smoke
from core.constants import ReadingQuality, Severity
from core.models import Alarm, Measurement, SensorReading
from core.models import TestDefinition as Definition
from core.permeability import calculate_klinkenberg
from database.database import Database
from database.repositories import CalculationRepository, EventRepository
from database.repositories import TestRepository as Repository
from services.export_service import ExportService
from ui.resources import font_path, resource_path

FORBIDDEN_INTERNAL_NAMES = (
    "pressure_inlet_kpa_abs",
    "data_origin",
    "reading_timestamps",
    "entradas_json",
    "resultados_json",
)


def _text(path: Path) -> tuple[PdfReader, str]:
    reader = PdfReader(path)
    return reader, "\n".join(page.extract_text() or "" for page in reader.pages)


def _build_report(
    tmp_path: Path,
    *,
    simulated: bool = False,
    point_count: int = 3,
    with_fit: bool = True,
    alarm_count: int = 1,
    long_comment: bool = False,
    legacy: bool = False,
) -> tuple[Database, ExportService, int, Path]:
    database = Database(tmp_path / f"report-{simulated}-{point_count}.db")
    database.initialize()
    tests = Repository(database)
    events = EventRepository(database)
    session = tests.create(
        Definition(
            code="ENS-PDF-SIM" if simulated else "ENS-PDF-REAL",
            sample_name="Amostra São João",
            operator="Operador José",
            pressure_unit="kPa",
            flow_unit="NL/min",
            sample_length_mm=50.25,
            sample_diameter_mm=25.4,
            sample_mass_g=42.125,
            bulk_volume_cm3=25.338,
            gas_type="Hélio",
            temperature_c=23.4,
            atmospheric_pressure_kpa=101.325,
            firmware_version="FW-2.1",
            simulated=simulated,
        )
    )
    start = datetime(2026, 9, 18, 10, 0)
    qualities = (
        ReadingQuality.VALID,
        ReadingQuality.VALID,
        ReadingQuality.INVALID,
        ReadingQuality.STALE,
        ReadingQuality.DISCONNECTED,
        ReadingQuality.VALID,
    )
    for index, quality in enumerate(qualities):
        timestamp = start + timedelta(seconds=index)
        status = "OK" if quality == ReadingQuality.VALID else quality.value.upper()
        tests.save_measurement(
            session.id,
            Measurement(
                received_at=timestamp,
                pressure=SensorReading(
                    value=100.0 + index if quality == ReadingQuality.VALID else 9999.0,
                    quality=quality,
                    timestamp=timestamp,
                    device_status=status,
                    unit="kPa",
                ),
                flow=SensorReading(
                    value=10.0 + index if quality == ReadingQuality.VALID else 9999.0,
                    quality=quality,
                    timestamp=timestamp + timedelta(milliseconds=100),
                    device_status=status,
                    unit="NL/min",
                ),
                communication_state="OK" if quality == ReadingQuality.VALID else status,
                simulated=simulated,
                schema_version=1,
                firmware_version="FW-2.1",
            ),
        )

    calculations = CalculationRepository(database)
    points: list[tuple[float, float]] = []
    for index in range(point_count):
        pressure = 100.0 + index * 10
        permeability = 15.0 - index * 0.05
        points.append((pressure, permeability))
        calculations.save(
            session.id,
            "Permeabilidade a gás",
            {
                "flow_nl_min": 2.5 + index / 10,
                "data_origin": "leitura_combinada",
                "reading_timestamps": {"pressure": start.isoformat()},
                "pressure_inlet_kpa_abs": pressure + 5,
            },
            {
                "permeability_md": permeability,
                "mean_pressure_kpa_abs": pressure,
                "pressure_drop_kpa": 10.0,
            },
        )
    if with_fit and len(points) >= 2:
        fit = calculate_klinkenberg(points).as_dict()
        calculations.save(session.id, "Klinkenberg", {"points": fit["points_used"]}, fit)
    if legacy:
        calculations.save(session.id, "Registro legado", {}, {})

    for index in range(alarm_count):
        message = "Pressão acima do limite"
        if long_comment:
            message += " — descrição extensa " + ("segura e legível " * 180)
        events.add_alarm(
            session.id,
            Alarm(
                start + timedelta(minutes=index),
                "pressao" if index % 2 == 0 else "vazao",
                Severity.WARNING,
                "limite",
                message,
                123.45,
            ),
        )
    events.add_marker(session.id, "Operação", "Ajuste fino efetuado pelo operador.")
    tests.finish(session.id, "á à â ã é ê í ó ô õ ú ç ° ² Δ ∞ × R²")
    service = ExportService(tests, events)
    target = service.export_pdf(session.id, tmp_path)
    return database, service, session.id, target


def test_real_pdf_has_logo_unicode_fonts_and_no_internal_names(tmp_path) -> None:
    database, _, _, target = _build_report(tmp_path)
    reader, text = _text(target)
    assert 5 <= len(reader.pages) <= 8
    assert len(reader.pages[0].images) >= 1
    assert "RELATÓRIO FINAL DE ENSAIO" in text
    assert "RELATÓRIO DEMONSTRATIVO" not in text
    assert "á à â ã é ê í ó ô õ ú ç ° ² Δ ∞ × R²" in text
    assert not any(name in text for name in FORBIDDEN_INTERNAL_NAMES)
    assert not any(token in text for token in ("NaN", "Infinity", "None", "{}", "[]"))
    font_names = []
    for page in reader.pages:
        fonts = page["/Resources"].get("/Font", {}).get_object()
        font_names.extend(str(item.get_object().get("/BaseFont")) for item in fonts.values())
    assert any("DejaVuSans" in name for name in font_names)
    database.close()


def test_simulation_banner_appears_only_for_simulated_report(tmp_path) -> None:
    real_db, _, _, real_target = _build_report(tmp_path / "real")
    sim_db, _, _, simulated_target = _build_report(tmp_path / "sim", simulated=True)
    assert "RELATÓRIO DEMONSTRATIVO - DADOS FICTÍCIOS" not in _text(real_target)[1]
    assert "RELATÓRIO DEMONSTRATIVO - DADOS FICTÍCIOS" in _text(simulated_target)[1]
    real_db.close()
    sim_db.close()


def test_statistics_use_all_and_only_valid_measurements(tmp_path) -> None:
    database, service, test_id, _ = _build_report(tmp_path)
    test, measurements, *_ = service._data(test_id)
    stats = service.measurement_statistics(measurements, test)
    pressure = stats.loc[stats["Grandeza"] == "Pressão"].iloc[0]
    assert pressure["N válido"] == 3
    assert pressure["Mínimo"] == 100.0
    assert pressure["Média"] == 102.0
    assert pressure["Máximo"] == 105.0
    assert service._status_counts(measurements, "pressao") == {
        "INVALID": 1,
        "STALE": 1,
        "DISCONNECTED": 1,
    }
    database.close()


def test_legacy_valid_values_without_timestamps_are_included_in_statistics(tmp_path) -> None:
    database, service, test_id, _ = _build_report(tmp_path)
    test = service.tests.get(test_id)
    frame = service._current_measurements(service._data(test_id)[1])
    frame.loc[0, "timestamp_pressao"] = None
    stats = service.measurement_statistics(frame, test)
    pressure = stats.loc[stats["Grandeza"] == "Pressão"].iloc[0]
    assert pressure["N válido"] == 3
    assert pressure["Média"] == 102.0
    database.close()


def test_many_permeability_points_share_a_paginated_table(tmp_path) -> None:
    database, _, _, target = _build_report(tmp_path, point_count=45)
    reader, text = _text(target)
    assert "Permeabilidade aparente (mD)" in re.sub(r"\s+", " ", text)
    assert "45" in text
    assert len(reader.pages) < 15
    assert text.count("Resultados de permeabilidade") == 1
    database.close()


def test_klinkenberg_valid_insufficient_and_no_calculations(tmp_path) -> None:
    valid_db, _, _, valid = _build_report(tmp_path / "valid", point_count=3, with_fit=True)
    insufficient_db, _, _, insufficient = _build_report(
        tmp_path / "insufficient", point_count=1, with_fit=False
    )
    empty_db, _, _, empty = _build_report(tmp_path / "empty", point_count=0, with_fit=False)
    valid_text = _text(valid)[1]
    insufficient_text = _text(insufficient)[1]
    empty_text = _text(empty)[1]
    assert "Permeabilidade intrínseca k∞" in valid_text
    assert "Coeficiente R²" in valid_text
    expected = "Dados insuficientes para calcular o ajuste de Klinkenberg."
    assert expected in insufficient_text
    assert expected in empty_text
    assert "Nenhum cálculo foi salvo para este ensaio." in empty_text
    valid_db.close()
    insufficient_db.close()
    empty_db.close()


def test_many_alarms_long_comments_and_legacy_data_are_robust(tmp_path) -> None:
    database, _, _, target = _build_report(
        tmp_path,
        point_count=2,
        alarm_count=35,
        long_comment=True,
        legacy=True,
    )
    reader, text = _text(target)
    assert "Ocorrências e registros do operador" in text
    assert "Alarme - Pressão" in text
    assert "Alarme - Vazão" in text
    assert "descrição extensa" in text
    assert len(reader.pages) < 30
    database.close()


def test_every_report_page_renders_and_section_titles_are_not_isolated(tmp_path) -> None:
    database, _, _, target = _build_report(tmp_path)
    document = pdfium.PdfDocument(str(target))
    rendered = tmp_path / "rendered"
    rendered.mkdir()
    for index, page in enumerate(document):
        image = page.render(scale=0.6).to_pil()
        image.save(rendered / f"page-{index + 1}.png")
        assert image.width > 0 and image.height > 0
    assert len(list(rendered.glob("page-*.png"))) == len(document)
    reader, _ = _text(target)
    assert len(reader.pages) <= 6
    for page in reader.pages:
        lines = [line.strip() for line in (page.extract_text() or "").splitlines() if line.strip()]
        assert any("1." <= line[:2] <= "8." for line in lines) or "RELATÓRIO FINAL" in " ".join(
            lines
        )
        if lines and lines[-1][0:2] in {"1.", "2.", "3.", "4.", "5.", "6.", "7.", "8."}:
            raise AssertionError(f"Título de seção isolado: {lines[-1]}")
    database.close()


def test_pdf_generation_uses_pyinstaller_resource_root(tmp_path, monkeypatch) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(resource_path("assets"), bundle / "assets")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert font_path("DejaVuSans.ttf") == bundle / "assets" / "fonts" / "DejaVuSans.ttf"
    database, _, _, target = _build_report(tmp_path / "data")
    assert target.read_bytes().startswith(b"%PDF")
    assert len(PdfReader(target).pages[0].images) >= 1
    database.close()


def test_packaged_report_smoke_uses_isolated_simulated_database(tmp_path) -> None:
    target = report_smoke(tmp_path)
    reader, text = _text(target)
    assert target.name.startswith("ENS-PACOTE-SIMULADO")
    assert len(reader.pages[0].images) >= 1
    assert "RELATÓRIO DEMONSTRATIVO - DADOS FICTÍCIOS" in text
    assert "Validação de á é í ó ú ç ° ² Δ ∞ × R²" in text
