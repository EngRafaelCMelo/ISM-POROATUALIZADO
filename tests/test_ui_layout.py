from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton


def test_buttons_reserve_vertical_space_for_font() -> None:
    app = QApplication.instance() or QApplication([])
    button = QPushButton("Iniciar ensaio")
    with open("ui/styles.qss", encoding="utf-8") as handle:
        button.setStyleSheet(handle.read())
    button.show()
    app.processEvents()
    assert button.height() >= button.fontMetrics().height() + 18
    button.close()
