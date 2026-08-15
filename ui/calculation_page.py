from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.models import Measurement, TestDefinition
from core.porosimetry import (
    GAS_PROPERTIES,
    absolute_pressure_kpa,
    calculate_boyle_cycle,
    calculate_gas_permeability,
    calculate_klinkenberg,
    cylindrical_volume_cm3,
    summarize_boyle_cycles,
)


def number_field(
    minimum: float = 0.0,
    maximum: float = 1_000_000.0,
    decimals: int = 5,
    suffix: str = "",
) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setRange(minimum, maximum)
    field.setDecimals(decimals)
    field.setSuffix(f" {suffix}" if suffix else "")
    return field


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(15, 13, 15, 13)
    return frame, layout


class CalculationPage(QWidget):
    save_requested = Signal(str, object, object, str)

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.config = config
        self.current_measurement: Measurement | None = None
        self.definition: TestDefinition | None = None
        self.last_boyle: tuple[dict, dict] | None = None
        self.last_permeability: tuple[dict, dict] | None = None
        self.last_klinkenberg: tuple[dict, dict] | None = None

        root = QVBoxLayout(self)
        title = QLabel("Cálculos")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Porosimetria por expansão de gás, propriedades da amostra e permeabilidade"
        )
        subtitle.setObjectName("muted")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.test_banner = QLabel("Nenhum ensaio ativo — cálculos podem ser simulados, mas não salvos")
        self.test_banner.setObjectName("simulationBanner")
        root.addWidget(self.test_banner)

        sample_card, sample_layout = card()
        sample_title = QLabel("Amostra, gás e referência")
        sample_title.setObjectName("sectionTitle")
        sample_layout.addWidget(sample_title)
        sample_grid = QGridLayout()
        self.length = number_field(suffix="mm")
        self.diameter = number_field(suffix="mm")
        self.mass = number_field(decimals=5, suffix="g")
        self.bulk_volume = number_field(decimals=5, suffix="cm³")
        self.gas = QComboBox()
        for key, properties in GAS_PROPERTIES.items():
            self.gas.addItem(str(properties["nome"]), key)
        self.temperature = number_field(-100, 300, 2, "°C")
        self.temperature.setValue(20.0)
        self.atmospheric = number_field(50, 120, 3, "kPa")
        self.atmospheric.setValue(float(config["calculos"].get("pressao_atmosferica_kpa", 101.325)))
        self.pressure_unit = QComboBox()
        self.pressure_unit.addItems(["bar", "kPa", "MPa", "psi"])
        self.pressure_reference = QComboBox()
        self.pressure_reference.addItem("Manométrica", "manometrica")
        self.pressure_reference.addItem("Absoluta", "absoluta")
        self.current_pressure = QLabel("Pressão atual: —")
        self.current_flow = QLabel("Vazão ativa: —")
        for index, (label, widget) in enumerate([
            ("Comprimento L", self.length), ("Diâmetro D", self.diameter),
            ("Massa seca", self.mass), ("Volume geométrico", self.bulk_volume),
            ("Gás", self.gas), ("Temperatura", self.temperature),
            ("Pressão atmosférica", self.atmospheric), ("Unidade de entrada", self.pressure_unit),
            ("Referência", self.pressure_reference), ("Leitura", self.current_pressure),
            ("Flow meter", self.current_flow),
        ]):
            row, column = divmod(index, 3)
            box = QVBoxLayout()
            name = QLabel(label)
            name.setObjectName("muted")
            box.addWidget(name)
            box.addWidget(widget)
            sample_grid.addLayout(box, row, column)
        sample_layout.addLayout(sample_grid)
        root.addWidget(sample_card)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_boyle_tab(), "Lei de Boyle")
        self.tabs.addTab(self._build_permeability_tab(), "Permeabilidade e Klinkenberg")
        self.tabs.addTab(self._build_history_tab(), "Resultados salvos")
        root.addWidget(self.tabs, 1)
        self.gas.currentIndexChanged.connect(self._apply_gas)
        self._apply_gas()

    def _build_boyle_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        inputs, input_layout = card()
        form = QFormLayout()
        calc_config = self.config["calculos"]
        self.sample_chamber = number_field(decimals=5, suffix="cm³")
        self.sample_chamber.setValue(float(calc_config["volume_camara_amostra_cm3"]))
        self.expansion_chamber = number_field(decimals=5, suffix="cm³")
        self.expansion_chamber.setValue(float(calc_config["volume_expansao_cm3"]))
        self.p0 = number_field(-1000, 1_000_000, 5)
        self.p1 = number_field(-1000, 1_000_000, 5)
        self.p2 = number_field(-1000, 1_000_000, 5)
        self.z0 = number_field(0.01, 10, 6)
        self.z1 = number_field(0.01, 10, 6)
        self.z2 = number_field(0.01, 10, 6)
        for field in (self.z0, self.z1, self.z2):
            field.setValue(1.0)
        form.addRow("Volume da câmara de amostra", self.sample_chamber)
        form.addRow("Volume da câmara de expansão", self.expansion_chamber)
        form.addRow("P0 — expansão antes da abertura", self.p0)
        form.addRow("P1 — amostra antes da abertura", self.p1)
        form.addRow("P2 — equilíbrio após expansão", self.p2)
        form.addRow("Z0 / Z1 / Z2", self._triple_widget(self.z0, self.z1, self.z2))
        input_layout.addLayout(form)
        capture = QHBoxLayout()
        for text, field in [("Capturar P0", self.p0), ("Capturar P1", self.p1), ("Capturar P2", self.p2)]:
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, target=field: self._capture_pressure(target))
            capture.addWidget(button)
        input_layout.addLayout(capture)
        cycle_actions = QHBoxLayout()
        add_cycle = QPushButton("Adicionar ciclo P1/P2")
        add_cycle.clicked.connect(self._add_boyle_cycle)
        remove_cycle = QPushButton("Remover ciclo")
        remove_cycle.clicked.connect(self._remove_boyle_cycle)
        cycle_actions.addWidget(add_cycle)
        cycle_actions.addWidget(remove_cycle)
        input_layout.addLayout(cycle_actions)
        self.boyle_cycles = QTableWidget(0, 2)
        self.boyle_cycles.setHorizontalHeaderLabels(["P1", "P2"])
        self.boyle_cycles.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        input_layout.addWidget(self.boyle_cycles)
        calculate = QPushButton("Calcular por Lei de Boyle")
        calculate.setObjectName("primary")
        calculate.clicked.connect(self._calculate_boyle)
        input_layout.addWidget(calculate)
        layout.addWidget(inputs, 1)

        results, result_layout = card()
        heading = QLabel("Resultado da porosimetria")
        heading.setObjectName("sectionTitle")
        result_layout.addWidget(heading)
        self.boyle_result = QTableWidget(0, 2)
        self.boyle_result.setHorizontalHeaderLabels(["Grandeza", "Resultado"])
        self.boyle_result.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.boyle_result.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        result_layout.addWidget(self.boyle_result)
        self.boyle_quality = QLabel("Aguardando cálculo")
        self.boyle_quality.setObjectName("pillNeutral")
        result_layout.addWidget(self.boyle_quality)
        self.boyle_notes = QTextEdit()
        self.boyle_notes.setPlaceholderText("Observações sobre estabilização, ciclos descartados ou condições do ensaio")
        self.boyle_notes.setMaximumHeight(75)
        result_layout.addWidget(self.boyle_notes)
        save = QPushButton("Salvar resultado no ensaio")
        save.clicked.connect(self._save_boyle)
        result_layout.addWidget(save)
        layout.addWidget(results, 1)
        return page

    def _build_permeability_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        permeability_card, permeability_layout = card()
        heading = QLabel("Darcy para gás compressível")
        heading.setObjectName("sectionTitle")
        permeability_layout.addWidget(heading)
        form = QFormLayout()
        self.inlet_pressure = number_field(-1000, 1_000_000, 5)
        self.outlet_pressure = number_field(-1000, 1_000_000, 5)
        self.flow = number_field(0, 1_000_000, 6, "L/min")
        self.flow_reference_pressure = number_field(0.001, 1_000_000, 5, "kPa abs")
        self.flow_reference_pressure.setValue(101.325)
        self.viscosity = number_field(0.001, 1000, 4, "µPa·s")
        form.addRow("Pressão de entrada", self.inlet_pressure)
        form.addRow("Pressão de saída", self.outlet_pressure)
        form.addRow("Vazão medida", self.flow)
        form.addRow("Pressão de referência da vazão", self.flow_reference_pressure)
        form.addRow("Viscosidade dinâmica", self.viscosity)
        permeability_layout.addLayout(form)
        captures = QHBoxLayout()
        for text, callback in [
            ("Capturar entrada", lambda: self._capture_pressure(self.inlet_pressure)),
            ("Capturar saída", lambda: self._capture_pressure(self.outlet_pressure)),
            ("Capturar vazão", self._capture_flow),
        ]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            captures.addWidget(button)
        permeability_layout.addLayout(captures)
        calculate = QPushButton("Calcular permeabilidade")
        calculate.setObjectName("primary")
        calculate.clicked.connect(self._calculate_permeability)
        permeability_layout.addWidget(calculate)
        self.permeability_result = QTableWidget(0, 2)
        self.permeability_result.setHorizontalHeaderLabels(["Grandeza", "Resultado"])
        self.permeability_result.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        permeability_layout.addWidget(self.permeability_result)
        save = QPushButton("Salvar permeabilidade")
        save.clicked.connect(self._save_permeability)
        permeability_layout.addWidget(save)
        layout.addWidget(permeability_card, 1)

        klink_card, klink_layout = card()
        klink_title = QLabel("Correção de deslizamento de Klinkenberg")
        klink_title.setObjectName("sectionTitle")
        klink_layout.addWidget(klink_title)
        help_label = QLabel(
            "Adicione permeabilidades aparentes obtidas em pressões médias absolutas diferentes."
        )
        help_label.setWordWrap(True)
        help_label.setObjectName("muted")
        klink_layout.addWidget(help_label)
        self.klinkenberg_points = QTableWidget(0, 2)
        self.klinkenberg_points.setHorizontalHeaderLabels(["Pressão média (kPa abs)", "k aparente (mD)"])
        self.klinkenberg_points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        klink_layout.addWidget(self.klinkenberg_points)
        point_actions = QHBoxLayout()
        add = QPushButton("Adicionar resultado atual")
        add.clicked.connect(self._add_klinkenberg_point)
        remove = QPushButton("Remover ponto")
        remove.clicked.connect(lambda: self.klinkenberg_points.removeRow(self.klinkenberg_points.currentRow()) if self.klinkenberg_points.currentRow() >= 0 else None)
        point_actions.addWidget(add)
        point_actions.addWidget(remove)
        klink_layout.addLayout(point_actions)
        calculate_k = QPushButton("Calcular Klinkenberg")
        calculate_k.setObjectName("primary")
        calculate_k.clicked.connect(self._calculate_klinkenberg)
        klink_layout.addWidget(calculate_k)
        self.klinkenberg_result = QTableWidget(0, 2)
        self.klinkenberg_result.setHorizontalHeaderLabels(["Grandeza", "Resultado"])
        self.klinkenberg_result.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        klink_layout.addWidget(self.klinkenberg_result)
        save_k = QPushButton("Salvar correção Klinkenberg")
        save_k.clicked.connect(self._save_klinkenberg)
        klink_layout.addWidget(save_k)
        layout.addWidget(klink_card, 1)
        return page

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(["Data", "Tipo", "Resultado principal", "Observações"])
        self.history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.history)
        return page

    @staticmethod
    def _triple_widget(*fields: QDoubleSpinBox) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        for field in fields:
            layout.addWidget(field)
        return widget

    def set_session(self, definition: TestDefinition | None) -> None:
        self.definition = definition
        self.test_banner.setText(
            f"Ensaio ativo: {definition.code} — {definition.sample_name}"
            if definition else "Nenhum ensaio ativo — cálculos podem ser simulados, mas não salvos"
        )
        if not definition:
            return
        for field, value in [
            (self.length, definition.sample_length_mm),
            (self.diameter, definition.sample_diameter_mm),
            (self.mass, definition.sample_mass_g),
            (self.bulk_volume, definition.bulk_volume_cm3),
        ]:
            field.setValue(value or 0.0)
        self.temperature.setValue(definition.temperature_c)
        self.atmospheric.setValue(definition.atmospheric_pressure_kpa)
        self.pressure_unit.setCurrentText(definition.pressure_unit)
        index = self.pressure_reference.findData(definition.pressure_reference)
        self.pressure_reference.setCurrentIndex(max(0, index))
        gas_index = self.gas.findData(definition.gas_type)
        self.gas.setCurrentIndex(max(0, gas_index))

    def update_measurement(self, measurement: Measurement) -> None:
        self.current_measurement = measurement
        value = measurement.pressure.value
        self.current_pressure.setText(
            f"Pressão atual: {value:.5f} {self.pressure_unit.currentText()}" if value is not None else "Pressão atual: —"
        )
        flow_reading = measurement.flow
        self.current_flow.setText(
            f"Vazão ativa: {flow_reading.value:.5f} L/min" if flow_reading.value is not None else "Vazão ativa: —"
        )

    def _capture_pressure(self, field: QDoubleSpinBox) -> None:
        if self.current_measurement and self.current_measurement.pressure.value is not None:
            field.setValue(self.current_measurement.pressure.value)

    def _capture_flow(self) -> None:
        if not self.current_measurement:
            return
        reading = self.current_measurement.flow
        if reading.value is not None:
            self.flow.setValue(reading.value)

    def _apply_gas(self) -> None:
        properties = GAS_PROPERTIES[self.gas.currentData()]
        if hasattr(self, "viscosity"):
            self.viscosity.setValue(float(properties["viscosidade_upa_s"]))

    def _bulk_volume_value(self) -> float | None:
        if self.bulk_volume.value() > 0:
            return self.bulk_volume.value()
        if self.length.value() > 0 and self.diameter.value() > 0:
            return cylindrical_volume_cm3(self.length.value(), self.diameter.value())
        return None

    def _absolute(self, pressure: float) -> float:
        return absolute_pressure_kpa(
            pressure, self.pressure_unit.currentText(), self.pressure_reference.currentData(),
            self.atmospheric.value(),
        )

    def _add_boyle_cycle(self) -> None:
        row = self.boyle_cycles.rowCount()
        self.boyle_cycles.insertRow(row)
        self.boyle_cycles.setItem(row, 0, QTableWidgetItem(f"{self.p1.value():.6g}"))
        self.boyle_cycles.setItem(row, 1, QTableWidgetItem(f"{self.p2.value():.6g}"))

    def _remove_boyle_cycle(self) -> None:
        row = self.boyle_cycles.currentRow()
        if row >= 0:
            self.boyle_cycles.removeRow(row)

    def _calculate_boyle(self) -> None:
        try:
            if self.boyle_cycles.rowCount() == 0:
                self._add_boyle_cycle()
            cycles_input = [
                (
                    float(self.boyle_cycles.item(row, 0).text()),
                    float(self.boyle_cycles.item(row, 1).text()),
                )
                for row in range(self.boyle_cycles.rowCount())
            ]
            temperature_k = self.temperature.value() + 273.15
            results = [
                calculate_boyle_cycle(
                    sample_chamber_volume_cm3=self.sample_chamber.value(),
                    expansion_volume_cm3=self.expansion_chamber.value(),
                    initial_sample_pressure_kpa_abs=self._absolute(p1),
                    equilibrium_pressure_kpa_abs=self._absolute(p2),
                    initial_expansion_pressure_kpa_abs=self._absolute(self.p0.value()),
                    bulk_volume_cm3=self._bulk_volume_value(),
                    sample_mass_g=self.mass.value() or None,
                    temperature_initial_k=temperature_k,
                    temperature_equilibrium_k=temperature_k,
                    temperature_expansion_k=temperature_k,
                    z_initial=self.z1.value(), z_equilibrium=self.z2.value(), z_expansion=self.z0.value(),
                )
                for p1, p2 in cycles_input
            ]
            summary = summarize_boyle_cycles(
                results, float(self.config["calculos"].get("limite_repetibilidade_percentual", 0.5))
            )
            inputs = self._common_inputs() | {
                "volume_camara_amostra_cm3": self.sample_chamber.value(),
                "volume_expansao_cm3": self.expansion_chamber.value(),
                "p0": self.p0.value(), "ciclos_p1_p2": cycles_input,
                "z0": self.z0.value(), "z1": self.z1.value(), "z2": self.z2.value(),
            }
            output = summary.as_dict()
            self.last_boyle = (inputs, output)
            self._show_results(self.boyle_result, [
                ("Ciclos válidos", str(summary.valid_cycles)),
                ("Volume esquelético médio", self._fmt(summary.skeletal_volume_mean_cm3, "cm³")),
                ("Desvio do volume", self._fmt(summary.skeletal_volume_stddev_cm3, "cm³")),
                ("Coeficiente de variação", self._fmt(summary.coefficient_variation_percent, "%")),
                ("Volume de poros abertos", self._fmt(summary.pore_volume_mean_cm3, "cm³")),
                ("Porosidade aberta", self._fmt(summary.porosity_mean_percent, "%")),
                ("Densidade esquelética", self._fmt(summary.skeletal_density_g_cm3, "g/cm³")),
                ("Densidade aparente", self._fmt(summary.bulk_density_g_cm3, "g/cm³")),
                ("Fração sólida", self._fmt(summary.solid_fraction_percent, "%")),
            ])
            self.boyle_quality.setText("Repetibilidade aprovada" if summary.repeatability_ok else "Repetibilidade acima do limite")
            self.boyle_quality.setObjectName("pillGood" if summary.repeatability_ok else "pillWarn")
            self.boyle_quality.style().unpolish(self.boyle_quality)
            self.boyle_quality.style().polish(self.boyle_quality)
        except (ValueError, TypeError, AttributeError) as exc:
            QMessageBox.warning(self, "Cálculo de Boyle", str(exc))

    def _calculate_permeability(self) -> None:
        try:
            result = calculate_gas_permeability(
                flow_l_min=self.flow.value(), viscosity_upa_s=self.viscosity.value(),
                length_mm=self.length.value(), diameter_mm=self.diameter.value(),
                inlet_pressure_kpa_abs=self._absolute(self.inlet_pressure.value()),
                outlet_pressure_kpa_abs=self._absolute(self.outlet_pressure.value()),
                flow_reference_pressure_kpa_abs=self.flow_reference_pressure.value(),
            )
            inputs = self._common_inputs() | {
                "vazao_l_min": self.flow.value(), "viscosidade_upa_s": self.viscosity.value(),
                "pressao_entrada": self.inlet_pressure.value(),
                "pressao_saida": self.outlet_pressure.value(),
                "pressao_referencia_vazao_kpa_abs": self.flow_reference_pressure.value(),
            }
            output = result.as_dict()
            self.last_permeability = (inputs, output)
            self._show_results(self.permeability_result, [
                ("Permeabilidade", f"{result.permeability_m2:.6e} m²"),
                ("Permeabilidade", f"{result.permeability_darcy:.6g} D"),
                ("Permeabilidade", f"{result.permeability_md:.6g} mD"),
                ("Pressão média absoluta", self._fmt(result.mean_pressure_kpa_abs, "kPa")),
                ("Queda de pressão", self._fmt(result.pressure_drop_kpa, "kPa")),
                ("Velocidade superficial", self._fmt(result.superficial_velocity_m_s, "m/s")),
                ("Gradiente de pressão", self._fmt(result.pressure_gradient_pa_m, "Pa/m")),
            ])
        except ValueError as exc:
            QMessageBox.warning(self, "Cálculo de permeabilidade", str(exc))

    def _add_klinkenberg_point(self) -> None:
        if not self.last_permeability:
            return
        result = self.last_permeability[1]
        row = self.klinkenberg_points.rowCount()
        self.klinkenberg_points.insertRow(row)
        self.klinkenberg_points.setItem(row, 0, QTableWidgetItem(f"{result['mean_pressure_kpa_abs']:.8g}"))
        self.klinkenberg_points.setItem(row, 1, QTableWidgetItem(f"{result['permeability_md']:.8g}"))

    def _calculate_klinkenberg(self) -> None:
        try:
            points = [
                (float(self.klinkenberg_points.item(row, 0).text()), float(self.klinkenberg_points.item(row, 1).text()))
                for row in range(self.klinkenberg_points.rowCount())
            ]
            result = calculate_klinkenberg(points)
            inputs = self._common_inputs() | {"pontos_pressao_media_kpa_permeabilidade_md": points}
            output = result.as_dict()
            self.last_klinkenberg = (inputs, output)
            self._show_results(self.klinkenberg_result, [
                ("Permeabilidade intrínseca", self._fmt(result.intrinsic_permeability_md, "mD")),
                ("Fator de deslizamento b", self._fmt(result.slip_factor_kpa, "kPa")),
                ("Inclinação", self._fmt(result.slope_md_kpa, "mD·kPa")),
                ("R² do ajuste", f"{result.r_squared:.6f}"),
                ("Pontos", str(result.points)),
            ])
        except (ValueError, AttributeError) as exc:
            QMessageBox.warning(self, "Correção de Klinkenberg", str(exc))

    def _common_inputs(self) -> dict[str, Any]:
        return {
            "comprimento_mm": self.length.value(), "diametro_mm": self.diameter.value(),
            "massa_g": self.mass.value() or None, "volume_geometrico_cm3": self._bulk_volume_value(),
            "gas": self.gas.currentData(), "temperatura_c": self.temperature.value(),
            "pressao_atmosferica_kpa": self.atmospheric.value(),
            "unidade_pressao": self.pressure_unit.currentText(),
            "referencia_pressao": self.pressure_reference.currentData(),
        }

    @staticmethod
    def _fmt(value: float | None, unit: str) -> str:
        return f"{value:.6g} {unit}" if value is not None else "—"

    @staticmethod
    def _show_results(table: QTableWidget, rows: list[tuple[str, str]]) -> None:
        table.setRowCount(0)
        for name, value in rows:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(value))

    def _save_boyle(self) -> None:
        if self.last_boyle:
            self.save_requested.emit("Lei de Boyle", *self.last_boyle, self.boyle_notes.toPlainText().strip())

    def _save_permeability(self) -> None:
        if self.last_permeability:
            self.save_requested.emit("Permeabilidade a gás", *self.last_permeability, "")

    def _save_klinkenberg(self) -> None:
        if self.last_klinkenberg:
            self.save_requested.emit("Klinkenberg", *self.last_klinkenberg, "")

    def populate_history(self, rows: list[Any]) -> None:
        self.history.setRowCount(0)
        for record in rows:
            results = json.loads(record["resultados_json"])
            if record["tipo"] == "Lei de Boyle":
                principal = f"Porosidade: {results.get('porosity_mean_percent', '—')} %"
            elif record["tipo"] == "Permeabilidade a gás":
                principal = f"k: {results.get('permeability_md', '—')} mD"
            else:
                principal = f"k∞: {results.get('intrinsic_permeability_md', '—')} mD"
            row = self.history.rowCount()
            self.history.insertRow(row)
            values = [
                datetime.fromisoformat(record["timestamp"]).strftime("%d/%m/%Y %H:%M:%S"),
                record["tipo"], principal, record["observacoes"] or "",
            ]
            for column, value in enumerate(values):
                self.history.setItem(row, column, QTableWidgetItem(str(value)))
