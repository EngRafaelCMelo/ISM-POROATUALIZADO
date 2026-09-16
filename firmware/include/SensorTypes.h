#pragma once
#include <Arduino.h>

struct PressureReading { int16_t raw = 0; float voltageV = NAN; float currentMa = NAN; float value = NAN; bool valid = false; String alarm; };
struct FlowReading { uint32_t raw = 0; float value = NAN; bool valid = false; uint32_t consecutiveFailures = 0; String alarm; };
