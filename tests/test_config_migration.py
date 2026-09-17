from __future__ import annotations

import json

from config.settings import AppPaths, ConfigManager


def make_paths(tmp_path) -> AppPaths:
    paths = AppPaths(
        root=tmp_path,
        data=tmp_path / "data",
        logs=tmp_path / "logs",
        exports=tmp_path / "exports",
        config=tmp_path / "config",
    )
    for folder in (paths.data, paths.logs, paths.exports, paths.config):
        folder.mkdir()
    return paths


def test_corrupt_user_config_is_backed_up_and_reported(tmp_path) -> None:
    paths = make_paths(tmp_path)
    paths.config.joinpath("user_config.json").write_text("{invalid", encoding="utf-8")
    manager = ConfigManager(paths)
    assert manager.warnings
    assert list(paths.config.glob("user_config_corrompido_*.json"))
    assert json.loads(paths.config.joinpath("user_config.json").read_text(encoding="utf-8"))


def test_three_sensor_user_config_is_migrated(tmp_path) -> None:
    paths = make_paths(tmp_path)
    paths.config.joinpath("user_config.json").write_text(
        json.dumps(
            {
                "sensores": {
                    "pressao": {"limite_superior": 10.0},
                    "vazao_baixa": {"nome": "Vazão baixa"},
                    "vazao_alta": {"nome": "Vazão alta"},
                },
                "flow_meter": {"modo": "automatico"},
            }
        ),
        encoding="utf-8",
    )

    config = ConfigManager(paths).data

    assert config["sensores"]["pressao"]["limite_superior"] == 10.0
    assert config["sensores"]["pressao"]["alerta"] == 9.0
    assert config["sensores"]["pressao"]["critico"] == 10.0
    assert config["sensores"]["vazao"]["nome"] == "Vazão"
    assert "vazao_baixa" not in config["sensores"]
    assert "vazao_alta" not in config["sensores"]
    assert config["flowmeter"]["configurado"] is True
    assert config["flowmeter"]["modo"] == "automatico"
    saved = json.loads(paths.config.joinpath("user_config.json").read_text(encoding="utf-8"))
    assert set(saved["sensores"]) == {"pressao", "vazao"}
    assert saved["flowmeter"]["configurado"] is True
    assert "flow_meter" not in saved
