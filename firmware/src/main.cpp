#include <Arduino.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include "HardwareConfig.h"
#include "PressureSensor.h"

PressureSensor pressureSensor;
uint32_t sequenceNumber = 0;
uint32_t lastPublishMs = 0;

void setup() {
  Serial.begin(HardwareConfig::USB_BAUD);
  Wire.begin(HardwareConfig::I2C_SDA_PIN, HardwareConfig::I2C_SCL_PIN);
  pressureSensor.begin();
}

void loop() {
  pressureSensor.task();
  const uint32_t now = millis();
  if (now - lastPublishMs < HardwareConfig::ACQUISITION_INTERVAL_MS) return;
  lastPublishMs = now;
  const PressureReading pressure = pressureSensor.latest();
  JsonDocument doc;
  doc["schema_version"] = 1;
  doc["timestamp_ms"] = now;
  doc["sequence"] = ++sequenceNumber;
  doc["firmware_version"] = HardwareConfig::FIRMWARE_VERSION;
  doc["pressao_raw"] = pressure.raw;
  if (isfinite(pressure.currentMa)) doc["pressao_ma"] = pressure.currentMa;
  else doc["pressao_ma"] = nullptr;
  if (pressure.valid) doc["pressao"] = pressure.value;
  else doc["pressao"] = nullptr;
  doc["pressao_unidade"] = PressureConfig::UNIT;
  doc["pressao_valida"] = pressure.valid;
  doc["pressao_status"] = pressure.valid ? "OK" : pressure.alarm;
  doc["status"] = pressure.valid ? "OK" : "PRESSURE_INVALID";
  serializeJson(doc, Serial);
  Serial.println();
}
