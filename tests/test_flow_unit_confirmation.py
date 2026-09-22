from __future__ import annotations

import json

from communication.modbus import append_crc, parse_flow_response
from config.settings import AppPaths, ConfigManager
from ui.pages import SettingsPage


def _manager(tmp_path) -> ConfigManager:
    paths = AppPaths(
        tmp_path,
        tmp_path / "data",
        tmp_path / "logs",
        tmp_path / "exports",
        tmp_path / "config",
    )
    for folder in (paths.data, paths.logs, paths.exports, paths.config):
        folder.mkdir(exist_ok=True)
    return ConfigManager(paths)


def test_new_install_blocks_unconfirmed_flow_unit(tmp_path) -> None:
    manager = _manager(tmp_path)
    errors = manager.real_mode_errors()
    assert any("unidade" in error.lower() and "confirme" in error.lower() for error in errors)


def test_nl_min_requires_confirmed_references(tmp_path) -> None:
    manager = _manager(tmp_path)
    flow = manager.data["flowmeter"]
    flow.update({"unit": "NL/min", "unit_confirmed": True})
    manager.data["sensores"]["vazao"]["unidade"] = "NL/min"
    errors = manager.real_mode_errors()
    assert any("referências" in error for error in errors)
    assert any("pressão normal" in error for error in errors)
    assert any("temperatura normal" in error for error in errors)
    flow.update(
        {
            "normal_pressure_kpa_abs": 101.325,
            "normal_temperature_c": 0.0,
            "normal_reference_confirmed": True,
        }
    )
    assert not any("normal" in error.lower() for error in manager.real_mode_errors())


def test_parser_propagates_confirmed_unit() -> None:
    response = append_crc(bytes.fromhex("01 03 04 00 00 03 E8"))
    assert parse_flow_response(response, "mL/min").unit == "mL/min"


def test_settings_persists_flow_unit_fields(qt_application, config_data) -> None:
    page = SettingsPage(config_data)
    emitted = []
    page.save_requested.connect(emitted.append)
    page.flow_unit.setCurrentText("NL/min")
    page.flow_unit_confirmed.setChecked(True)
    page.normal_reference_confirmed.setChecked(True)
    page.normal_pressure.setValue(101.325)
    page.normal_temperature.setValue(0.0)
    page._save()
    flow = emitted[0]["flowmeter"]
    assert flow["unit"] == "NL/min"
    assert flow["unit_confirmed"] is True
    assert flow["normal_reference_confirmed"] is True
    assert emitted[0]["sensores"]["vazao"]["unidade"] == "NL/min"


def test_old_config_migrates_to_pending_confirmation(tmp_path) -> None:
    manager = _manager(tmp_path)
    legacy = json.loads(json.dumps(manager.data))
    legacy["flowmeter"].pop("unit_confirmed", None)
    legacy["flowmeter"].pop("unit", None)
    manager.user_path.write_text(json.dumps(legacy), encoding="utf-8")
    reloaded = ConfigManager(manager.paths)
    assert reloaded.get("flowmeter.unit_confirmed") is False
    assert reloaded.get("flowmeter.unit") in {"L/min", "NL/min", "mL/min"}
