#pragma once
#include <Adafruit_ADS1X15.h>
#include "SensorTypes.h"

class PressureSensor {
 public:
  bool begin();
  PressureReading read();
 private:
  Adafruit_ADS1115 ads_;
  bool available_ = false;
};
