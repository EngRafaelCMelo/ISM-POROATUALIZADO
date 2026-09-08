"""Parser do protocolo JSON por linha, schema 1, com compatibilidade plana."""
from __future__ import annotations
import json
from datetime import datetime
from typing import Any
from core.calculations import current_to_engineering
from core.constants import ReadingQuality, SENSOR_KEYS, SENSOR_MA_KEYS
from core.models import Measurement, SensorReading
from core.validation import classify_current, classify_value, optional_number

class ProtocolError(ValueError): pass

class ProtocolParser:
    def __init__(self, sensor_config: dict[str, dict[str, Any]], value_source: str="comparar"):
        self.sensor_config=sensor_config; self.value_source=value_source
    def parse(self, raw:str, simulated:bool=False)->Measurement:
        try: payload=json.loads(raw.strip())
        except json.JSONDecodeError as exc: raise ProtocolError(f"JSON inválido: {exc.msg}") from exc
        if not isinstance(payload,dict): raise ProtocolError("A mensagem precisa ser um objeto JSON")
        payload=dict(payload)
        if "vazao" not in payload and "vazao_baixa" in payload: payload["vazao"]=payload["vazao_baixa"]
        if "vazao_status" not in payload and "vazao_baixa_status" in payload: payload["vazao_status"]=payload["vazao_baixa_status"]
        if "vazao_ma" not in payload and "vazao_baixa_ma" in payload: payload["vazao_ma"]=payload["vazao_baixa_ma"]
        readings={key:self._reading(key,payload.get(key),payload.get(SENSOR_MA_KEYS[key]),payload.get(f"{key}_status"),simulated) for key in SENSOR_KEYS}
        if all(r.value is None and r.current_ma is None for r in readings.values()): raise ProtocolError("Nenhum campo de sensor reconhecido")
        try: timestamp=int(payload["timestamp_ms"]) if payload.get("timestamp_ms") is not None else None
        except (ValueError,TypeError) as exc: raise ProtocolError("timestamp_ms inválido") from exc
        return Measurement(received_at=datetime.now(),device_timestamp_ms=timestamp,pressure=readings["pressao"],flow=readings["vazao"],communication_state=str(payload.get("status","OK")),raw_message=raw.strip(),simulated=simulated,sequence=self._number(payload.get("sequence"),int),schema_version=self._number(payload.get("schema_version"),int),firmware_version=str(payload.get("firmware_version","")))
    @staticmethod
    def _number(value:Any, kind:type):
        try:return kind(value) if value is not None else None
        except (ValueError,TypeError):return None
    def _reading(self,key:str, raw:Any, current_raw:Any,status:Any,simulated:bool)->SensorReading:
        # Firmware schema 1: {value, unit, valid, current_ma}; formato plano continua aceito.
        if isinstance(raw,dict):
            current_raw=raw.get("current_ma",current_raw); status=raw.get("status",status); device_raw=raw.get("value"); unit=str(raw.get("unit", "")); declared=raw.get("valid")
        else: device_raw=raw; unit=""; declared=None
        try: device=optional_number(device_raw); current=optional_number(current_raw)
        except (ValueError,TypeError) as exc: raise ProtocolError(f"Campo numérico inválido em {key}") from exc
        cfg=self.sensor_config[key]; lower,upper=cfg.get("limite_inferior"),cfg.get("limite_superior"); configured=lower is not None and upper is not None
        calculated=None
        if current is not None and configured:
            # Calibrações novas são corrente→engenharia; não aplique após a conversão nominal.
            if cfg.get("calibracao_tipo") == "corrente_para_engenharia": calculated=float(cfg.get("ganho",1))*current+float(cfg.get("offset",0))
            else: calculated=current_to_engineering(current,float(lower),float(upper),float(cfg.get("corrente_min",4)),float(cfg.get("corrente_max",20)))
        value=calculated if self.value_source=="software" and calculated is not None else (device if device is not None else calculated)
        quality=classify_current(current,simulated)
        if current is None and value is not None: quality=ReadingQuality.SIMULATED if simulated else ReadingQuality.VALID
        if declared is False: quality=ReadingQuality.INVALID; value=None
        if configured and value is not None: quality=classify_value(value,float(lower),float(upper),quality)
        if self.value_source=="comparar" and device is not None and calculated is not None and quality != ReadingQuality.INVALID and abs(device-calculated)>float(cfg.get("tolerancia",0)): quality=ReadingQuality.WARNING
        return SensorReading(value=value,current_ma=current,quality=quality,device_value=device,calculated_value=calculated,device_status=str(status or ""),unit=unit or str(cfg.get("unidade", "")),valid=quality not in (ReadingQuality.INVALID,ReadingQuality.MISSING))
