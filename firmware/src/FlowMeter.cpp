#include "FlowMeter.h"
#include "HardwareConfig.h"

bool FlowMeter::begin() {
  pinMode(HardwareConfig::RS485_DE_RE_PIN, OUTPUT);
  digitalWrite(HardwareConfig::RS485_DE_RE_PIN, LOW);
  if (!FlowConfig::CONFIGURED || FlowConfig::BAUD_RATE == 0 || FlowConfig::REGISTER_COUNT == 0) {
    reading_.alarm = "MODBUS_UNCONFIGURED"; return false;
  }
  Serial2.begin(FlowConfig::BAUD_RATE, SERIAL_8N1, HardwareConfig::RS485_RX_PIN, HardwareConfig::RS485_TX_PIN);
  modbus_.begin(&Serial2, HardwareConfig::RS485_DE_RE_PIN);
  modbus_.master();
  return true;
}
void FlowMeter::task() {
  modbus_.task();
  if (!FlowConfig::CONFIGURED) return;
  if (!pending_ && millis() - lastRequestMs_ >= HardwareConfig::ACQUISITION_INTERVAL_MS) request();
}

void FlowMeter::request() {
  lastRequestMs_ = millis(); pending_ = true;
  bool queued = false;
  if (FlowConfig::FUNCTION_CODE == 3) queued = modbus_.readHreg(FlowConfig::SLAVE_ID, FlowConfig::START_REGISTER, registers_, FlowConfig::REGISTER_COUNT, onResult, this);
  else if (FlowConfig::FUNCTION_CODE == 4) queued = modbus_.readIreg(FlowConfig::SLAVE_ID, FlowConfig::START_REGISTER, registers_, FlowConfig::REGISTER_COUNT, onResult, this);
  if (!queued) { pending_ = false; reading_.valid = false; reading_.consecutiveFailures++; reading_.alarm = "MODBUS_REQUEST_FAILED"; }
}

bool FlowMeter::onResult(Modbus::ResultCode event, uint16_t, void* data) {
  auto* self = static_cast<FlowMeter*>(data); self->pending_ = false;
  if (event != Modbus::EX_SUCCESS) { self->reading_.valid = false; self->reading_.consecutiveFailures++; self->reading_.alarm = event == Modbus::EX_TIMEOUT ? "MODBUS_TIMEOUT" : "MODBUS_INVALID_RESPONSE"; return true; }
  // A decodificação só é liberada após tipo/ordens serem confirmados no manual.
  if (String(FlowConfig::DATA_TYPE) != "UINT16" || FlowConfig::REGISTER_COUNT != 1 || FlowConfig::SCALE == 0.0F) {
    self->reading_.valid = false; self->reading_.alarm = "MODBUS_FORMAT_UNSUPPORTED_OR_UNCONFIGURED"; return true;
  }
  self->reading_.raw = self->registers_[0]; self->reading_.value = self->reading_.raw * FlowConfig::SCALE;
  self->reading_.valid = isfinite(self->reading_.value); self->reading_.consecutiveFailures = 0; self->reading_.alarm = "";
  return true;
}
