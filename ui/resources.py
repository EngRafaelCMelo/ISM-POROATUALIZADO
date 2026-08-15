from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def branding_path(filename: str) -> Path:
    return resource_path("assets", "branding", filename)
