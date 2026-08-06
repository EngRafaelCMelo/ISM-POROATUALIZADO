from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QTextEdit


class MarkerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adicionar marcação")
        layout = QFormLayout(self)
        self.category = QComboBox()
        self.category.addItems([
            "Aplicação de pressão", "Troca de faixa", "Estabilização",
            "Observação do operador", "Ocorrência inesperada",
        ])
        self.comment = QTextEdit()
        self.comment.setMinimumWidth(420)
        self.comment.setMaximumHeight(100)
        layout.addRow("Categoria", self.category)
        layout.addRow("Comentário*", self.comment)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Registrar")
        buttons.accepted.connect(lambda: self.accept() if self.comment.toPlainText().strip() else None)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
