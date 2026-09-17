#pragma once
#include <Arduino.h>

namespace HardwareConfig {
constexpr uint8_t I2C_SDA_PIN = 21;
constexpr uint8_t I2C_SCL_PIN = 22;
constexpr uint8_t ADS1115_ADDRESS = 0x48;
constexpr uint8_t ADS1115_CHANNEL = 0;
constexpr float ADS1115_FULL_SCALE_V = 4.096F;  // GAIN_ONE, seguro até ±4,096 V
constexpr float SHUNT_OHM = 149.7F;
constexpr uint32_t ACQUISITION_INTERVAL_MS = 1000;
constexpr uint32_t PRESSURE_STALE_MS = 3000;
constexpr uint32_t ADS_RECONNECT_INTERVAL_MS = 5000;
constexpr uint32_t USB_BAUD = 115200;
constexpr const char* FIRMWARE_VERSION = "2.2.0";
}
namespace PressureConfig {
// Ajuste estes limites à faixa nominal gravada no transdutor instalado.
constexpr bool CONFIGURED = true;
constexpr float MIN_CURRENT_MA = 3.95F;
constexpr float MAX_CURRENT_MA = 20.0F;
constexpr float MIN_VALUE = 0.0F;
constexpr float MAX_VALUE = 400.0F;
constexpr const char* UNIT = "psi";
}
