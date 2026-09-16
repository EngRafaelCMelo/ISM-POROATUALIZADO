#include "PressureSensor.h"
#include "HardwareConfig.h"

bool PressureSensor::begin() {
  available_ = ads_.begin(HardwareConfig::ADS1115_ADDRESS);
  ads_.setGain(GAIN_ONE);
  return available_;
}
PressureReading PressureSensor::read() {
  PressureReading out;
  if (!available_) { out.alarm = "ADS1115_UNAVAILABLE"; return out; }
  out.raw = ads_.readADC_SingleEnded(HardwareConfig::ADS1115_CHANNEL);
  out.voltageV = ads_.computeVolts(out.raw);
  out.currentMa = out.voltageV / HardwareConfig::SHUNT_OHM * 1000.0F;
  if (!isfinite(out.voltageV) || !isfinite(out.currentMa) || out.currentMa < 3.6F || out.currentMa > 20.5F) {
    out.alarm = "PRESSURE_CURRENT_INVALID"; return out;
  }
  if (!PressureConfig::CONFIGURED || PressureConfig::MAX_VALUE <= PressureConfig::MIN_VALUE) {
    out.alarm = "PRESSURE_RANGE_UNCONFIGURED"; return out;
  }
  out.value = PressureConfig::MIN_VALUE + (out.currentMa - 4.0F) / 16.0F * (PressureConfig::MAX_VALUE - PressureConfig::MIN_VALUE);
  out.valid = isfinite(out.value) && out.currentMa >= 4.0F && out.currentMa <= 20.0F;
  if (!out.valid) out.alarm = "PRESSURE_INVALID";
  return out;
}
