from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal


class ExportWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, operation: Callable[..., Path], args: tuple[object, ...]):
        super().__init__()
        self.operation = operation
        self.args = args

    def run(self) -> None:
        try:
            self.completed.emit(str(self.operation(*self.args)))
        except Exception as exc:
            self.failed.emit(str(exc))
