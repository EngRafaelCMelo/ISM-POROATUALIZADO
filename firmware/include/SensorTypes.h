#pragma once
#include <Arduino.h>

struct PressureReading { int16_t raw = 0; float voltageV = NAN; float currentMa = NAN; float value = NAN; bool valid = false; String alarm; };
