from __future__ import annotations

import json

from config.settings import AppPaths, ConfigManager


def test_three_sensor_user_config_is_migrated(tmp_path) -> None:
    paths = AppPaths(
        root=tmp_path,
        data=tmp_path / "data",
        logs=tmp_path / "logs",
        exports=tmp_path / "exports",
        config=tmp_path / "config",
    )
    for folder in (paths.data, paths.logs, paths.exports, paths.config):
        folder.mkdir()
    paths.config.joinpath("user_config.json").write_text(
        json.dumps({
            "sensores": {
                "pressao": {"limite_superior": 10.0},
                "vazao_baixa": {"nome": "Vazão baixa"},
                "vazao_alta": {"nome": "Vazão alta"},
            },
            "flow_meter": {"modo": "automatico"},
        }),
        encoding="utf-8",
    )

    config = ConfigManager(paths).data

    assert config["sensores"]["pressao"]["limite_superior"] == 10.0
    assert config["sensores"]["vazao"]["nome"] == "Vazão"
    assert "vazao_baixa" not in config["sensores"]
    assert "vazao_alta" not in config["sensores"]
    assert config["flow_meter"]["configurado"] is False
    saved = json.loads(paths.config.joinpath("user_config.json").read_text(encoding="utf-8"))
    assert set(saved["sensores"]) == {"pressao", "vazao"}
    assert saved["flow_meter"]["configurado"] is False
