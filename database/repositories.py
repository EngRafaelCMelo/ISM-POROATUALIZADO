from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Iterable

from core.constants import TestStatus
from core.models import Alarm, Measurement, TestDefinition, TestSession
from database.database import Database


class TestRepository:
    def __init__(self, database: Database):
        self.db = database

    def next_code(self, year: int | None = None) -> str:
        year = year or datetime.now().year
        prefix = f"ENS-{year}-"
        with self.db.read_connection() as con:
            row = con.execute(
                "SELECT codigo FROM ensaios WHERE codigo LIKE ? ORDER BY codigo DESC LIMIT 1",
                (f"{prefix}%",),
            ).fetchone()
        number = int(row["codigo"].rsplit("-", 1)[1]) + 1 if row else 1
        return f"{prefix}{number:04d}"

    def create(self, definition: TestDefinition) -> TestSession:
        now = datetime.now()
        with self.db.transaction() as con:
            cur = con.execute(
                """INSERT INTO amostras(nome, identificacao) VALUES (?, ?)""",
                (definition.sample_name, definition.sample_identification),
            )
            sample_id = cur.lastrowid
            cur = con.execute(
                """INSERT INTO ensaios(
                    codigo, amostra_id, amostra_nome, amostra_identificacao, operador,
                    descricao, tipo, observacoes, faixa_pressao, flow_meter_principal,
                    unidade_pressao, unidade_vazao, intervalo_aquisicao,
                    diretorio_exportacao, inicio, status,
                    comprimento_amostra_mm, diametro_amostra_mm, massa_amostra_g,
                    volume_geometrico_cm3, tipo_gas, temperatura_c,
                    pressao_atmosferica_kpa, referencia_pressao
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    definition.code, sample_id, definition.sample_name,
                    definition.sample_identification, definition.operator,
                    definition.description, definition.test_type, definition.notes,
                    definition.expected_pressure_range, "Único",
                    definition.pressure_unit, definition.flow_unit,
                    definition.acquisition_interval, definition.export_directory,
                    now.isoformat(), TestStatus.RUNNING.value,
                    definition.sample_length_mm, definition.sample_diameter_mm,
                    definition.sample_mass_g, definition.bulk_volume_cm3,
                    definition.gas_type, definition.temperature_c,
                    definition.atmospheric_pressure_kpa, definition.pressure_reference,
                ),
            )
            test_id = int(cur.lastrowid)
        return TestSession(test_id, definition, TestStatus.RUNNING, now)

    def save_measurement(self, test_id: int, measurement: Measurement) -> int:
        maximum_pressure = measurement.pressure.value if measurement.pressure.quality.value in ("valid", "warning", "simulated") else None
        maximum_flow = measurement.flow.value if measurement.flow.quality.value in ("valid", "warning", "simulated") else None
        with self.db.transaction() as con:
            cur = con.execute(
                """INSERT INTO medicoes(
                    ensaio_id, timestamp_computador, timestamp_esp32, pressao_ma,
                    pressao, vazao_baixa_ma, vazao_baixa, vazao_alta_ma, vazao_alta,
                    flow_meter_ativo, qualidade, estado_comunicacao, mensagem_original
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                measurement.to_db_tuple(test_id),
            )
            con.execute(
                """UPDATE ensaios SET quantidade_amostras = quantidade_amostras + 1,
                   pressao_maxima = CASE
                     WHEN ? IS NULL THEN pressao_maxima
                     WHEN pressao_maxima IS NULL OR ? > pressao_maxima THEN ?
                     ELSE pressao_maxima END,
                   vazao_maxima = CASE
                     WHEN ? IS NULL THEN vazao_maxima
                     WHEN vazao_maxima IS NULL OR ? > vazao_maxima THEN ?
                     ELSE vazao_maxima END
                   WHERE id = ?""",
                (
                    maximum_pressure, maximum_pressure, maximum_pressure,
                    maximum_flow, maximum_flow, maximum_flow,
                    test_id,
                ),
            )
            return int(cur.lastrowid)

    def pause_or_resume(self, test_id: int, status: TestStatus) -> None:
        with self.db.transaction() as con:
            con.execute("UPDATE ensaios SET status=? WHERE id=?", (status.value, test_id))

    def finish(self, test_id: int, final_note: str = "") -> None:
        now = datetime.now()
        with self.db.transaction() as con:
            row = con.execute("SELECT inicio FROM ensaios WHERE id=?", (test_id,)).fetchone()
            if not row:
                raise ValueError("Ensaio não encontrado")
            duration = (now - datetime.fromisoformat(row["inicio"])).total_seconds()
            con.execute(
                """UPDATE ensaios SET status=?, fim=?, duracao_segundos=?,
                   observacao_final=? WHERE id=?""",
                (TestStatus.FINISHED.value, now.isoformat(), duration, final_note, test_id),
            )

    def mark_interrupted_tests(self) -> int:
        with self.db.transaction() as con:
            cur = con.execute(
                "UPDATE ensaios SET status=? WHERE status IN (?,?)",
                (TestStatus.INTERRUPTED.value, TestStatus.RUNNING.value, TestStatus.PAUSED.value),
            )
            return cur.rowcount

    def list(self, search: str = "") -> list[sqlite3.Row]:
        with self.db.read_connection() as con:
            return con.execute(
                """SELECT * FROM ensaios
                   WHERE codigo LIKE ? OR amostra_nome LIKE ? OR operador LIKE ?
                   ORDER BY inicio DESC""",
                (f"%{search}%", f"%{search}%", f"%{search}%"),
            ).fetchall()

    def get(self, test_id: int) -> sqlite3.Row | None:
        with self.db.read_connection() as con:
            return con.execute("SELECT * FROM ensaios WHERE id=?", (test_id,)).fetchone()

    def measurements(self, test_id: int) -> list[sqlite3.Row]:
        with self.db.read_connection() as con:
            return con.execute(
                "SELECT * FROM medicoes WHERE ensaio_id=? ORDER BY timestamp_computador", (test_id,)
            ).fetchall()

    def delete(self, test_id: int) -> None:
        with self.db.transaction() as con:
            con.execute("DELETE FROM ensaios WHERE id=?", (test_id,))

    def invalidate(self, test_id: int) -> None:
        with self.db.transaction() as con:
            con.execute(
                "UPDATE ensaios SET status=? WHERE id=?", (TestStatus.INVALID.value, test_id)
            )


class EventRepository:
    def __init__(self, database: Database):
        self.db = database

    def add_marker(self, test_id: int, category: str, comment: str) -> None:
        with self.db.transaction() as con:
            con.execute(
                "INSERT INTO marcacoes(ensaio_id,timestamp,categoria,comentario) VALUES(?,?,?,?)",
                (test_id, datetime.now().isoformat(), category, comment),
            )

    def markers(self, test_id: int) -> list[sqlite3.Row]:
        with self.db.read_connection() as con:
            return con.execute(
                "SELECT * FROM marcacoes WHERE ensaio_id=? ORDER BY timestamp", (test_id,)
            ).fetchall()

    def add_alarm(self, test_id: int | None, alarm: Alarm) -> int:
        with self.db.transaction() as con:
            cur = con.execute(
                """INSERT INTO alarmes(
                    ensaio_id,timestamp,sensor,severidade,categoria,mensagem,
                    valor_medido,limite,reconhecido,observacao_operador
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    test_id, alarm.timestamp.isoformat(), alarm.sensor,
                    alarm.severity.value, alarm.category, alarm.message,
                    alarm.measured_value, alarm.limit_value, int(alarm.acknowledged),
                    alarm.operator_note,
                ),
            )
            return int(cur.lastrowid)

    def alarms(self, test_id: int | None = None, only_active: bool = False) -> list[sqlite3.Row]:
        clauses, args = [], []
        if test_id is not None:
            clauses.append("ensaio_id=?")
            args.append(test_id)
        if only_active:
            clauses.append("reconhecido=0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.read_connection() as con:
            return con.execute(
                f"SELECT * FROM alarmes {where} ORDER BY timestamp DESC LIMIT 500", args
            ).fetchall()

    def acknowledge(self, alarm_id: int, note: str = "") -> None:
        with self.db.transaction() as con:
            con.execute(
                "UPDATE alarmes SET reconhecido=1, observacao_operador=? WHERE id=?",
                (note, alarm_id),
            )


class CalibrationRepository:
    def __init__(self, database: Database):
        self.db = database

    def save(
        self, sensor: str, operator: str, gain: float, offset: float, error: float,
        stable: bool, points: list[tuple[float, float]], notes: str
    ) -> int:
        with self.db.transaction() as con:
            con.execute("UPDATE calibracoes SET ativa=0 WHERE sensor=?", (sensor,))
            cur = con.execute(
                """INSERT INTO calibracoes(
                   sensor,timestamp,operador,ganho,offset,erro,estavel,pontos_json,
                   observacoes,ativa) VALUES(?,?,?,?,?,?,?,?,?,1)""",
                (
                    sensor, datetime.now().isoformat(), operator, gain, offset, error,
                    int(stable), json.dumps(points), notes,
                ),
            )
            return int(cur.lastrowid)

    def history(self, sensor: str) -> list[sqlite3.Row]:
        with self.db.read_connection() as con:
            return con.execute(
                "SELECT * FROM calibracoes WHERE sensor=? ORDER BY timestamp DESC", (sensor,)
            ).fetchall()


class CalculationRepository:
    def __init__(self, database: Database):
        self.db = database

    def save(
        self,
        test_id: int,
        calculation_type: str,
        inputs: dict[str, Any],
        results: dict[str, Any],
        notes: str = "",
    ) -> int:
        with self.db.transaction() as con:
            cursor = con.execute(
                """INSERT INTO calculos(
                   ensaio_id,timestamp,tipo,entradas_json,resultados_json,observacoes
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    test_id, datetime.now().isoformat(), calculation_type,
                    json.dumps(inputs, ensure_ascii=False),
                    json.dumps(results, ensure_ascii=False), notes,
                ),
            )
            return int(cursor.lastrowid)

    def list(self, test_id: int) -> list[sqlite3.Row]:
        with self.db.read_connection() as con:
            return con.execute(
                "SELECT * FROM calculos WHERE ensaio_id=? ORDER BY timestamp DESC", (test_id,)
            ).fetchall()
