#include <Arduino.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include "FlowMeter.h"
#include "HardwareConfig.h"
#include "PressureSensor.h"

PressureSensor pressureSensor;
FlowMeter flowMeter;
uint32_t sequenceNumber = 0;
uint32_t lastPublishMs = 0;

void setup() {
  Serial.begin(HardwareConfig::USB_BAUD);
  Wire.begin(HardwareConfig::I2C_SDA_PIN, HardwareConfig::I2C_SCL_PIN);
  pressureSensor.begin(); flowMeter.begin();
}

void loop() {
  flowMeter.task();
  const uint32_t now = millis();
  if (now - lastPublishMs < HardwareConfig::ACQUISITION_INTERVAL_MS) return;
  lastPublishMs = now;
  const PressureReading pressure = pressureSensor.read();
  const FlowReading flow = flowMeter.latest();
  JsonDocument doc;
  doc["schema_version"] = 1; doc["sequence"] = sequenceNumber++; doc["uptime_ms"] = now;
  doc["firmware_version"] = HardwareConfig::FIRMWARE_VERSION;
  JsonObject p = doc["pressao"].to<JsonObject>(); p["ads_raw"] = pressure.raw; p["voltage_v"] = pressure.voltageV; p["current_ma"] = pressure.currentMa;
  if (pressure.valid) p["value"] = pressure.value; else p["value"] = nullptr;
  p["unit"] = PressureConfig::UNIT; p["valid"] = pressure.valid;
  JsonObject f = doc["vazao"].to<JsonObject>(); f["raw_register"] = flow.raw;
  if (flow.valid) f["value"] = flow.value; else f["value"] = nullptr;
  f["unit"] = FlowConfig::UNIT; f["valid"] = flow.valid; f["consecutive_failures"] = flow.consecutiveFailures;
  JsonArray alarms = doc["alarms"].to<JsonArray>(); if (pressure.alarm.length()) alarms.add(pressure.alarm); if (flow.alarm.length()) alarms.add(flow.alarm);
  doc["status"] = pressure.valid && flow.valid ? "OK" : "ERROR";
  serializeJson(doc, Serial); Serial.println();
}
