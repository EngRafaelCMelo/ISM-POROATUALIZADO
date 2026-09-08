from __future__ import annotations
import json
from core.constants import ReadingQuality
from communication.protocol_parser import ProtocolParser

def test_schema_one_firmware_object_message_preserves_metadata(config_data):
    config_data["sensores"]["pressao"].update({"limite_inferior": 0.0, "limite_superior": 100.0})
    raw=json.dumps({"schema_version":1,"sequence":7,"timestamp_ms":123,"firmware_version":"2.0.0","pressao":{"value":50,"unit":"bar","valid":True,"current_ma":12},"vazao":{"value":1.2,"unit":"L/min","valid":True},"status":"OK"})
    measurement=ProtocolParser(config_data["sensores"],"software").parse(raw)
    assert measurement.sequence == 7 and measurement.firmware_version == "2.0.0"
    assert measurement.pressure.value == 50 and measurement.pressure.valid
    assert measurement.flow.unit == "L/min" and measurement.flow.valid

def test_current_calibration_is_applied_to_current_not_engineering_value(config_data):
    pressure=config_data["sensores"]["pressao"]
    pressure.update({"limite_inferior":0,"limite_superior":100,"calibracao_tipo":"corrente_para_engenharia","ganho":6.25,"offset":-25})
    reading=ProtocolParser(config_data["sensores"],"software").parse('{"pressao":{"current_ma":12,"valid":true}}').pressure
    assert reading.value == 50 and reading.quality == ReadingQuality.VALID
