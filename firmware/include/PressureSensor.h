#pragma once
#include <Adafruit_ADS1X15.h>
#include "SensorTypes.h"

class PressureSensor {
 public:
  bool begin();
  void task();
  PressureReading latest() const { return reading_; }
 private:
  void updateReading(int16_t raw);
  Adafruit_ADS1115 ads_;
  bool available_ = false;
  uint32_t lastSampleMs_ = 0;
  uint32_t lastReconnectAttemptMs_ = 0;
  PressureReading reading_;
};
