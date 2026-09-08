from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from database.repositories import CalculationRepository, EventRepository, TestRepository


class ExportService:
    def __init__(self, tests: TestRepository, events: EventRepository):
        self.tests = tests
        self.events = events
        self.calculations = CalculationRepository(tests.db)

    def _data(self, test_id: int) -> tuple[Any, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
            return "—"
        try:
            formatted = f"{float(value):.6g}"
        except (TypeError, ValueError):
            return str(value)
        return f"{formatted} {unit}".strip()

    @staticmethod
    def _current_measurements(measurements: pd.DataFrame) -> pd.DataFrame:
        """Apresenta somente o hardware atual, sem expor colunas legadas."""
        legacy = ["vazao_alta_ma", "vazao_alta", "flow_meter_ativo"]
        current = measurements.drop(
            columns=[column for column in legacy if column in measurements],
            errors="ignore",
        ).copy()
        return current.rename(columns={
            "vazao_baixa_ma": "vazao_ma",
            "vazao_baixa": "vazao",
        })

    def export_csv(self, test_id: int, directory: Path, separator: str = ";") -> Path:
        test, measurements, _, _, _ = self._data(test_id)
        target = self._safe_target(directory, f"{test['codigo']}_medicoes.csv")
        columns = {
            "timestamp_computador": "Data e hora",
            "timestamp_esp32": "Timestamp ESP32 (ms)",
            "pressao_ma": "Pressão (mA)",
            "pressao": f"Pressão ({test['unidade_pressao']})",
            "vazao_baixa": f"Vazão ({test['unidade_vazao']})",
            "qualidade": "Qualidade",
        }
        selected = measurements[[c for c in columns if c in measurements.columns]].rename(columns=columns)
        selected.to_csv(target, sep=separator, index=False, encoding="utf-8-sig")
        return target

    def export_json(self, test_id: int, directory: Path) -> Path:
        test, measurements, alarms, markers, calculations = self._data(test_id)
        target = self._safe_target(directory, f"{test['codigo']}.json")
        measurements = self._current_measurements(measurements)
        payload = {
            "ensaio": dict(test),
            "medicoes": measurements.to_dict(orient="records"),
            "alarmes": alarms.to_dict(orient="records"),
            "marcacoes": markers.to_dict(orient="records"),
            "calculos": calculations.to_dict(orient="records"),
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def export_xlsx(self, test_id: int, directory: Path) -> Path:
        test, measurements, alarms, markers, calculations = self._data(test_id)
        target = self._safe_target(directory, f"{test['codigo']}.xlsx")
        summary = pd.DataFrame([dict(test)])
        measurements = self._current_measurements(measurements)
        numeric = [c for c in ("pressao", "vazao") if c in measurements]
        stats = measurements[numeric].describe().T.reset_index() if numeric else pd.DataFrame()
        with pd.ExcelWriter(target, engine="openpyxl") as writer:
            summary.to_excel(writer, sheet_name="Resumo", index=False)
            if not stats.empty:
                stats.to_excel(writer, sheet_name="Resumo", index=False, startrow=4)
            measurements.to_excel(writer, sheet_name="Medições", index=False)
            alarms.to_excel(writer, sheet_name="Alarmes", index=False)
            markers.to_excel(writer, sheet_name="Marcações", index=False)
            calculations.to_excel(writer, sheet_name="Cálculos", index=False)
            pd.DataFrame(columns=["sensor", "data", "ganho", "offset"]).to_excel(
                writer, sheet_name="Calibração", index=False
            )
        return target

    def export_pdf(self, test_id: int, directory: Path) -> Path:
        test, measurements, alarms, markers, calculations = self._data(test_id)
        target = self._safe_target(directory, f"{test['codigo']}_relatorio_final.pdf")
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(
            str(target), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
            topMargin=16 * mm, bottomMargin=16 * mm,
        )
        story = [
            Paragraph("Relatório Final de Ensaio — Porosímetro", styles["Title"]),
            Spacer(1, 8 * mm),
        ]
        details = [
            ["Código", test["codigo"], "Status", test["status"]],
            ["Amostra", test["amostra_nome"], "Operador", test["operador"]],
            ["Início", test["inicio"], "Fim", test["fim"] or "—"],
            ["Amostras", str(test["quantidade_amostras"]), "Duração (s)", f"{test['duracao_segundos']:.1f}"],
            ["Gás", test["tipo_gas"] or "—", "Temperatura", f"{test['temperatura_c'] or 0:.2f} °C"],
            ["L / D", f"{test['comprimento_amostra_mm'] or '—'} / {test['diametro_amostra_mm'] or '—'} mm", "Massa", f"{test['massa_amostra_g'] or '—'} g"],
        ]
        table = Table(details, colWidths=[28 * mm, 58 * mm, 28 * mm, 58 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F6F8")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E0E5")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([table, Spacer(1, 7 * mm), Paragraph("Resumo estatístico", styles["Heading2"])])
        stat_rows = [["Variável", "Mínimo", "Média", "Máximo", "Desvio padrão"]]
        for column, label in [("pressao", "Pressão"), ("vazao_baixa", "Vazão")]:
            if column in measurements and not measurements[column].dropna().empty:
                series = measurements[column].dropna()
                stat_rows.append([
                    label, f"{series.min():.3f}", f"{series.mean():.3f}",
                    f"{series.max():.3f}", f"{series.std(ddof=0):.3f}",
                ])
        stats_table = Table(stat_rows, repeatRows=1)
        stats_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F5D73")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E0E5")),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([stats_table, Spacer(1, 7 * mm)])
        if not calculations.empty:
            story.append(Paragraph("Resultados de porosimetria e permeabilidade", styles["Heading2"]))
            calculation_rows = [["Tipo", "Resultado principal"]]
            for _, calculation in calculations.iterrows():
                result = json.loads(calculation["resultados_json"])
                if calculation["tipo"] == "Lei de Boyle":
                    principal = (
                        f"Porosidade aberta: {self._format_result(result.get('porosity_mean_percent'), '%')}; "
                        f"volume de poros: {self._format_result(result.get('pore_volume_mean_cm3'), 'cm³')}; "
                        f"volume esquelético: {self._format_result(result.get('skeletal_volume_mean_cm3'), 'cm³')}; "
                        f"densidade esquelética: {self._format_result(result.get('skeletal_density_g_cm3'), 'g/cm³')}; "
                        f"CV: {self._format_result(result.get('coefficient_variation_percent'), '%')}; "
                        f"ciclos: {result.get('valid_cycles', '—')}"
                    )
                elif calculation["tipo"] == "Permeabilidade a gás":
                    principal = f"k={self._format_result(result.get('permeability_md'), 'mD')}"
                else:
                    principal = f"k∞={self._format_result(result.get('intrinsic_permeability_md'), 'mD')}"
                calculation_rows.append([
                    calculation["tipo"],
                    Paragraph(escape(principal), styles["BodyText"]),
                ])
            calculation_table = Table(calculation_rows, repeatRows=1, colWidths=[55 * mm, 110 * mm])
            calculation_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F5D73")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E0E5")),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([calculation_table, Spacer(1, 7 * mm)])
        else:
            story.extend([
                Paragraph("Resultados de porosimetria e permeabilidade", styles["Heading2"]),
                Paragraph("Nenhum cálculo foi salvo para este ensaio.", styles["BodyText"]),
                Spacer(1, 7 * mm),
            ])
        story.extend([
            Paragraph(f"Alarmes registrados: {len(alarms)}", styles["Heading3"]),
            Paragraph(f"Marcações do operador: {len(markers)}", styles["Heading3"]),
            Spacer(1, 15 * mm),
            Paragraph("Observações", styles["Heading2"]),
            Paragraph(
                escape(test["observacao_final"] or test["observacoes"] or "Sem observações."),
                styles["BodyText"],
            ),
            Spacer(1, 25 * mm),
            Paragraph("Assinatura: _________________________________________________", styles["BodyText"]),
        ])
        doc.build(story)
        return target
