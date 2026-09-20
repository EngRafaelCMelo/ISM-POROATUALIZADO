from __future__ import annotations

import json
import math
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    CondPageBreak,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.version import APP_VERSION
from database.repositories import CalculationRepository, EventRepository, TestRepository
from services.chart_service import INSUFFICIENT_DATA_MESSAGE, ChartService
from ui.resources import branding_path, font_path
from ui.theme import COLORS

PDF_FONT = "DejaVuSans"
PDF_FONT_BOLD = "DejaVuSans-Bold"
NOT_AVAILABLE = "Não disponível"


class NumberedCanvas(canvas.Canvas):
    """Adiciona cabeçalho e Página X de Y sem gerar o documento duas vezes."""

    def __init__(self, *args, header: str, footer: str, issued: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []
        self._header = header
        self._footer = footer
        self._issued = issued

    def showPage(self):  # noqa: N802
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_chrome(total)
            super().showPage()
        super().save()

    def _draw_chrome(self, total: int) -> None:
        width, height = A4
        self.saveState()
        self.setStrokeColor(colors.HexColor(COLORS["border"]))
        self.setFillColor(colors.HexColor(COLORS["muted"]))
        self.setFont(PDF_FONT, 7.2)
        self.line(16 * mm, height - 12 * mm, width - 16 * mm, height - 12 * mm)
        self.drawString(16 * mm, height - 9.5 * mm, self._header)
        self.line(16 * mm, 12 * mm, width - 16 * mm, 12 * mm)
        self.setFont(PDF_FONT, 6.2)
        self.drawString(16 * mm, 8.8 * mm, self._issued)
        self.drawString(16 * mm, 6.1 * mm, self._footer)
        self.setFont(PDF_FONT_BOLD, 6.5)
        self.drawRightString(width - 16 * mm, 6.1 * mm, f"Página {self._pageNumber} de {total}")
        self.restoreState()


class ExportService:
    def __init__(self, tests: TestRepository, events: EventRepository):
        self._register_fonts()
        self.tests = tests
        self.events = events
        self.calculations = CalculationRepository(tests.db)
        self.charts = ChartService()

    @staticmethod
    def _register_fonts() -> None:
        registered = set(pdfmetrics.getRegisteredFontNames())
        if PDF_FONT not in registered:
            pdfmetrics.registerFont(TTFont(PDF_FONT, str(font_path("DejaVuSans.ttf"))))
        if PDF_FONT_BOLD not in registered:
            pdfmetrics.registerFont(TTFont(PDF_FONT_BOLD, str(font_path("DejaVuSans-Bold.ttf"))))
        pdfmetrics.registerFontFamily(
            PDF_FONT,
            normal=PDF_FONT,
            bold=PDF_FONT_BOLD,
            italic=PDF_FONT,
            boldItalic=PDF_FONT_BOLD,
        )

    def _data(self, test_id: int):
        test = self.tests.get(test_id)
        if not test:
            raise ValueError("Ensaio não encontrado")
        measurements = pd.DataFrame([dict(row) for row in self.tests.measurements(test_id)])
        alarms = pd.DataFrame([dict(row) for row in self.events.alarms(test_id)])
        markers = pd.DataFrame([dict(row) for row in self.events.markers(test_id)])
        calculations = pd.DataFrame([dict(row) for row in self.calculations.list(test_id)])
        return test, measurements, alarms, markers, calculations

    @staticmethod
    def _safe_target(directory: Path, filename: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / filename
        if not target.exists():
            return target
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return directory / f"{target.stem}_{stamp}{target.suffix}"

    @staticmethod
    def _format_result(value: Any, unit: str = "") -> str:
        if value is None or isinstance(value, (dict, list, tuple)):
            return NOT_AVAILABLE
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            text = str(value).strip()
            return (
                text
                if text and text.casefold() not in {"none", "nan", "infinity", "-inf"}
                else NOT_AVAILABLE
            )
        if not math.isfinite(numeric):
            return NOT_AVAILABLE
        formatted = f"{numeric:.6g}"
        return f"{formatted} {unit}".strip()

    @staticmethod
    def _number(value: Any, decimals: int = 2, unit: str = "") -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return NOT_AVAILABLE
        if not math.isfinite(numeric):
            return NOT_AVAILABLE
        formatted = f"{numeric:.{decimals}f}".replace(".", ",")
        return f"{formatted} {unit}".strip()

    @staticmethod
    def _text(value: Any) -> str:
        if value is None or isinstance(value, (dict, list, tuple)):
            return NOT_AVAILABLE
        text = str(value).strip()
        return (
            text
            if text and text.casefold() not in {"none", "nan", "infinity", "-inf"}
            else NOT_AVAILABLE
        )

    @staticmethod
    def _timestamp(value: Any, *, time_only: bool = False) -> str:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return NOT_AVAILABLE
        return parsed.strftime("%H:%M:%S" if time_only else "%d/%m/%Y %H:%M:%S")

    @staticmethod
    def _current_measurements(measurements: pd.DataFrame) -> pd.DataFrame:
        current = measurements.copy()
        if "vazao" not in current:
            current["vazao"] = pd.NA
        for legacy in ("vazao_baixa", "vazao_alta"):
            if legacy in current:
                current["vazao"] = current["vazao"].where(current["vazao"].notna(), current[legacy])
        if "vazao_ma" not in current:
            current["vazao_ma"] = pd.NA
        for legacy in ("vazao_baixa_ma", "vazao_alta_ma"):
            if legacy in current:
                current["vazao_ma"] = current["vazao_ma"].where(
                    current["vazao_ma"].notna(), current[legacy]
                )
        legacy_columns = [
            "vazao_baixa_ma",
            "vazao_baixa",
            "vazao_alta_ma",
            "vazao_alta",
            "flow_meter_ativo",
        ]
        return current.drop(columns=[c for c in legacy_columns if c in current], errors="ignore")

    @staticmethod
    def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        clean = frame.astype(object).where(pd.notna(frame), None)
        return clean.to_dict(orient="records")

    def export_csv(self, test_id: int, directory: Path, separator: str = ";") -> Path:
        test, measurements, _, _, _ = self._data(test_id)
        target = self._safe_target(directory, f"{test['codigo']}_medicoes.csv")
        measurements = self._current_measurements(measurements)
        columns = {
            "timestamp_computador": "Data e hora da combinação",
            "timestamp_esp32": "Timestamp ESP32 (ms)",
            "timestamp_pressao": "Data e hora da pressão",
            "pressao_ads_raw": "Pressão bruta (ADS1115)",
            "pressao_ma": "Pressão (mA)",
            "pressao": f"Pressão ({test['unidade_pressao']})",
            "pressao_valida": "Pressão válida",
            "status_pressao": "Status da pressão",
            "timestamp_vazao": "Data e hora da vazão",
            "vazao_raw": "Vazão bruta (UINT32)",
            "vazao": f"Vazão ({test['unidade_vazao'] or 'unidade não registrada'})",
            "vazao_valida": "Vazão válida",
            "status_vazao": "Status da vazão",
            "qualidade": "Qualidade",
            "estado_comunicacao": "Estado da comunicação",
        }
        selected = measurements[[c for c in columns if c in measurements.columns]].rename(
            columns=columns
        )
        selected.to_csv(target, sep=separator, index=False, encoding="utf-8-sig")
        return target

    def export_json(self, test_id: int, directory: Path) -> Path:
        test, measurements, alarms, markers, calculations = self._data(test_id)
        target = self._safe_target(directory, f"{test['codigo']}.json")
        payload = {
            "ensaio": dict(test),
            "medicoes": self._records(self._current_measurements(measurements)),
            "alarmes": self._records(alarms),
            "marcacoes": self._records(markers),
            "calculos": self._records(calculations),
        }
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        return target

    def export_xlsx(self, test_id: int, directory: Path) -> Path:
        test, measurements, alarms, markers, calculations = self._data(test_id)
        target = self._safe_target(directory, f"{test['codigo']}.xlsx")
        summary = pd.DataFrame([dict(test)])
        measurements = self._current_measurements(measurements)
        stats = self.measurement_statistics(measurements, test)
        measurement_export = measurements.rename(
            columns={
                "pressao": f"pressao ({test['unidade_pressao'] or 'não disponível'})",
                "vazao": f"vazao ({test['unidade_vazao'] or 'não disponível'})",
            }
        )
        with pd.ExcelWriter(target, engine="openpyxl") as writer:
            summary.to_excel(writer, sheet_name="Resumo", index=False)
            if not stats.empty:
                stats.to_excel(writer, sheet_name="Resumo", index=False, startrow=4)
            measurement_export.to_excel(writer, sheet_name="Medições", index=False)
            alarms.to_excel(writer, sheet_name="Alarmes", index=False)
            markers.to_excel(writer, sheet_name="Marcações", index=False)
            calculations.to_excel(writer, sheet_name="Cálculos", index=False)
            pd.DataFrame(columns=["sensor", "data", "ganho", "offset"]).to_excel(
                writer, sheet_name="Calibração", index=False
            )
        return target

    def measurement_statistics(self, measurements: pd.DataFrame, test) -> pd.DataFrame:
        """Resumo compartilhado por PDF/XLSX, sempre sobre todos os pontos válidos."""
        rows = []
        for sensor, label, unit in (
            ("pressao", "Pressão", test["unidade_pressao"] or "não disponível"),
            ("vazao", "Vazão", test["unidade_vazao"] or "não disponível"),
        ):
            values = self._valid_measurement_values(measurements, sensor)
            rows.append(
                {
                    "Grandeza": label,
                    "Mínimo": values.min() if not values.empty else None,
                    "Média": values.mean() if not values.empty else None,
                    "Máximo": values.max() if not values.empty else None,
                    "Desvio padrão": values.std(ddof=0) if not values.empty else None,
                    "N válido": len(values),
                    "Unidade": unit,
                }
            )
        return pd.DataFrame(rows)

    def _valid_measurement_values(self, measurements: pd.DataFrame, sensor: str) -> pd.Series:
        """Valida valores da série integral, mesmo em registros legados sem timestamp."""
        if sensor not in measurements:
            return pd.Series(dtype=float)
        values = pd.to_numeric(measurements[sensor], errors="coerce")
        mask = self.charts._valid_mask(measurements, sensor)
        return values.where(mask).replace([math.inf, -math.inf], math.nan).dropna()

    @staticmethod
    def _styles():
        styles = getSampleStyleSheet()
        for style in styles.byName.values():
            style.fontName = PDF_FONT
            style.bulletFontName = PDF_FONT
        styles["Title"].fontName = PDF_FONT_BOLD
        styles["Heading1"].fontName = PDF_FONT_BOLD
        styles["Heading2"].fontName = PDF_FONT_BOLD
        styles["Heading3"].fontName = PDF_FONT_BOLD
        styles["BodyText"].fontSize = 8.5
        styles["BodyText"].leading = 11
        styles.add(
            ParagraphStyle(
                "ReportTitle",
                parent=styles["Title"],
                textColor=colors.HexColor(COLORS["primary"]),
                fontName=PDF_FONT_BOLD,
                fontSize=20,
                leading=24,
                alignment=TA_CENTER,
                spaceAfter=5 * mm,
            )
        )
        styles.add(
            ParagraphStyle(
                "Section",
                parent=styles["Heading2"],
                textColor=colors.HexColor(COLORS["primary"]),
                fontName=PDF_FONT_BOLD,
                fontSize=12,
                leading=14,
                keepWithNext=True,
                spaceBefore=4 * mm,
                spaceAfter=2 * mm,
            )
        )
        styles.add(
            ParagraphStyle(
                "Subsection",
                parent=styles["Heading3"],
                textColor=colors.HexColor(COLORS["text"]),
                fontName=PDF_FONT_BOLD,
                fontSize=10.5,
                leading=13,
                keepWithNext=True,
            )
        )
        styles.add(
            ParagraphStyle(
                "Notice",
                parent=styles["BodyText"],
                textColor=colors.HexColor(COLORS["muted"]),
                alignment=TA_CENTER,
                borderColor=colors.HexColor(COLORS["border"]),
                borderWidth=0.5,
                borderPadding=8,
            )
        )
        return styles

    @staticmethod
    def _table(rows, widths=None, font_size=8, repeat_rows=0):
        cell_style = ParagraphStyle(
            "TableCell",
            fontName=PDF_FONT,
            fontSize=font_size,
            leading=font_size + 2,
            textColor=colors.HexColor(COLORS["text"]),
            alignment=TA_LEFT,
        )
        label_style = ParagraphStyle(
            "TableLabel",
            parent=cell_style,
            fontName=PDF_FONT_BOLD,
        )
        header_style = ParagraphStyle(
            "TableHeader",
            parent=cell_style,
            fontName=PDF_FONT_BOLD,
            textColor=colors.white,
            leading=font_size + 1,
        )

        prepared = []
        for row_index, row in enumerate(rows):
            converted = []
            for column_index, value in enumerate(row):
                if isinstance(value, (Paragraph, Image)):
                    converted.append(value)
                    continue
                style = (
                    header_style
                    if repeat_rows and row_index < repeat_rows
                    else label_style
                    if not repeat_rows and column_index in {0, 2}
                    else cell_style
                )
                converted.append(Paragraph(escape(ExportService._text(value)), style))
            prepared.append(converted)
        table = Table(
            prepared,
            colWidths=widths,
            repeatRows=repeat_rows,
            hAlign="LEFT",
            splitByRow=True,
        )
        commands = [
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor(COLORS["border"])),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 4),
            ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
        ]
        if repeat_rows:
            commands += [
                ("BACKGROUND", (0, 0), (-1, repeat_rows - 1), colors.HexColor(COLORS["primary"])),
                ("TEXTCOLOR", (0, 0), (-1, repeat_rows - 1), colors.white),
                ("FONTNAME", (0, 0), (-1, repeat_rows - 1), PDF_FONT_BOLD),
            ]
        else:
            commands += [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F6F8")),
                ("FONTNAME", (0, 0), (0, -1), PDF_FONT_BOLD),
            ]
        table.setStyle(TableStyle(commands))
        return table

    @staticmethod
    def _paragraph(value: Any, style) -> Paragraph:
        return Paragraph(escape(ExportService._text(value)), style)

    @staticmethod
    def _duration(seconds: Any) -> str:
        try:
            total = int(float(seconds or 0))
        except (TypeError, ValueError):
            return NOT_AVAILABLE
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _status_counts(frame: pd.DataFrame, sensor: str) -> dict[str, int]:
        column = f"status_{sensor}"
        values = (
            frame[column].fillna("").astype(str).str.upper()
            if column in frame
            else pd.Series(dtype=str)
        )
        labels = {
            "INVALID": ("INVALID", "INVÁLID", "INVALIDA"),
            "STALE": ("STALE", "DESATUALIZAD"),
            "DISCONNECTED": ("DISCONNECTED", "DESCONECTAD"),
        }
        if values.empty:
            return dict.fromkeys(labels, 0)
        return {
            state: int(values.apply(lambda value: any(label in value for label in aliases)).sum())
            for state, aliases in labels.items()
        }

    def _schema_version(self) -> str:
        try:
            with self.tests.db.read_connection() as connection:
                row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            return str(row[0]) if row else NOT_AVAILABLE
        except Exception:
            return NOT_AVAILABLE

    def _cover(self, test, styles, issued: datetime):
        logo = Image(str(branding_path("ism_logo_horizontal_transparente.png")))
        ratio = logo.imageHeight / logo.imageWidth
        logo.drawWidth = 78 * mm
        logo.drawHeight = 78 * mm * ratio
        logo.hAlign = "CENTER"
        elements = [
            Spacer(1, 28 * mm),
            logo,
            Spacer(1, 12 * mm),
            Paragraph("RELATÓRIO FINAL DE ENSAIO", styles["ReportTitle"]),
            Spacer(1, 8 * mm),
        ]
        if bool(test["simulado"]):
            simulated = Table([["RELATÓRIO DEMONSTRATIVO - DADOS FICTÍCIOS"]], colWidths=[170 * mm])
            simulated.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF3CD")),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#8A5700")),
                        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(COLORS["warning"])),
                        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT_BOLD),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("PADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            elements.extend([simulated, Spacer(1, 8 * mm)])
        details = [
            ["Código do ensaio", test["codigo"]],
            ["Amostra", test["amostra_nome"]],
            ["Operador", test["operador"]],
            [
                "Período",
                f"{self._timestamp(test['inicio'])} a {self._timestamp(test['fim'])}",
            ],
            ["Situação", self._text(test["status"]).replace("_", " ").capitalize()],
            ["Data e hora de emissão", issued.strftime("%d/%m/%Y %H:%M:%S")],
        ]
        elements.extend([self._table(details, [45 * mm, 125 * mm]), PageBreak()])
        return elements

    def _identification(self, test, styles):
        rows = [
            [
                "Amostra",
                self._text(test["amostra_nome"]),
                "Gás utilizado",
                self._text(test["tipo_gas"]),
            ],
            [
                "Comprimento",
                self._number(test["comprimento_amostra_mm"], 2, "mm"),
                "Diâmetro",
                self._number(test["diametro_amostra_mm"], 2, "mm"),
            ],
            [
                "Massa",
                self._number(test["massa_amostra_g"], 2, "g"),
                "Volume geométrico",
                self._number(test["volume_geometrico_cm3"], 2, "cm³"),
            ],
            [
                "Temperatura",
                self._number(test["temperatura_c"], 1, "°C"),
                "Pressão atmosférica",
                self._number(test["pressao_atmosferica_kpa"], 3, "kPa"),
            ],
            [
                "Unidade de pressão",
                self._text(test["unidade_pressao"]),
                "Unidade de vazão",
                self._text(test["unidade_vazao"]),
            ],
        ]
        return KeepTogether(
            [
                Paragraph("1. Dados da amostra", styles["Section"]),
                self._table(rows, [34 * mm, 48 * mm, 36 * mm, 52 * mm]),
            ]
        )

    def _acquisition_summary(self, test, measurements, styles):
        total = len(measurements)
        rows = [
            [
                "Sensor",
                "Válidas / total",
                "Aproveitamento",
                "Primeira leitura",
                "Última leitura",
                "Inválidas",
                "Desatualizadas",
                "Desconectadas",
            ]
        ]
        for sensor, label in (("pressao", "Pressão"), ("vazao", "Vazão")):
            series = self.charts.validated_sensor_series(measurements, sensor)
            valid_series = series.dropna(subset=["value"])
            valid = len(self._valid_measurement_values(measurements, sensor))
            times = valid_series["timestamp"]
            counts = self._status_counts(measurements, sensor)
            rows.append(
                [
                    label,
                    f"{valid} / {total}",
                    f"{(100 * valid / total):.1f}%".replace(".", ",") if total else "0,0%",
                    self._timestamp(times.iloc[0]) if not times.empty else NOT_AVAILABLE,
                    self._timestamp(times.iloc[-1]) if not times.empty else NOT_AVAILABLE,
                    str(counts["INVALID"]),
                    str(counts["STALE"]),
                    str(counts["DISCONNECTED"]),
                ]
            )
        return [
            Paragraph("2. Resumo da aquisição", styles["Section"]),
            Paragraph(
                (
                    (
                        f"Tempo ativo de aquisição: {self._duration(test['duracao_segundos'])} · "
                        f"Tempo pausado: {self._duration(test['duracao_pausada_segundos'])} · "
                        f"Tempo total decorrido: {self._duration(test['duracao_decorrida_segundos'])} · "
                        if test["duracao_decorrida_segundos"] is not None
                        else f"Tempo decorrido legado: {self._duration(test['duracao_segundos'])} · "
                    )
                    + f"Medições combinadas: {total}"
                ),
                styles["BodyText"],
            ),
            Spacer(1, 2 * mm),
            self._table(
                rows,
                [14 * mm, 18 * mm, 18 * mm, 29 * mm, 29 * mm, 16 * mm, 25 * mm, 25 * mm],
                5.8,
                1,
            ),
        ]

    def _statistics(self, measurements, test, styles):
        stats = self.measurement_statistics(measurements, test)
        rows = [list(stats.columns)]
        for record in stats.to_dict(orient="records"):
            rows.append(
                [
                    record["Grandeza"],
                    self._number(record["Mínimo"], 3),
                    self._number(record["Média"], 3),
                    self._number(record["Máximo"], 3),
                    self._number(record["Desvio padrão"], 3),
                    str(record["N válido"]),
                    record["Unidade"],
                ]
            )
        return [
            Paragraph("3. Resumo estatístico", styles["Section"]),
            self._table(
                rows,
                [30 * mm, 22 * mm, 22 * mm, 22 * mm, 29 * mm, 21 * mm, 28 * mm],
                7,
                1,
            ),
        ]

    @staticmethod
    def _chart_elements(
        title,
        chart,
        styles,
        height_mm: float = 70,
        missing_message: str = INSUFFICIENT_DATA_MESSAGE,
    ):
        if chart is None:
            body = Paragraph(missing_message, styles["Notice"])
        else:
            body = Image(chart.image)
            scale = min(170 * mm / body.imageWidth, height_mm * mm / body.imageHeight)
            body.drawWidth = body.imageWidth * scale
            body.drawHeight = body.imageHeight * scale
            body.hAlign = "CENTER"
        return [Paragraph(title, styles["Subsection"]), body, Spacer(1, 2 * mm)]

    @staticmethod
    def _first(mapping: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = mapping.get(key)
            if value is not None:
                return value
        return None

    def _calculation_elements(self, calculations, styles):
        elements = [Paragraph("5. Resultados de permeabilidade", styles["Section"])]
        records = self.charts.calculation_records(calculations)
        permeability = [
            record
            for record in records
            if "klinkenberg" not in str(record.get("tipo") or "").casefold()
            and self._first(record["results"], "permeability_md") is not None
        ]
        if not permeability:
            elements.append(
                Paragraph("Nenhum cálculo foi salvo para este ensaio.", styles["Notice"])
            )
        else:
            parsed_times = [
                pd.to_datetime(item.get("timestamp"), errors="coerce") for item in permeability
            ]
            days = {item.date() for item in parsed_times if pd.notna(item)}
            time_only = len(days) <= 1
            rows = [
                [
                    "Ponto",
                    "Captura",
                    "Pressão média absoluta (kPa)",
                    "Vazão do cálculo",
                    "Queda de pressão (kPa)",
                    "Permeabilidade aparente (mD)",
                ]
            ]
            for index, record in enumerate(permeability, 1):
                inputs, results = record["inputs"], record["results"]
                flow = self._first(inputs, "flow_value", "flow_nl_min", "flow_l_min", "flow_used")
                flow_unit = (
                    str(inputs["flow_unit"])
                    if inputs.get("flow_unit")
                    else "NL/min"
                    if inputs.get("flow_nl_min") is not None
                    else str((inputs.get("units") or {}).get("flow") or "L/min")
                )
                rows.append(
                    [
                        str(index),
                        self._timestamp(record.get("timestamp"), time_only=time_only),
                        self._number(self._first(results, "mean_pressure_kpa_abs"), 3),
                        self._number(flow, 3, flow_unit),
                        self._number(self._first(results, "pressure_drop_kpa"), 3),
                        self._number(self._first(results, "permeability_md"), 3),
                    ]
                )
            elements.append(
                self._table(
                    rows,
                    [13 * mm, 29 * mm, 38 * mm, 29 * mm, 30 * mm, 35 * mm],
                    6.4,
                    1,
                )
            )
            for index, record in enumerate(permeability, 1):
                inputs = record["inputs"]
                if inputs.get("flow_unit") == "NL/min":
                    reference = self._number(inputs.get("flow_reference_pressure_kpa_abs"), 3)
                    temperature = self._number(inputs.get("flow_reference_temperature_c"), 2)
                    elements.append(
                        Paragraph(
                            f"Ponto {index}: vazão normal referida a {reference} kPa abs e "
                            f"{temperature} °C; temperatura do ensaio "
                            f"{self._number(inputs.get('temperatura_c'), 2)} °C.",
                            styles["BodyText"],
                        )
                    )

        elements.append(Paragraph("5.1 Resultado do ajuste de Klinkenberg", styles["Subsection"]))
        valid_fit = None
        for record in reversed(records):
            if "klinkenberg" not in str(record.get("tipo") or "").casefold():
                continue
            result = record["results"]
            count = self._first(result, "points", "point_count")
            if count is None:
                count = len(self.charts.klinkenberg_points(record))
            values = (
                self._first(result, "intrinsic_permeability_md", "k_infinity_md", "intercept_md"),
                self._first(result, "slip_factor_kpa"),
                self._first(result, "r_squared"),
                count,
            )
            if int(count or 0) >= 2 and all(self.charts._finite(value) for value in values[:3]):
                valid_fit = values
                break
        if valid_fit is None:
            elements.append(
                Paragraph(
                    "Dados insuficientes para calcular o ajuste de Klinkenberg.",
                    styles["Notice"],
                )
            )
        else:
            intrinsic, slip, r_squared, count = valid_fit
            elements.append(
                self._table(
                    [
                        ["Permeabilidade intrínseca k∞", self._number(intrinsic, 3, "mD")],
                        ["Fator de deslizamento b", self._number(slip, 3, "kPa")],
                        ["Coeficiente R²", self._number(r_squared, 5)],
                        ["Pontos utilizados", str(int(count))],
                    ],
                    [75 * mm, 95 * mm],
                    8,
                )
            )
        return elements

    @staticmethod
    def _description_chunks(value: Any, limit: int = 600) -> list[str]:
        text = ExportService._text(value)
        return [text[index : index + limit] for index in range(0, len(text), limit)] or [
            NOT_AVAILABLE
        ]

    def _events(self, alarms, markers, styles):
        elements = [Paragraph("7. Ocorrências e registros do operador", styles["Section"])]
        records: list[tuple[Any, str, Any]] = []
        for record in alarms.to_dict(orient="records"):
            sensor = str(record.get("sensor") or "").casefold()
            kind = (
                "Alarme - Pressão"
                if "press" in sensor
                else "Alarme - Vazão"
                if "vaz" in sensor
                else "Alarme"
            )
            description = record.get("mensagem") or record.get("categoria")
            if record.get("observacao_operador"):
                description = (
                    f"{self._text(description)} — {self._text(record['observacao_operador'])}"
                )
            records.append((record.get("timestamp"), kind, description))
        for record in markers.to_dict(orient="records"):
            category = str(record.get("categoria") or "").casefold()
            kind = "Encerramento" if "encerr" in category else "Operação"
            records.append((record.get("timestamp"), kind, record.get("comentario")))
        records.sort(key=lambda item: str(item[0] or ""))
        if not records:
            elements.append(Paragraph("Nenhuma ocorrência registrada.", styles["BodyText"]))
            return elements
        rows = [["Horário", "Tipo", "Descrição"]]
        for timestamp, kind, description in records:
            chunks = self._description_chunks(description)
            for index, chunk in enumerate(chunks):
                rows.append(
                    [
                        self._timestamp(timestamp) if index == 0 else "continuação",
                        kind if index == 0 else "continuação",
                        chunk,
                    ]
                )
        elements.append(self._table(rows, [38 * mm, 35 * mm, 101 * mm], 7, 1))
        return elements

    def export_pdf(self, test_id: int, directory: Path) -> Path:
        test, measurements, alarms, markers, calculations = self._data(test_id)
        measurements = self._current_measurements(measurements)
        target = self._safe_target(directory, f"{test['codigo']}_relatorio_final.pdf")
        styles = self._styles()
        issued = datetime.now()
        charts = self.charts.generate_all(
            measurements,
            calculations,
            test["unidade_pressao"] or "psi",
            test["unidade_vazao"] or "não registrada",
        )
        story = self._cover(test, styles, issued)
        story.extend([self._identification(test, styles), Spacer(1, 4 * mm)])
        story.extend(self._acquisition_summary(test, measurements, styles))
        story.extend(self._statistics(measurements, test, styles))
        story.append(CondPageBreak(90 * mm))
        story.append(Paragraph("4. Gráficos de processo", styles["Section"]))
        for key, title in (
            ("pressao_tempo", "4.1 Pressão × tempo"),
            ("vazao_tempo", "4.2 Vazão × tempo"),
            ("pressao_vazao_tempo", "4.3 Pressão e vazão no mesmo período"),
            ("vazao_pressao", "4.4 Relação entre vazão e pressão"),
        ):
            story.extend(self._chart_elements(title, charts[key], styles, 72))
        story.append(CondPageBreak(70 * mm))
        story.extend(self._calculation_elements(calculations, styles))
        story.append(CondPageBreak(90 * mm))
        story.append(Paragraph("6. Análise da permeabilidade", styles["Section"]))
        for key, title in (
            ("permeabilidade_tempo", "6.1 Evolução da permeabilidade aparente"),
            (
                "permeabilidade_pressao",
                "6.2 Permeabilidade em função da pressão média absoluta",
            ),
            ("klinkenberg", "6.3 Ajuste de Klinkenberg"),
        ):
            missing = (
                "Dados insuficientes para calcular o ajuste de Klinkenberg."
                if key == "klinkenberg"
                else INSUFFICIENT_DATA_MESSAGE
            )
            story.extend(self._chart_elements(title, charts[key], styles, 72, missing))
        story.extend(self._events(alarms, markers, styles))
        notes = test["observacao_final"] or test["observacoes"] or "Sem observações finais."
        story.extend(
            [
                Paragraph("8. Observações finais", styles["Section"]),
                Paragraph(escape(self._text(notes)), styles["BodyText"]),
                Spacer(1, 6 * mm),
                Paragraph(
                    "Responsável: ________________________________________________",
                    styles["BodyText"],
                ),
            ]
        )
        firmware = self._text(test["versao_firmware"])
        if firmware == NOT_AVAILABLE:
            firmware = "não disponível"
        footer = f"Aplicativo {APP_VERSION} · Firmware {firmware} · Schema {self._schema_version()}"
        doc = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=17 * mm,
            bottomMargin=17 * mm,
            title=f"Relatório {test['codigo']}",
            author="Supervisório ISM – Permeabilímetro",
        )
        canvas_maker = partial(
            NumberedCanvas,
            header=f"Supervisório ISM - Permeabilímetro | {test['codigo']}",
            footer=footer,
            issued=f"Emissão: {issued:%d/%m/%Y %H:%M:%S}",
        )
        doc.build(story, canvasmaker=canvas_maker)
        return target
