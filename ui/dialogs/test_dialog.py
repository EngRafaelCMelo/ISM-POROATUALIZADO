from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.models import TestDefinition
from core.porosimetry import GAS_PROPERTIES, cylindrical_volume_cm3


def physical_spin(suffix: str, maximum: float = 1_000_000.0, decimals: int = 4) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setRange(0.0, maximum)
    field.setDecimals(decimals)
    field.setSuffix(f" {suffix}")
    field.setSpecialValueText("Não informado")
    return field


class TestSetupDialog(QDialog):
    def __init__(self, code: str, default_export: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Novo ensaio")
        self.setMinimumSize(650, 650)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        general_page = QWidget()
        form = QFormLayout(general_page)
        self.code = QLineEdit(code)
        self.sample = QLineEdit()
        self.identification = QLineEdit()
        self.operator = QLineEdit("Operador")
        self.description = QTextEdit()
        self.description.setMaximumHeight(65)
        self.test_type = QComboBox()
        self.test_type.addItems(["Porosimetria por gás", "Permeabilidade", "Porosidade e permeabilidade"])
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(65)
        self.expected_range = QLineEdit()
        self.expected_range.setPlaceholderText("Use a faixa confirmada no manual do transdutor")
        self.pressure_unit = QComboBox()
        self.pressure_unit.addItems(["bar", "kPa", "MPa", "psi"])
        self.flow_unit = QComboBox()
        self.flow_unit.addItems(["L/min", "mL/min"])
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.05, 60)
        self.interval.setValue(1.0)
        self.interval.setSuffix(" s")
        self.export_dir = QLineEdit(str(default_export))
        browse = QPushButton("Escolher…")
        browse.clicked.connect(self._browse)
        export_row = QHBoxLayout()
        export_row.addWidget(self.export_dir)
        export_row.addWidget(browse)
        for label, widget in [
            ("Código do ensaio*", self.code), ("Nome da amostra*", self.sample),
            ("Identificação", self.identification), ("Operador*", self.operator),
            ("Descrição", self.description), ("Tipo de ensaio", self.test_type),
            ("Observações", self.notes), ("Faixa esperada", self.expected_range),
            ("Unidade de pressão", self.pressure_unit),
            ("Unidade de vazão", self.flow_unit), ("Intervalo de aquisição", self.interval),
        ]:
            form.addRow(label, widget)
        form.addRow("Diretório de exportação", export_row)
        tabs.addTab(general_page, "Identificação")

        physical_page = QWidget()
        physical_form = QFormLayout(physical_page)
        information = QLabel(
            "Estes dados alimentam os cálculos de Boyle, porosidade, densidade e permeabilidade. "
            "Podem ser completados ou ajustados posteriormente na tela Cálculos."
        )
        information.setWordWrap(True)
        information.setObjectName("muted")
        self.length = physical_spin("mm")
        self.diameter = physical_spin("mm")
        self.mass = physical_spin("g", decimals=5)
        self.bulk_volume = physical_spin("cm³", decimals=5)
        self.gas = QComboBox()
        for key, properties in GAS_PROPERTIES.items():
            self.gas.addItem(str(properties["nome"]), key)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(-100.0, 300.0)
        self.temperature.setDecimals(2)
        self.temperature.setValue(20.0)
        self.temperature.setSuffix(" °C")
        self.atmospheric = QDoubleSpinBox()
        self.atmospheric.setRange(50.0, 120.0)
        self.atmospheric.setDecimals(3)
        self.atmospheric.setValue(101.325)
        self.atmospheric.setSuffix(" kPa")
        self.pressure_reference = QComboBox()
        self.pressure_reference.addItem("Manométrica (relativa à atmosfera)", "manometrica")
        self.pressure_reference.addItem("Absoluta", "absoluta")
        self.geometry_preview = QLabel("Volume geométrico calculado: —")
        self.geometry_preview.setObjectName("muted")
        self.length.valueChanged.connect(self._update_geometry)
        self.diameter.valueChanged.connect(self._update_geometry)
        physical_form.addRow(information)
        physical_form.addRow("Comprimento L", self.length)
        physical_form.addRow("Diâmetro D", self.diameter)
        physical_form.addRow("Massa seca", self.mass)
        physical_form.addRow("Volume geométrico manual", self.bulk_volume)
        physical_form.addRow("", self.geometry_preview)
        physical_form.addRow("Gás de análise", self.gas)
        physical_form.addRow("Temperatura", self.temperature)
        physical_form.addRow("Pressão atmosférica local", self.atmospheric)
        physical_form.addRow("Referência das pressões", self.pressure_reference)
        tabs.addTab(physical_page, "Amostra e gás")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Iniciar ensaio")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Diretório de exportação", self.export_dir.text()
        )
        if selected:
            self.export_dir.setText(selected)

    def _update_geometry(self) -> None:
        if self.length.value() > 0 and self.diameter.value() > 0:
            volume = cylindrical_volume_cm3(self.length.value(), self.diameter.value())
            self.geometry_preview.setText(f"Volume cilíndrico calculado: {volume:.5f} cm³")
        else:
            self.geometry_preview.setText("Volume geométrico calculado: —")

    def _validate(self) -> None:
        required = [self.code, self.sample, self.operator]
        if any(not field.text().strip() for field in required):
            for field in required:
                field.setProperty("validationError", not field.text().strip())
                field.style().unpolish(field); field.style().polish(field)
            return
        self.accept()

    @staticmethod
    def _optional(value: float) -> float | None:
        return value if value > 0 else None

    def definition(self) -> TestDefinition:
        length = self._optional(self.length.value())
        diameter = self._optional(self.diameter.value())
        manual_volume = self._optional(self.bulk_volume.value())
        calculated_volume = (
            cylindrical_volume_cm3(length, diameter) if length and diameter else None
        )
        return TestDefinition(
            code=self.code.text().strip(),
            sample_name=self.sample.text().strip(),
            sample_identification=self.identification.text().strip(),
            operator=self.operator.text().strip(),
            description=self.description.toPlainText().strip(),
            test_type=self.test_type.currentText(),
            notes=self.notes.toPlainText().strip(),
            expected_pressure_range=self.expected_range.text().strip(),
            pressure_unit=self.pressure_unit.currentText(),
            flow_unit=self.flow_unit.currentText(),
            acquisition_interval=self.interval.value(),
            export_directory=self.export_dir.text().strip(),
            sample_length_mm=length,
            sample_diameter_mm=diameter,
            sample_mass_g=self._optional(self.mass.value()),
            bulk_volume_cm3=manual_volume or calculated_volume,
            gas_type=self.gas.currentData(),
            temperature_c=self.temperature.value(),
            atmospheric_pressure_kpa=self.atmospheric.value(),
            pressure_reference=self.pressure_reference.currentData(),
        )
