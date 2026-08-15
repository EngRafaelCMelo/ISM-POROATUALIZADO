#pragma once
#include <ModbusRTU.h>
#include "SensorTypes.h"

class FlowMeter {
 public:
  bool begin();
  void task();
  FlowReading latest() const { return reading_; }
 private:
  static bool onResult(Modbus::ResultCode event, uint16_t transactionId, void* data);
  void request();
  ModbusRTU modbus_;
  FlowReading reading_;
  uint16_t registers_[4] = {};
  uint32_t lastRequestMs_ = 0;
  bool pending_ = false;
};
