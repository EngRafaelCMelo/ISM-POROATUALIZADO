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
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
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
from ui.theme import COLORS


class NumberedCanvas(canvas.Canvas):
    """Adiciona cabeçalho e Página X de Y sem gerar o documento duas vezes."""

    def __init__(self, *args, header: str, footer: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []
        self._header = header
        self._footer = footer

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
        self.setFont("Helvetica", 7.5)
        self.line(16 * mm, height - 12 * mm, width - 16 * mm, height - 12 * mm)
        self.drawString(16 * mm, height - 9.5 * mm, self._header)
        self.line(16 * mm, 12 * mm, width - 16 * mm, 12 * mm)
        self.drawString(16 * mm, 8.5 * mm, self._footer)
        self.drawRightString(width - 16 * mm, 8.5 * mm, f"Página {self._pageNumber} de {total}")
        self.restoreState()


class ExportService:
    def __init__(self, tests: TestRepository, events: EventRepository):
        self.tests = tests
        self.events = events
        self.calculations = CalculationRepository(tests.db)
        self.charts = ChartService()

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
        if value is None:
            return "não disponível"
        if isinstance(value, (dict, list, tuple)):
            try:
                return json.dumps(value, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError):
                return "não disponível"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        if not math.isfinite(numeric):
            return "não disponível"
        formatted = f"{numeric:.6g}"
        return f"{formatted} {unit}".strip()

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
            "vazao": f"Vazão ({test['unidade_vazao']})",
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
            values = self.charts.validated_sensor_series(measurements, sensor)["value"].dropna()
            rows.append(
                {
                    "Grandeza": label,
                    "Mínimo": values.min() if not values.empty else None,
                    "Média": values.mean() if not values.empty else None,
                    "Mediana": values.median() if not values.empty else None,
                    "Máximo": values.max() if not values.empty else None,
                    "Desvio padrão": values.std(ddof=0) if not values.empty else None,
                    "N válido": len(values),
                    "Unidade": unit,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _styles():
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                "ReportTitle",
                parent=styles["Title"],
                textColor=colors.HexColor(COLORS["primary"]),
                fontSize=22,
                leading=27,
                alignment=TA_CENTER,
                spaceAfter=10 * mm,
            )
        )
        styles.add(
            ParagraphStyle(
                "Section",
                parent=styles["Heading2"],
                textColor=colors.HexColor(COLORS["primary"]),
                fontSize=13,
                leading=16,
                keepWithNext=True,
                spaceBefore=5 * mm,
                spaceAfter=2.5 * mm,
            )
        )
        styles.add(
            ParagraphStyle(
                "Subsection",
                parent=styles["Heading3"],
                textColor=colors.HexColor(COLORS["text"]),
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
        table = Table(rows, colWidths=widths, repeatRows=repeat_rows, hAlign="LEFT")
        commands = [
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor(COLORS["border"])),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 4),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ]
        if repeat_rows:
            commands += [
                ("BACKGROUND", (0, 0), (-1, repeat_rows - 1), colors.HexColor(COLORS["primary"])),
                ("TEXTCOLOR", (0, 0), (-1, repeat_rows - 1), colors.white),
                ("FONTNAME", (0, 0), (-1, repeat_rows - 1), "Helvetica-Bold"),
            ]
        else:
            commands += [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F6F8")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ]
        table.setStyle(TableStyle(commands))
        return table

    @staticmethod
    def _paragraph(value: Any, style) -> Paragraph:
        return Paragraph(escape("não disponível" if value is None else str(value)), style)

    @staticmethod
    def _duration(seconds: Any) -> str:
        try:
            total = int(float(seconds or 0))
        except (TypeError, ValueError):
            return "não disponível"
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
        return {
            state: int(values.str.contains(state, regex=False).sum())
            for state in ("INVALID", "STALE", "DISCONNECTED")
        }

    def _schema_version(self) -> str:
        try:
            with self.tests.db.read_connection() as connection:
                row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            return str(row[0]) if row else "não disponível"
        except Exception:
            return "não disponível"

    def _cover(self, test, styles, issued: datetime):
        elements = [
            Spacer(1, 20 * mm),
            Paragraph("Supervisório ISM – Permeabilímetro", styles["ReportTitle"]),
            Paragraph("RELATÓRIO FINAL DE ENSAIO", styles["Heading2"]),
            Spacer(1, 12 * mm),
        ]
        if bool(test["simulado"]):
            simulated = Table(
                [["ENSAIO SIMULADO — DADOS NÃO PROVENIENTES DO EQUIPAMENTO"]], colWidths=[170 * mm]
            )
            simulated.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF3CD")),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#8A5700")),
                        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(COLORS["warning"])),
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
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
            ["Início", test["inicio"]],
            ["Término", test["fim"] or "não disponível"],
            ["Status", test["status"] or "não disponível"],
            ["Emissão", issued.strftime("%d/%m/%Y %H:%M:%S")],
        ]
        elements.extend([self._table(details, [45 * mm, 125 * mm]), PageBreak()])
        return elements

    def _identification(self, test, styles):
        rows = [
            [
                "Comprimento",
                self._format_result(test["comprimento_amostra_mm"], "mm"),
                "Diâmetro",
                self._format_result(test["diametro_amostra_mm"], "mm"),
            ],
            [
                "Massa",
                self._format_result(test["massa_amostra_g"], "g"),
                "Volume geométrico",
                self._format_result(test["volume_geometrico_cm3"], "cm³"),
            ],
            [
                "Gás",
                test["tipo_gas"] or "não disponível",
                "Temperatura",
                self._format_result(test["temperatura_c"], "°C"),
            ],
            [
                "Referência de pressão",
                test["referencia_pressao"] or "não disponível",
                "Pressão atmosférica",
                self._format_result(test["pressao_atmosferica_kpa"], "kPa"),
            ],
            [
                "Unidade de pressão",
                test["unidade_pressao"] or "não disponível",
                "Unidade de vazão",
                test["unidade_vazao"] or "não disponível",
            ],
        ]
        return KeepTogether(
            [
                Paragraph("1. Identificação e geometria da amostra", styles["Section"]),
                self._table(rows, [34 * mm, 48 * mm, 36 * mm, 52 * mm]),
            ]
        )

    def _acquisition_summary(self, test, measurements, styles):
        total = len(measurements)
        rows = [
            [
                "Sensor",
                "Válidas / total",
                "% válida",
                "Primeira leitura",
                "Última leitura",
                "Inv./stale/desc.",
            ]
        ]
        for sensor, label in (("pressao", "Pressão"), ("vazao", "Vazão")):
            series = self.charts.validated_sensor_series(measurements, sensor)
            valid_series = series.dropna(subset=["value"])
            valid = len(valid_series)
            times = valid_series["timestamp"]
            counts = self._status_counts(measurements, sensor)
            rows.append(
                [
                    label,
                    f"{valid} / {total}",
                    f"{(100 * valid / total):.1f}%" if total else "0,0%",
                    times.iloc[0].strftime("%d/%m/%Y %H:%M:%S")
                    if not times.empty
                    else "não disponível",
                    times.iloc[-1].strftime("%d/%m/%Y %H:%M:%S")
                    if not times.empty
                    else "não disponível",
                    f"{counts['INVALID']} / {counts['STALE']} / {counts['DISCONNECTED']}",
                ]
            )
        return [
            Paragraph("2. Resumo da aquisição", styles["Section"]),
            Paragraph(
                f"Duração: {self._duration(test['duracao_segundos'])} · Amostras combinadas: {total}",
                styles["BodyText"],
            ),
            Spacer(1, 2 * mm),
            self._table(rows, [18 * mm, 24 * mm, 16 * mm, 42 * mm, 42 * mm, 28 * mm], 6.5, 1),
        ]

    def _statistics(self, measurements, test, styles):
        stats = self.measurement_statistics(measurements, test)
        rows = [list(stats.columns)]
        for record in stats.to_dict(orient="records"):
            rows.append(
                [
                    record["Grandeza"],
                    self._format_result(record["Mínimo"]),
                    self._format_result(record["Média"]),
                    self._format_result(record["Mediana"]),
                    self._format_result(record["Máximo"]),
                    self._format_result(record["Desvio padrão"]),
                    str(record["N válido"]),
                    record["Unidade"],
                ]
            )
        return [
            Paragraph("3. Resumo estatístico", styles["Section"]),
            self._table(
                rows, [25 * mm, 19 * mm, 19 * mm, 19 * mm, 19 * mm, 24 * mm, 17 * mm, 20 * mm], 7, 1
            ),
        ]

    @staticmethod
    def _chart_elements(title, chart, styles):
        body = (
            Image(chart.image, width=170 * mm, height=84 * mm)
            if chart is not None
            else Paragraph(INSUFFICIENT_DATA_MESSAGE, styles["Notice"])
        )
        return KeepTogether([Paragraph(title, styles["Subsection"]), body, Spacer(1, 3 * mm)])

    def _calculation_elements(self, calculations, styles):
        elements = [Paragraph("5. Resultados de permeabilidade", styles["Section"])]
        records = self.charts.calculation_records(calculations)
        if not records:
            elements.append(
                Paragraph("Nenhum cálculo foi salvo para este ensaio.", styles["Notice"])
            )
            return elements
        fields = {
            "permeability_m2": "Permeabilidade (m²)",
            "permeability_darcy": "Permeabilidade (Darcy)",
            "permeability_md": "Permeabilidade aparente (mD)",
            "pressure_drop_kpa": "Queda de pressão (kPa)",
            "mean_pressure_kpa_abs": "Pressão média absoluta (kPa abs)",
            "superficial_velocity_m_s": "Velocidade superficial (m/s)",
            "pressure_gradient_pa_m": "Gradiente de pressão (Pa/m)",
            "intrinsic_permeability_md": "k∞ (mD)",
            "slip_factor_kpa": "Fator de deslizamento (kPa)",
            "slope_md_kpa": "Inclinação (mD·kPa)",
            "r_squared": "R²",
            "points": "Quantidade de pontos",
        }
        for index, record in enumerate(records, 1):
            inputs, results = record["inputs"], record["results"]
            result_rows = [["Campo", "Valor"]] + [
                [label, self._format_result(results.get(key))]
                for key, label in fields.items()
                if key in results
            ]
            if len(result_rows) == 1:
                result_rows.append(["Resultado", "não disponível (registro legado)"])
            input_rows = [["Entrada", "Valor"]]
            for key, value in self._flatten_mapping(inputs):
                if key == "points" or key.startswith("points."):
                    continue
                input_rows.append(
                    [
                        self._paragraph(key, styles["BodyText"]),
                        self._paragraph(self._format_result(value), styles["BodyText"]),
                    ]
                )
            if len(input_rows) == 1:
                input_rows.append(["Entradas", "não disponível"])
            block = [
                Paragraph(
                    f"5.{index} {escape(str(record.get('tipo') or 'Cálculo'))}",
                    styles["Subsection"],
                ),
                Paragraph(
                    f"Timestamp: {escape(str(record.get('timestamp') or 'não disponível'))}",
                    styles["BodyText"],
                ),
                Paragraph(
                    f"Método/fórmula: {escape(str(inputs.get('formula') or 'não disponível'))}",
                    styles["BodyText"],
                ),
                self._table(input_rows, [62 * mm, 108 * mm], 7.5, 1),
                self._table(result_rows, [72 * mm, 98 * mm], 7.5, 1),
                Paragraph(
                    f"Observações: {escape(str(record.get('observacoes') or '—'))}",
                    styles["BodyText"],
                ),
                Spacer(1, 3 * mm),
            ]
            elements.extend(block)
        return elements

    @classmethod
    def _flatten_mapping(cls, value: Any, prefix: str = "") -> list[tuple[str, Any]]:
        rows: list[tuple[str, Any]] = []
        if isinstance(value, dict):
            for key, child in value.items():
                name = f"{prefix}.{key}" if prefix else str(key)
                rows.extend(cls._flatten_mapping(child, name))
        elif isinstance(value, (list, tuple)):
            rows.append((prefix, f"{len(value)} item(ns)"))
        else:
            rows.append((prefix, value))
        return rows

    def _events(self, alarms, markers, styles):
        elements = [Paragraph("7. Alarmes", styles["Section"])]
        if alarms.empty:
            elements.append(Paragraph("Nenhum alarme registrado.", styles["BodyText"]))
        else:
            rows = [["Timestamp", "Sensor", "Severidade", "Mensagem", "Valor", "Reconhecido"]]
            for record in alarms.to_dict(orient="records"):
                rows.append(
                    [
                        str(record.get("timestamp") or "—"),
                        str(record.get("sensor") or "—"),
                        str(record.get("severidade") or "—"),
                        self._paragraph(record.get("mensagem") or "—", styles["BodyText"]),
                        self._format_result(record.get("valor_medido")),
                        "Sim" if record.get("reconhecido") else "Não",
                    ]
                )
            elements.append(
                self._table(rows, [31 * mm, 18 * mm, 19 * mm, 65 * mm, 18 * mm, 19 * mm], 6.5, 1)
            )
        elements.append(Paragraph("8. Marcações do operador", styles["Section"]))
        if markers.empty:
            elements.append(Paragraph("Nenhuma marcação registrada.", styles["BodyText"]))
        else:
            rows = [["Timestamp", "Categoria", "Comentário"]]
            for record in markers.to_dict(orient="records"):
                rows.append(
                    [
                        str(record.get("timestamp") or "—"),
                        str(record.get("categoria") or "—"),
                        self._paragraph(record.get("comentario") or "—", styles["BodyText"]),
                    ]
                )
            elements.append(self._table(rows, [42 * mm, 35 * mm, 93 * mm], 7, 1))
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
            test["unidade_vazao"] or "NL/min",
        )
        story = self._cover(test, styles, issued)
        story.extend([self._identification(test, styles), Spacer(1, 4 * mm)])
        story.extend(self._acquisition_summary(test, measurements, styles))
        story.extend(self._statistics(measurements, test, styles))
        story.append(Paragraph("4. Gráficos de processo", styles["Section"]))
        for key, title in (
            ("pressao_tempo", "4.1 Pressão × tempo"),
            ("vazao_tempo", "4.2 Vazão × tempo"),
            ("pressao_vazao_tempo", "4.3 Pressão e vazão × tempo"),
            ("vazao_pressao", "4.4 Vazão × pressão (pares sincronizados)"),
        ):
            story.append(self._chart_elements(title, charts[key], styles))
        story.extend(self._calculation_elements(calculations, styles))
        story.append(Paragraph("6. Gráficos de permeabilidade e Klinkenberg", styles["Section"]))
        for key, title in (
            ("permeabilidade_tempo", "6.1 Permeabilidade aparente × tempo"),
            ("permeabilidade_pressao", "6.2 Permeabilidade aparente × pressão média absoluta"),
            ("klinkenberg", "6.3 Klinkenberg"),
        ):
            story.append(self._chart_elements(title, charts[key], styles))
        story.extend(self._events(alarms, markers, styles))
        notes = test["observacao_final"] or test["observacoes"] or "Sem observações finais."
        story.extend(
            [
                Paragraph("9. Observações finais e assinatura", styles["Section"]),
                Paragraph(escape(str(notes)), styles["BodyText"]),
                Spacer(1, 18 * mm),
                Paragraph(
                    "Assinatura: _________________________________________________",
                    styles["BodyText"],
                ),
            ]
        )
        footer = f"Emitido em {issued:%d/%m/%Y %H:%M:%S} · App {APP_VERSION} · Firmware {test['versao_firmware'] or 'não disponível'} · Schema {self._schema_version()}"
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
            header=f"Supervisório ISM – Permeabilímetro · {test['codigo']}",
            footer=footer,
        )
        doc.build(story, canvasmaker=canvas_maker)
        return target
