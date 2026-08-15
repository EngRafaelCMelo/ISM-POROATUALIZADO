from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as ReportImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.utils import ImageReader

from database.repositories import CalculationRepository, EventRepository, TestRepository
from ui.resources import branding_path


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

    def export_csv(self, test_id: int, directory: Path, separator: str = ";") -> Path:
        test, measurements, _, _, _ = self._data(test_id)
        target = self._safe_target(directory, f"{test['codigo']}_medicoes.csv")
        columns = {
            "timestamp_computador": "Data e hora",
            "timestamp_esp32": "Timestamp ESP32 (ms)",
            "pressao_ma": "Pressão (mA)",
            "pressao": f"Pressão ({test['unidade_pressao']})",
            "pressao_valida": "Pressão válida",
            "vazao_raw": "Registro bruto de vazão",
            "vazao": f"Vazão ({test['unidade_vazao']})",
            "vazao_valida": "Vazão válida",
            "sequencia": "Sequência",
            "versao_firmware": "Versão do firmware",
            "simulado": "Simulado",
            "qualidade": "Qualidade",
        }
        selected = measurements[[c for c in columns if c in measurements.columns]].rename(columns=columns)
        selected.to_csv(target, sep=separator, index=False, encoding="utf-8-sig")
        return target

    def export_json(self, test_id: int, directory: Path) -> Path:
        test, measurements, alarms, markers, calculations = self._data(test_id)
        target = self._safe_target(directory, f"{test['codigo']}.json")
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
        target = self._safe_target(directory, f"{test['codigo']}_resumo.pdf")
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(
            str(target), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
            topMargin=16 * mm, bottomMargin=16 * mm,
        )
        logo_path = branding_path("ism_logo_horizontal.png")
        logo_width_px, logo_height_px = ImageReader(str(logo_path)).getSize()
        logo_width = 58 * mm
        logo = ReportImage(str(logo_path), width=logo_width, height=logo_width * logo_height_px / logo_width_px)
        header = Table([[logo, Paragraph("Relatório de Ensaio — Porosímetro", styles["Title"])]], colWidths=[64 * mm, 101 * mm])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
        story = [header, Spacer(1, 7 * mm)]
        if test["simulado"]:
            story.extend([Paragraph("RELATÓRIO DE DADOS SIMULADOS", styles["Heading1"]), Spacer(1, 4 * mm)])
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
        for column, label in [
            ("pressao", "Pressão"), ("vazao", "Vazão")
        ]:
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
                        f"Vesq={result.get('skeletal_volume_mean_cm3', 0):.6g} cm³; "
                        f"porosidade={result.get('porosity_mean_percent', 0):.6g}%"
                    )
                elif calculation["tipo"] == "Permeabilidade a gás":
                    principal = f"k={result.get('permeability_md', 0):.6g} mD"
                else:
                    principal = f"k∞={result.get('intrinsic_permeability_md', 0):.6g} mD"
                calculation_rows.append([calculation["tipo"], principal])
            calculation_table = Table(calculation_rows, repeatRows=1, colWidths=[55 * mm, 110 * mm])
            calculation_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F5D73")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E0E5")),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([calculation_table, Spacer(1, 7 * mm)])
        story.extend([
            Paragraph(f"Alarmes registrados: {len(alarms)}", styles["Heading3"]),
            Paragraph(f"Marcações do operador: {len(markers)}", styles["Heading3"]),
            Spacer(1, 15 * mm),
            Paragraph("Observações", styles["Heading2"]),
            Paragraph(test["observacao_final"] or test["observacoes"] or "Sem observações.", styles["BodyText"]),
            Spacer(1, 25 * mm),
            Paragraph("Assinatura: _________________________________________________", styles["BodyText"]),
        ])
        doc.build(story)
        return target
