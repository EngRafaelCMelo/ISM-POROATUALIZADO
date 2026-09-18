from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.models import Measurement, MeasurementSnapshot, TestDefinition
from core.permeability import (
    GAS_PROPERTIES,
    absolute_pressure_kpa,
    calculate_gas_permeability,
    calculate_klinkenberg,
)


def field(minimum=0.0, maximum=1_000_000.0, decimals=5, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(minimum, maximum)
    w.setDecimals(decimals)
    w.setSuffix(f" {suffix}" if suffix else "")
    return w


def card():
    f = QFrame()
    f.setObjectName("card")
    return f, QVBoxLayout(f)


class CalculationPage(QWidget):
    save_requested = Signal(str, object, object, str)

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.config = config
        self.definition = None
        self.current_measurement = None
        self.last_permeability = None
        self.last_klinkenberg = None
        self._dirty_results = set()
        self._read_only = False
        self._captured = False
        self._captured_snapshot: MeasurementSnapshot | None = None
        self._captured_input_signature: tuple[Any, ...] | None = None
        root = QVBoxLayout(self)
        title = QLabel("Permeabilidade")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        root.addWidget(
            QLabel(
                "Calcule a permeabilidade de gás compressível, registre condições estáveis e aplique Klinkenberg opcionalmente."
            )
        )
        self.banner = QLabel("Nenhum ensaio ativo")
        self.banner.setObjectName("simulationBanner")
        root.addWidget(self.banner)
        sample, sl = card()
        form = QFormLayout()
        self.length = field(suffix="mm")
        self.diameter = field(suffix="mm")
        self.gas = QComboBox()
        for key, p in GAS_PROPERTIES.items():
            self.gas.addItem(p["nome"], key)
        self.temperature = field(-100, 300, 2, "°C")
        self.temperature.setValue(20)
        self.viscosity = field(0.001, 1000, 4, "µPa·s")
        self.atmospheric = field(50, 120, 3, "kPa")
        self.atmospheric.setValue(config["calculos"].get("pressao_atmosferica_kpa", 101.325))
        self.unit = QComboBox()
        self.unit.addItems(["bar", "kPa", "MPa", "psi"])
        self.reference = QComboBox()
        self.reference.addItem("Manométrica", "manometrica")
        self.reference.addItem("Absoluta", "absoluta")
        for n, w in [
            ("Comprimento", self.length),
            ("Diâmetro", self.diameter),
            ("Gás", self.gas),
            ("Temperatura", self.temperature),
            ("Viscosidade", self.viscosity),
            ("Pressão atmosférica", self.atmospheric),
            ("Unidade de pressão", self.unit),
            ("Referência", self.reference),
        ]:
            form.addRow(n, w)
        sl.addLayout(form)
        root.addWidget(sample)
        tabs = QTabWidget()
        tabs.addTab(self._permeability_tab(), "Permeabilidade")
        tabs.addTab(self._history_tab(), "Resultados salvos")
        root.addWidget(tabs, 1)
        self.gas.currentIndexChanged.connect(self._apply_gas)
        self._apply_gas()

    def _permeability_tab(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        left, ll = card()
        form = QFormLayout()
        self.inlet = field(-1000)
        self.outlet = field(-1000)
        self.flow = field(0, 1e6, 6, "L/min")
        self.flow_ref = field(0.001, 1e6, 5, "kPa abs")
        self.flow_ref.setValue(101.325)
        self.outlet_mode = QComboBox()
        self.outlet_mode.addItem("Informada manualmente", "manual")
        self.outlet_mode.addItem("Fixa configurada", "fixed")
        self.outlet_mode.addItem("Saída aberta à atmosfera", "atmosphere")
        for n, w in [
            ("Pressão de entrada", self.inlet),
            ("Pressão de saída", self.outlet),
            ("Modo da pressão de saída", self.outlet_mode),
            ("Vazão", self.flow),
            ("Referência da vazão", self.flow_ref),
        ]:
            form.addRow(n, w)
        ll.addLayout(form)
        self.current = QLabel("Leituras: pressão — | vazão —")
        ll.addWidget(self.current)
        self.capture_button = QPushButton("Capturar entrada e vazão")
        self.capture_button.clicked.connect(self._capture)
        ll.addWidget(self.capture_button)
        self.calculate_button = QPushButton("Calcular permeabilidade")
        self.calculate_button.setObjectName("primary")
        self.calculate_button.clicked.connect(self._calculate)
        ll.addWidget(self.calculate_button)
        self.result = QTableWidget(0, 2)
        self.result.setHorizontalHeaderLabels(["Grandeza", "Resultado"])
        self.result.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ll.addWidget(self.result)
        self.save_permeability = QPushButton("Salvar resultado")
        self.save_permeability.setEnabled(False)
        self.save_permeability.clicked.connect(
            lambda: self._save("Permeabilidade a gás", self.last_permeability)
        )
        ll.addWidget(self.save_permeability)
        layout.addWidget(left)
        right, rl = card()
        h = QLabel("Correção de Klinkenberg")
        h.setObjectName("sectionTitle")
        rl.addWidget(h)
        self.points = QTableWidget(0, 2)
        self.points.setHorizontalHeaderLabels(["Pressão média (kPa abs)", "k aparente (mD)"])
        self.points.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        rl.addWidget(self.points)
        add = QPushButton("Adicionar resultado atual")
        add.clicked.connect(self._add_point)
        rl.addWidget(add)
        kb = QPushButton("Calcular Klinkenberg")
        kb.clicked.connect(self._klinkenberg)
        rl.addWidget(kb)
        self.kresult = QTableWidget(0, 2)
        self.kresult.setHorizontalHeader().setVisible(True) if False else None
        rl.addWidget(self.kresult)
        self.save_klinkenberg = QPushButton("Salvar correção")
        self.save_klinkenberg.setEnabled(False)
        self.save_klinkenberg.clicked.connect(
            lambda: self._save("Klinkenberg", self.last_klinkenberg)
        )
        rl.addWidget(self.save_klinkenberg)
        layout.addWidget(right)
        return page

    def _history_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(["Data", "Tipo", "Resultado", "Observações"])
        layout.addWidget(self.history)
        return page

    def _apply_gas(self):
        self.viscosity.setValue(float(GAS_PROPERTIES[self.gas.currentData()]["viscosidade_upa_s"]))

    def set_session(self, definition: TestDefinition | None, context="active"):
        changed = not self.definition or not definition or self.definition.code != definition.code
        self.definition = definition
        self._read_only = context != "active"
        if changed:
            self.clear_pending_results()
        self.banner.setText(
            f"Ensaio: {definition.code} — {definition.sample_name}"
            + (" · HISTÓRICO — SOMENTE LEITURA" if self._read_only else "")
            if definition
            else "Nenhum ensaio selecionado"
        )
        if definition:
            self.length.setValue(definition.sample_length_mm or 0)
            self.diameter.setValue(definition.sample_diameter_mm or 0)
            self.temperature.setValue(definition.temperature_c)
            self.unit.setCurrentText(definition.pressure_unit)
            self.reference.setCurrentIndex(
                max(0, self.reference.findData(definition.pressure_reference))
            )
            self.gas.setCurrentIndex(max(0, self.gas.findData(definition.gas_type)))
        for widget in (self.save_permeability, self.save_klinkenberg):
            widget.setEnabled(False)
        self.capture_button.setEnabled(bool(definition) and not self._read_only)
        self.calculate_button.setEnabled(bool(definition) and not self._read_only)

    def update_measurement(self, m: Measurement):
        self.current_measurement = m
        self.current.setText(
            f"Leituras: pressão {m.pressure.value if m.pressure.value is not None else '—'} | vazão {m.flow.value if m.flow.value is not None else '—'}"
        )

    def _capture(self):
        if not self.current_measurement:
            return QMessageBox.information(
                self, "Aguardando leituras", "Conecte o ESP32 ou inicie o simulador."
            )
        measurement = self.current_measurement
        if not measurement.pressure.valid or not measurement.flow.valid:
            return QMessageBox.warning(
                self,
                "Captura indisponível",
                "A pressão e a vazão precisam estar presentes, válidas e atualizadas.",
            )
        if measurement.communication_state.upper() != "OK":
            return QMessageBox.warning(
                self,
                "Captura indisponível",
                f"A medição combinada não está sincronizada ({measurement.communication_state}).",
            )
        pressure_time = measurement.pressure.timestamp
        flow_time = measurement.flow.timestamp
        if pressure_time is None or flow_time is None:
            return QMessageBox.warning(
                self, "Captura indisponível", "Os dois sensores precisam possuir timestamp."
            )
        delta = abs((pressure_time - flow_time).total_seconds())
        tolerance = max(0.1, float(self.config.get("aquisicao", {}).get("intervalo_s", 1.0)))
        if delta > tolerance + 0.05:
            return QMessageBox.warning(
                self,
                "Captura indisponível",
                f"Diferença temporal de {delta:.3f} s excede a tolerância de {tolerance:.3f} s.",
            )
        identity = (pressure_time, flow_time, measurement.sequence)
        if self._captured_snapshot and identity == (
            self._captured_snapshot.pressure_timestamp,
            self._captured_snapshot.flow_timestamp,
            self._captured_snapshot.sequence,
        ):
            return QMessageBox.information(
                self,
                "Leitura já capturada",
                "Aguarde uma nova medição combinada antes de capturar.",
            )
        self.inlet.setValue(float(measurement.pressure.value))
        self.flow.setValue(float(measurement.flow.value))
        self._captured_snapshot = MeasurementSnapshot(
            captured_at=datetime.now(),
            received_at=measurement.received_at,
            pressure_value=float(measurement.pressure.value),
            flow_value=float(measurement.flow.value),
            pressure_timestamp=pressure_time,
            flow_timestamp=flow_time,
            pressure_status=measurement.pressure.device_status,
            flow_status=measurement.flow.device_status,
            pressure_quality=measurement.pressure.quality.value,
            flow_quality=measurement.flow.quality.value,
            pressure_valid=measurement.pressure.valid,
            flow_valid=measurement.flow.valid,
            pressure_raw=measurement.pressure.raw_value,
            flow_raw=measurement.flow.raw_value,
            pressure_current_ma=measurement.pressure.current_ma,
            device_timestamp_ms=measurement.device_timestamp_ms,
            sequence=measurement.sequence,
            schema_version=measurement.schema_version,
            firmware_version=measurement.firmware_version,
            communication_state=measurement.communication_state,
            delta_seconds=delta,
            simulated=measurement.simulated,
        )
        self._captured = True
        self._captured_input_signature = self._input_signature()
        self.current.setText(
            f"Snapshot capturado: pressão {measurement.pressure.value} | "
            f"vazão {measurement.flow.value} | Δt {delta:.3f} s"
        )

    def _input_signature(self) -> tuple[Any, ...]:
        return (
            self.inlet.value(),
            self.outlet.value(),
            self.flow.value(),
            self.flow_ref.value(),
            self.length.value(),
            self.diameter.value(),
            self.temperature.value(),
            self.viscosity.value(),
            self.atmospheric.value(),
            self.unit.currentText(),
            self.reference.currentData(),
            self.outlet_mode.currentData(),
            self.gas.currentData(),
        )

    def _outlet_absolute(self):
        mode = self.outlet_mode.currentData()
        if mode == "atmosphere":
            return self.atmospheric.value()
        return absolute_pressure_kpa(
            self.outlet.value(),
            self.unit.currentText(),
            self.reference.currentData(),
            self.atmospheric.value(),
        )

    def _calculate(self):
        try:
            inlet_absolute = absolute_pressure_kpa(
                self.inlet.value(),
                self.unit.currentText(),
                self.reference.currentData(),
                self.atmospheric.value(),
            )
            outlet_absolute = self._outlet_absolute()
            r = calculate_gas_permeability(
                flow_l_min=self.flow.value(),
                viscosity_upa_s=self.viscosity.value(),
                length_mm=self.length.value(),
                diameter_mm=self.diameter.value(),
                inlet_pressure_kpa_abs=inlet_absolute,
                outlet_pressure_kpa_abs=outlet_absolute,
                flow_reference_pressure_kpa_abs=self.flow_ref.value(),
            )
            snapshot = self._captured_snapshot
            captured_unchanged = bool(
                snapshot and self._captured_input_signature == self._input_signature()
            )
            inputs = {
                "gas": self.gas.currentData(),
                "viscosity_upa_s": self.viscosity.value(),
                "temperatura_c": self.temperature.value(),
                "comprimento_mm": self.length.value(),
                "diametro_mm": self.diameter.value(),
                "cross_section_area_m2": math.pi * (self.diameter.value() / 1000) ** 2 / 4,
                "inlet_pressure_entered": self.inlet.value(),
                "inlet_pressure_kpa_abs": inlet_absolute,
                "outlet_pressure_entered": self.outlet.value(),
                "outlet_pressure_kpa_abs": outlet_absolute,
                "modo_pressao_saida": self.outlet_mode.currentData(),
                "atmospheric_pressure_kpa": self.atmospheric.value(),
                "pressure_reference": self.reference.currentData(),
                "flow_l_min": self.flow.value(),
                "flow_reference_pressure_kpa_abs": self.flow_ref.value(),
                "units": {
                    "temperature": "°C",
                    "viscosity": "µPa·s",
                    "length": "mm",
                    "diameter": "mm",
                    "area": "m²",
                    "pressure_entered": self.unit.currentText(),
                    "absolute_pressure": "kPa abs",
                    "flow": "L/min",
                },
                "data_origin": (
                    "leitura_combinada"
                    if captured_unchanged
                    else "mista"
                    if snapshot
                    else "entrada_manual"
                ),
                "reading_timestamps": {
                    "pressure": snapshot.pressure_timestamp.isoformat() if snapshot else None,
                    "flow": snapshot.flow_timestamp.isoformat() if snapshot else None,
                },
                "captured_measurement": snapshot.as_dict() if snapshot else None,
                "simulado": snapshot.simulated
                if snapshot
                else bool(self.current_measurement and self.current_measurement.simulated),
                "formula": "k=2·μ·L·Qref·Pref/[A·(Pin²−Pout²)]",
            }
            self.last_permeability = (inputs, r.as_dict())
            self._dirty_results.add("Permeabilidade a gás")
            self.save_permeability.setEnabled(self.definition is not None and not self._read_only)
            self._rows(
                self.result,
                [
                    ("Permeabilidade", f"{r.permeability_m2:.6e} m²"),
                    ("Permeabilidade", f"{r.permeability_darcy:.6g} D"),
                    ("Permeabilidade", f"{r.permeability_md:.6g} mD"),
                    ("ΔP", f"{r.pressure_drop_kpa:.6g} kPa"),
                ],
            )
        except ValueError as e:
            QMessageBox.warning(self, "Permeabilidade", str(e))

    def _add_point(self):
        if self.last_permeability:
            r = self.last_permeability[1]
            row = self.points.rowCount()
            self.points.insertRow(row)
            self.points.setItem(row, 0, QTableWidgetItem(str(r["mean_pressure_kpa_abs"])))
            self.points.setItem(row, 1, QTableWidgetItem(str(r["permeability_md"])))

    def _klinkenberg(self):
        try:
            points = [
                (float(self.points.item(i, 0).text()), float(self.points.item(i, 1).text()))
                for i in range(self.points.rowCount())
            ]
            r = calculate_klinkenberg(points)
            self.last_klinkenberg = (
                {
                    "points": [
                        {
                            "mean_pressure_kpa_abs": pressure,
                            "inverse_pressure_kpa": 1 / pressure,
                            "permeability_md": permeability,
                        }
                        for pressure, permeability in points
                    ],
                    "units": {
                        "mean_pressure": "kPa abs",
                        "inverse_pressure": "1/kPa",
                        "permeability": "mD",
                    },
                    "formula": "k_aparente = k∞ + inclinação·(1/Pm)",
                    "simulado": bool(
                        self.current_measurement and self.current_measurement.simulated
                    ),
                },
                r.as_dict(),
            )
            self._dirty_results.add("Klinkenberg")
            self.save_klinkenberg.setEnabled(self.definition is not None and not self._read_only)
            self._rows(
                self.kresult,
                [
                    ("Permeabilidade intrínseca", f"{r.intrinsic_permeability_md:.6g} mD"),
                    ("b", f"{r.slip_factor_kpa:.6g} kPa"),
                    ("R²", f"{r.r_squared:.6f}"),
                ],
            )
        except (ValueError, AttributeError) as e:
            QMessageBox.warning(self, "Klinkenberg", str(e))

    @staticmethod
    def _rows(table, rows):
        table.setRowCount(0)
        for a, b in rows:
            i = table.rowCount()
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(a))
            table.setItem(i, 1, QTableWidgetItem(b))

    def _save(self, kind, data):
        if data:
            self.save_requested.emit(kind, *data, "")

    def pending_results(self):
        return [
            (k, d[0], d[1], "")
            for k, d in [
                ("Permeabilidade a gás", self.last_permeability),
                ("Klinkenberg", self.last_klinkenberg),
            ]
            if d and k in self._dirty_results
        ]

    def mark_saved(self, kind):
        self._dirty_results.discard(kind)
        (
            self.save_permeability if kind == "Permeabilidade a gás" else self.save_klinkenberg
        ).setEnabled(False)

    def clear_pending_results(self):
        self.last_permeability = None
        self.last_klinkenberg = None
        self._dirty_results.clear()
        self._captured = False
        self._captured_snapshot = None
        self._captured_input_signature = None
        self.current_measurement = None
        if hasattr(self, "save_permeability"):
            self.save_permeability.setEnabled(False)
            self.save_klinkenberg.setEnabled(False)
        if hasattr(self, "result"):
            self.result.setRowCount(0)
            self.kresult.setRowCount(0)
            self.points.setRowCount(0)

    def populate_history(self, rows):
        self.history.setRowCount(0)
        for r in rows:
            result = json.loads(r["resultados_json"])
            i = self.history.rowCount()
            self.history.insertRow(i)
            values = [
                datetime.fromisoformat(r["timestamp"]).strftime("%d/%m/%Y %H:%M"),
                r["tipo"],
                f"{result.get('permeability_md', result.get('intrinsic_permeability_md', '—'))} mD",
                r["observacoes"] or "",
            ]
            for j, v in enumerate(values):
                self.history.setItem(i, j, QTableWidgetItem(str(v)))
