from __future__ import annotations

import json
import logging
import math
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.units import FLOW_PROTOCOL_UNIT
from core.version import APP_NAME, APP_VERSION

logger = logging.getLogger(__name__)


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
        self.warnings: list[str] = []
        self.data = self._load()
        if self._migration_required:
            self.save()

    def _load(self) -> dict[str, Any]:
        with self.default_path.open(encoding="utf-8") as handle:
            default = json.load(handle)
        user_sensors: dict[str, Any] = {}
        if self.user_path.exists():
            try:
                with self.user_path.open(encoding="utf-8") as handle:
                    user_config = json.load(handle)
                user_sensors = user_config.get("sensores", {})
                legacy_flow = user_config.pop("flow_meter", None)
                if legacy_flow:
                    migrated_flow = user_config.setdefault("flowmeter", {})
                    # Preserva todos os valores conhecidos, convertendo nomes antigos.
                    aliases = {"endereco_escravo": "slave_id"}
                    for key, value in legacy_flow.items():
                        migrated_flow.setdefault(aliases.get(key, key), value)
                self._migration_required = bool(
                    {"vazao_baixa", "vazao_alta"}.intersection(user_sensors) or legacy_flow
                )
                if "vazao" not in user_sensors and "vazao_baixa" in user_sensors:
                    user_sensors["vazao"] = dict(user_sensors["vazao_baixa"])
                    user_sensors["vazao"]["nome"] = "Vazão"
                user_sensors.pop("vazao_baixa", None)
                user_sensors.pop("vazao_alta", None)
                self._deep_update(default, user_config)
                for sensor_key in ("pressao", "vazao"):
                    overrides = user_sensors.get(sensor_key, {})
                    if not isinstance(overrides, dict):
                        continue
                    sensor = default["sensores"][sensor_key]
                    lower = sensor.get("limite_inferior")
                    upper = sensor.get("limite_superior")
                    if lower is None or upper is None or float(lower) >= float(upper):
                        continue
                    alert = sensor.get("alerta")
                    if (
                        "alerta" not in overrides
                        and alert is not None
                        and not float(lower) <= float(alert) <= float(upper)
                    ):
                        sensor["alerta"] = float(lower) + 0.9 * (float(upper) - float(lower))
                        self._migration_required = True
                    critical = sensor.get("critico")
                    if (
                        "critico" not in overrides
                        and critical is not None
                        and not float(lower) <= float(critical) <= float(upper)
                    ):
                        sensor["critico"] = float(upper)
                        self._migration_required = True
            except json.JSONDecodeError as exc:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup = self.user_path.with_name(f"user_config_corrompido_{stamp}.json")
                shutil.copy2(self.user_path, backup)
                message = f"Configuração local corrompida; backup criado em {backup}: {exc}"
                self.warnings.append(message)
                logger.error(message)
                self._migration_required = True
            except OSError as exc:
                message = f"Não foi possível ler a configuração local: {exc}"
                self.warnings.append(message)
                logger.error(message)
        default["aplicacao"]["nome"] = APP_NAME
        default["aplicacao"]["versao"] = APP_VERSION
        self.validate(default)
        return default

    @staticmethod
    def validate(data: dict[str, Any]) -> None:
        sensors = data.get("sensores", {})
        for key in ("pressao", "vazao"):
            cfg = sensors.get(key, {})
            if not str(cfg.get("unidade", "")).strip():
                raise ValueError(f"A unidade de {key} é obrigatória")
            current_min = float(cfg.get("corrente_min", 4.0))
            current_max = float(cfg.get("corrente_max", 20.0))
            if not math.isfinite(current_min) or not math.isfinite(current_max):
                raise ValueError(f"A escala de corrente de {key} deve ser finita")
            if current_min >= current_max:
                raise ValueError(f"A corrente mínima de {key} deve ser menor que a máxima")
            lower, upper = cfg.get("limite_inferior"), cfg.get("limite_superior")
            if lower is None or upper is None:
                continue
            if float(lower) >= float(upper):
                raise ValueError(f"Faixa de {key}: o mínimo deve ser menor que o máximo")
            for name in ("alerta", "critico"):
                value = cfg.get(name)
                if value is not None and not float(lower) <= float(value) <= float(upper):
                    raise ValueError(f"{name} de {key} deve estar dentro da faixa configurada")
        flow = data.get("flowmeter", {})
        scale = float(flow.get("fator_escala", 0.0))
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("O fator de escala do flowmeter deve ser positivo e finito")
        if float(flow.get("timeout_s", 1.0)) < 0.75 or float(flow.get("timeout_s", 1.0)) > 1.5:
            raise ValueError("Timeout do flowmeter deve estar entre 0,75 e 1,5 s")
        if int(flow.get("intervalo_ms", 0)) < 125:
            raise ValueError("Intervalo do flowmeter deve ser de pelo menos 125 ms")

    @staticmethod
    def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                ConfigManager._deep_update(target[key], value)
            else:
                target[key] = value

    def save(self) -> None:
        self.validate(self.data)
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
        legacy = (
            Path(os.environ.get("LOCALAPPDATA", Path.home()))
            / "ISM"
            / "Porosimetro"
            / "data"
            / "porosimetro.db"
        )
        target = self.database_path
        if target.exists() or not legacy.exists():
            return None
        with sqlite3.connect(legacy) as source:
            result = source.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise OSError("Banco legado reprovado no PRAGMA integrity_check")
            backup_dir = legacy.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
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
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = backup_dir / f"{source.stem}_backup_{stamp}{source.suffix}"
        with (
            sqlite3.connect(source) as source_connection,
            sqlite3.connect(target) as target_connection,
        ):
            source_connection.backup(target_connection)
            result = target_connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise OSError("Falha na verificação de integridade do backup SQLite")
        keep = max(1, int(self.get("dados.retencao_backups", 10)))
        backups = sorted(backup_dir.glob(f"{source.stem}_backup_*{source.suffix}"), reverse=True)
        for old_backup in backups[keep:]:
            old_backup.unlink(missing_ok=True)
        return target

    def real_mode_errors(self) -> list[str]:
        """Retorna parâmetros obrigatórios ausentes sem inventar dados do equipamento."""
        errors: list[str] = []
        pressure = self.get("sensores.pressao", {})
        if pressure.get("limite_inferior") is None or pressure.get("limite_superior") is None:
            errors.append("Informe a faixa mínima e máxima do transdutor de pressão")
        elif float(pressure["limite_inferior"]) >= float(pressure["limite_superior"]):
            errors.append("A faixa de pressão é inválida")
        flow = self.get("flowmeter", {})
        if self.get("sensores.vazao.unidade") != FLOW_PROTOCOL_UNIT:
            errors.append(f"A unidade configurada do flowmeter deve ser {FLOW_PROTOCOL_UNIT}")
        required = (
            "porta",
            "baud_rate",
            "slave_id",
            "funcao",
            "registrador_inicial",
            "quantidade_registradores",
            "tipo_dado",
            "ordem_bytes",
            "fator_escala",
        )
        if not flow.get("configurado") or any(flow.get(key) is None for key in required):
            errors.append("Complete e confirme a configuração Modbus do flow meter")
        expected = {
            "baud_rate": 9600,
            "slave_id": 1,
            "funcao": 3,
            "registrador_inicial": 58,
            "quantidade_registradores": 2,
            "tipo_dado": "uint32",
            "ordem_bytes": "big",
            "fator_escala": 0.001,
        }
        if any(str(flow.get(key)).lower() != str(value).lower() for key, value in expected.items()):
            errors.append(
                "A configuração Modbus deve ser 9600 8N1, slave 1, função 03, registro 58, UINT32 big-endian / 1000"
            )
        if not self.get("comunicacao.porta"):
            errors.append("Selecione a porta serial do ESP32")
        if not flow.get("porta"):
            errors.append("Selecione a porta USB–RS485 do flowmeter")
        if flow.get("porta") and flow.get("porta") == self.get("comunicacao.porta"):
            errors.append("ESP32 e flowmeter devem usar portas COM diferentes")
        return errors
