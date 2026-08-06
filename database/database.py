from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from database.migrations import SCHEMA_SQL, apply_migrations

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            logger.exception("Falha na transação SQLite")
            raise
        finally:
            connection.close()

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        """Conexão de leitura com fechamento determinístico."""
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(SCHEMA_SQL)
            apply_migrations(connection)

    def health_check(self) -> bool:
        try:
            with self.read_connection() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            logger.exception("Banco indisponível")
            return False
