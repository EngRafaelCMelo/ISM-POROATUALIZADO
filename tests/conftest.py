from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def config_data() -> dict:
    path = Path(__file__).parents[1] / "config" / "default_config.json"
    return json.loads(path.read_text(encoding="utf-8"))
