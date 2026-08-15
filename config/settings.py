from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data: Path
    logs: Path
    exports: Path
    config: Path

    @classmethod
    def create(cls) -> "AppPaths":
        if getattr(sys, "frozen", False):
            base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ISM" / "Porosimetro"
        else:
            base = Path(__file__).resolve().parents[1]
        paths = cls(
            root=base,
            data=base / "data",
            logs=base / "logs",
            exports=base / "exports",
            config=base / "config",
        )
        for folder in (paths.data, paths.logs, paths.exports, paths.config):
            folder.mkdir(parents=True, exist_ok=True)
        return paths


class ConfigManager:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.default_path = Path(__file__).with_name("default_config.json")
        self.user_path = paths.config / "user_config.json"
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        with self.default_path.open(encoding="utf-8") as handle:
            default = json.load(handle)
        if self.user_path.exists():
            try:
                with self.user_path.open(encoding="utf-8") as handle:
                    self._deep_update(default, json.load(handle))
            except (OSError, json.JSONDecodeError):
                pass
        return default

    @staticmethod
    def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                ConfigManager._deep_update(target[key], value)
            else:
                target[key] = value

    def save(self) -> None:
        self.user_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get(self, dotted_key: str, default: Any = None) -> Any:
        value: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def set(self, dotted_key: str, value: Any) -> None:
        target = self.data
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
        self.save()

    @property
    def database_path(self) -> Path:
        configured = self.get("dados.banco")
        return Path(configured) if configured else self.paths.data / "porosimetro.db"

    def backup_database(self) -> Path | None:
        source = self.database_path
        if not source.exists():
            return None
        backup_dir = self.paths.data / "backups"
        backup_dir.mkdir(exist_ok=True)
        target = backup_dir / f"{source.stem}_backup{source.suffix}"
        with sqlite3.connect(source) as source_connection, sqlite3.connect(target) as target_connection:
            source_connection.backup(target_connection)
            result = target_connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise OSError("Falha na verificação de integridade do backup SQLite")
        return target

    def real_mode_errors(self) -> list[str]:
        """Retorna parâmetros obrigatórios ausentes sem inventar dados do equipamento."""
        errors: list[str] = []
        pressure = self.get("sensores.pressao", {})
        if pressure.get("limite_inferior") is None or pressure.get("limite_superior") is None:
            errors.append("Informe a faixa mínima e máxima do transdutor de pressão")
        flow = self.get("flow_meter", {})
        required = (
            "endereco_escravo", "baud_rate", "paridade", "stop_bits", "funcao",
            "registrador_inicial", "quantidade_registradores", "tipo_dado",
            "ordem_bytes", "ordem_palavras", "fator_escala", "unidade_nativa",
        )
        if not flow.get("configurado") or any(flow.get(key) is None for key in required):
            errors.append("Complete e confirme a configuração Modbus do flow meter")
        if not self.get("comunicacao.porta"):
            errors.append("Selecione a porta serial do ESP32")
        return errors
