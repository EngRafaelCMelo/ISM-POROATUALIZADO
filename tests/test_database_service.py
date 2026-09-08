from __future__ import annotations

from datetime import datetime

from core.constants import ReadingQuality, TestStatus as Status
from core.models import Measurement, SensorReading, TestDefinition as Definition
from database.database import Database
from database.repositories import (
    CalculationRepository,
    EventRepository,
    TestRepository as Repository,
)
from services.test_service import TestService as Service


def measurement() -> Measurement:
    return Measurement(
        received_at=datetime.now(),
        pressure=SensorReading(2.0, 7.2, ReadingQuality.VALID),
        flow=SensorReading(1.0, None, ReadingQuality.VALID),
    )


def test_create_record_and_finish_test(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    repository = Repository(database)
    service = Service(repository, EventRepository(database))
    session = service.start(Definition(code="ENS-2026-0001", sample_name="Amostra A"))
    assert session.status == Status.RUNNING
    assert service.record(measurement())
    service.add_marker("Observação", "Pressão estabilizada")
    finished = service.finish("Concluído")
    assert finished.status == Status.FINISHED
    stored = repository.get(finished.id)
    assert stored["quantidade_amostras"] == 1
    assert stored["pressao_maxima"] == 2.0
    measurements = repository.measurements(finished.id)
    assert len(measurements) == 1
    assert measurements[0]["vazao_alta"] is None
    assert measurements[0]["vazao"] == 1.0


def test_recover_interrupted_test(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    repository = Repository(database)
    repository.create(Definition(code="ENS-2026-0001", sample_name="A"))
    assert repository.mark_interrupted_tests() == 1
    assert repository.list()[0]["status"] == Status.INTERRUPTED.value


def test_physical_parameters_and_calculation_are_persisted(tmp_path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    repository = Repository(database)
    session = repository.create(Definition(
        code="ENS-2026-0002", sample_name="Testemunho",
        sample_length_mm=50.0, sample_diameter_mm=25.4, sample_mass_g=52.4,
        bulk_volume_cm3=25.335, gas_type="Helio", temperature_c=20.0,
        atmospheric_pressure_kpa=101.325, pressure_reference="manometrica",
    ))
    stored = repository.get(session.id)
    assert stored["comprimento_amostra_mm"] == 50.0
    assert stored["tipo_gas"] == "Helio"
    calculations = CalculationRepository(database)
    calculations.save(
        session.id, "Permeabilidade a gás", {"flow_l_min": 2.0},
        {"permeability_md": 18.5}, "Condição estável",
    )
    saved = calculations.list(session.id)
    assert len(saved) == 1
    assert saved[0]["tipo"] == "Permeabilidade a gás"
