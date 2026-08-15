from __future__ import annotations

from datetime import datetime

from core.constants import TestStatus
from core.models import Measurement, TestDefinition, TestSession
from database.repositories import EventRepository, TestRepository


class TestService:
    def __init__(self, tests: TestRepository, events: EventRepository):
        self.tests = tests
        self.events = events
        self.current: TestSession | None = None
        self._paused_at: datetime | None = None

    def start(self, definition: TestDefinition) -> TestSession:
        if self.current and self.current.status in (TestStatus.RUNNING, TestStatus.PAUSED):
            raise RuntimeError("Já existe um ensaio ativo")
        self.current = self.tests.create(definition)
        return self.current

    def record(self, measurement: Measurement) -> bool:
        if not self.current or self.current.status != TestStatus.RUNNING:
            return False
        self.tests.save_measurement(self.current.id, measurement)
        self.current.sample_count += 1
        return True

    def toggle_pause(self) -> TestStatus:
        if not self.current:
            raise RuntimeError("Nenhum ensaio ativo")
        if self.current.status == TestStatus.RUNNING:
            self.current.status = TestStatus.PAUSED
            self._paused_at = datetime.now()
        elif self.current.status == TestStatus.PAUSED:
            self.current.status = TestStatus.RUNNING
            if self._paused_at:
                self.current.paused_seconds += (datetime.now() - self._paused_at).total_seconds()
            self._paused_at = None
        self.tests.pause_or_resume(self.current.id, self.current.status)
        return self.current.status

    def finish(self, final_note: str = "") -> TestSession:
        if not self.current:
            raise RuntimeError("Nenhum ensaio ativo")
        self.tests.finish(self.current.id, final_note, self.elapsed_seconds())
        self.current.status = TestStatus.FINISHED
        self.current.ended_at = datetime.now()
        result = self.current
        self.current = None
        return result

    def add_marker(self, category: str, comment: str) -> None:
        if not self.current:
            raise RuntimeError("Nenhum ensaio ativo")
        self.events.add_marker(self.current.id, category, comment)

    def elapsed_seconds(self) -> float:
        if not self.current:
            return 0.0
        end = self.current.ended_at or datetime.now()
        paused = self.current.paused_seconds
        if self._paused_at:
            paused += (datetime.now() - self._paused_at).total_seconds()
        return max(0.0, (end - self.current.started_at).total_seconds() - paused)
