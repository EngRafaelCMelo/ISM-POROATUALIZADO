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
            base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ISM" / "Permeabilimetro"
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
        self._migration_required = False
        self.data = self._load()
        if self._migration_required:
            self.save()

    def _load(self) -> dict[str, Any]:
        with self.default_path.open(encoding="utf-8") as handle:
            default = json.load(handle)
        legacy_three_sensor_config = False
        if self.user_path.exists():
            try:
                with self.user_path.open(encoding="utf-8") as handle:
                    user_config = json.load(handle)
                user_sensors = user_config.get("sensores", {})
                legacy_three_sensor_config = "vazao_alta" in user_sensors
                legacy_flow = isinstance(user_config.get("flow_meter"), dict) and "modo" in user_config["flow_meter"] and "configurado" not in user_config["flow_meter"]
                self._migration_required = bool({"vazao_baixa", "vazao_alta"}.intersection(user_sensors) or legacy_flow)
                if "vazao" not in user_sensors and "vazao_baixa" in user_sensors:
                    user_sensors["vazao"] = user_sensors["vazao_baixa"]
                user_sensors.pop("vazao_baixa", None)
                user_sensors.pop("vazao_alta", None)
                if legacy_flow:
                    user_config.pop("flow_meter", None)
                self._deep_update(default, user_config)
            except (OSError, json.JSONDecodeError):
                pass
        sensors = default["sensores"]
        if legacy_three_sensor_config:
            # Migra configuracoes gravadas por versoes que esperavam tres
            # sinais. O hardware atual usa uma pressão via ADS1115 e uma vazão
            # via MAX3485/RS-485.
            sensors["vazao"].update({
                "nome": "Vazão",
                "limite_inferior": 0.0,
                "limite_superior": 5.0,
                "alerta": 4.5,
                "critico": 5.0,
            })
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
        return Path(configured) if configured else self.paths.data / "permeabilimetro.db"

    def migrate_legacy_database(self) -> Path | None:
        """Copia, após checagem e backup, a base antiga sem jamais removê-la."""
        legacy = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ISM" / "Porosimetro" / "data" / "porosimetro.db"
        target = self.database_path
        if target.exists() or not legacy.exists():
            return None
        with sqlite3.connect(legacy) as source:
            result = source.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise OSError("Banco legado reprovado no PRAGMA integrity_check")
            backup_dir = legacy.parent / "backups"; backup_dir.mkdir(exist_ok=True)
            with sqlite3.connect(backup_dir / "porosimetro_pre_migracao.db") as backup:
                source.backup(backup)
            with sqlite3.connect(target) as destination:
                source.backup(destination)
        return target

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
