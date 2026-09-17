#include "PressureSensor.h"
#include "HardwareConfig.h"

bool PressureSensor::begin() {
  lastReconnectAttemptMs_ = millis();
  available_ = ads_.begin(HardwareConfig::ADS1115_ADDRESS);
  if (available_) {
    ads_.setGain(GAIN_ONE);
    ads_.setDataRate(RATE_ADS1115_128SPS);
    ads_.startADCReading(ADS1X15_REG_CONFIG_MUX_SINGLE_0, false);
    lastSampleMs_ = millis();
    reading_.valid = false;
    reading_.alarm = "WAITING_FOR_PRESSURE_SAMPLE";
  } else {
    reading_.valid = false;
    reading_.alarm = "ADS1115_UNAVAILABLE";
  }
  return available_;
}
void PressureSensor::task() {
  const uint32_t now = millis();
  if (!available_) {
    if (now - lastReconnectAttemptMs_ >= HardwareConfig::ADS_RECONNECT_INTERVAL_MS) begin();
    return;
  }
  if (!ads_.conversionComplete()) {
    if (now - lastSampleMs_ > HardwareConfig::PRESSURE_STALE_MS) {
      reading_.valid = false;
      reading_.alarm = "PRESSURE_STALE";
      available_ = false;
      lastReconnectAttemptMs_ = now;
    }
    return;
  }
  updateReading(ads_.getLastConversionResults());
  lastSampleMs_ = now;
  ads_.startADCReading(ADS1X15_REG_CONFIG_MUX_SINGLE_0, false);
}
void PressureSensor::updateReading(int16_t raw) {
  PressureReading out;
  out.raw = raw;
  out.voltageV = ads_.computeVolts(raw);
  out.currentMa = out.voltageV / HardwareConfig::SHUNT_OHM * 1000.0F;
  if (!isfinite(out.voltageV) || !isfinite(out.currentMa) || out.currentMa < 3.6F || out.currentMa > 20.5F) {
    out.alarm = "PRESSURE_CURRENT_INVALID"; reading_ = out; return;
  }
  if (!PressureConfig::CONFIGURED || PressureConfig::MAX_VALUE <= PressureConfig::MIN_VALUE) {
    out.alarm = "PRESSURE_RANGE_UNCONFIGURED"; reading_ = out; return;
  }
  out.value = PressureConfig::MIN_VALUE +
      (out.currentMa - PressureConfig::MIN_CURRENT_MA) /
      (PressureConfig::MAX_CURRENT_MA - PressureConfig::MIN_CURRENT_MA) *
      (PressureConfig::MAX_VALUE - PressureConfig::MIN_VALUE);
  out.valid = isfinite(out.value) && out.currentMa >= PressureConfig::MIN_CURRENT_MA &&
              out.currentMa <= PressureConfig::MAX_CURRENT_MA;
  if (!out.valid) out.alarm = "PRESSURE_INVALID";
  reading_ = out;
}
