#pragma once
#include <Arduino.h>

namespace HardwareConfig {
constexpr uint8_t RS485_RX_PIN = 16;
constexpr uint8_t RS485_TX_PIN = 17;
constexpr uint8_t RS485_DE_RE_PIN = 4;
constexpr uint8_t I2C_SDA_PIN = 21;
constexpr uint8_t I2C_SCL_PIN = 22;
constexpr uint8_t ADS1115_ADDRESS = 0x48;
constexpr uint8_t ADS1115_CHANNEL = 0;
constexpr float ADS1115_FULL_SCALE_V = 4.096F;  // GAIN_ONE, seguro até ±4,096 V
constexpr float SHUNT_OHM = 149.7F;
constexpr uint32_t ACQUISITION_INTERVAL_MS = 1000;
constexpr uint32_t USB_BAUD = 115200;
constexpr const char* FIRMWARE_VERSION = "2.0.0";
}
namespace PressureConfig {
// O firmware não converte pressão até estes valores serem confirmados.
constexpr bool CONFIGURED = false;
constexpr float MIN_VALUE = 0.0F;
constexpr float MAX_VALUE = 0.0F;
constexpr const char* UNIT = "UNCONFIGURED";
}

namespace FlowConfig {
// Preencher exclusivamente com o manual. Zero/UNKNOWN significa inválido.
constexpr bool CONFIGURED = false;
constexpr uint8_t SLAVE_ID = 0;
constexpr uint32_t BAUD_RATE = 0;
constexpr char PARITY = 'N';
constexpr uint8_t STOP_BITS = 0;
constexpr uint8_t FUNCTION_CODE = 0;
constexpr uint16_t START_REGISTER = 0;
constexpr uint16_t REGISTER_COUNT = 0;
constexpr float SCALE = 0.0F;
constexpr const char* DATA_TYPE = "UNKNOWN";
constexpr const char* BYTE_ORDER = "UNKNOWN";
constexpr const char* WORD_ORDER = "UNKNOWN";
constexpr const char* UNIT = "UNCONFIGURED";
constexpr uint16_t TIMEOUT_MS = 500;
constexpr uint8_t RETRIES = 3;
}
