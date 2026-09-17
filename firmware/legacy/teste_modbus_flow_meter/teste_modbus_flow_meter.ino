// LEGADO — NÃO USAR NO EQUIPAMENTO DE PRODUÇÃO.
// Teste histórico do flowmeter via ESP32/MAX3485, arquitetura substituída
// pela conexão direta PC -> USB-RS485. Os parâmetros abaixo não são os
// parâmetros validados do medidor atual.
// Abra o Monitor Serial em 115200 baud.
// Ajuste as constantes abaixo conforme o manual do flow meter.

#include <ModbusMaster.h>

constexpr int PINO_RS485_RX = 16;
constexpr int PINO_RS485_TX = 17;
constexpr int PINO_RS485_DE_RE = 4;

constexpr uint8_t MODBUS_SLAVE_ID = 1;
constexpr uint32_t MODBUS_BAUD_RATE = 9600;
constexpr uint32_t MODBUS_SERIAL_CONFIG = SERIAL_8N1;

// O endereço usado pela biblioteca começa em zero:
// 40001 ou 30001 no manual geralmente corresponde a 0.
constexpr uint16_t REGISTRADOR_VAZAO = 0x0000;

// true = Input Registers (função 04)
// false = Holding Registers (função 03)
constexpr bool REGISTRADOR_EH_INPUT = true;

// FLOAT32 usa dois registradores; UINT16 usa um.
enum class TipoDado : uint8_t { FLOAT32, UINT16, INT16, UINT32 };
constexpr TipoDado TIPO_DADO = TipoDado::FLOAT32;

// Alguns medidores enviam os dois words invertidos.
constexpr bool INVERTER_ORDEM_WORDS = false;

HardwareSerial serialModbus(2);
ModbusMaster modbus;

void habilitarTransmissao() {
  digitalWrite(PINO_RS485_DE_RE, HIGH);
}

void habilitarRecepcao() {
  digitalWrite(PINO_RS485_DE_RE, LOW);
}

uint8_t quantidadeRegistradores() {
  return (TIPO_DADO == TipoDado::FLOAT32 || TIPO_DADO == TipoDado::UINT32) ? 2 : 1;
}

float lerFloat32(uint16_t word0, uint16_t word1) {
  uint32_t bits = (static_cast<uint32_t>(word0) << 16) | word1;
  float valor;
  memcpy(&valor, &bits, sizeof(valor));
  return valor;
}

void setup() {
  Serial.begin(115200);
  pinMode(PINO_RS485_DE_RE, OUTPUT);
  habilitarRecepcao();

  serialModbus.begin(
      MODBUS_BAUD_RATE,
      MODBUS_SERIAL_CONFIG,
      PINO_RS485_RX,
      PINO_RS485_TX);

  modbus.begin(MODBUS_SLAVE_ID, serialModbus);
  modbus.preTransmission(habilitarTransmissao);
  modbus.postTransmission(habilitarRecepcao);

  Serial.println();
  Serial.println("=== TESTE MODBUS DO FLOW METER ===");
  Serial.println("Monitor Serial: 115200 baud");
}

void loop() {
  const uint8_t quantidade = quantidadeRegistradores();
  uint8_t resultado;

  if (REGISTRADOR_EH_INPUT) {
    resultado = modbus.readInputRegisters(REGISTRADOR_VAZAO, quantidade);
  } else {
    resultado = modbus.readHoldingRegisters(REGISTRADOR_VAZAO, quantidade);
  }

  Serial.print("ID=");
  Serial.print(MODBUS_SLAVE_ID);
  Serial.print(" registrador=0x");
  Serial.print(REGISTRADOR_VAZAO, HEX);
  Serial.print(" resposta=0x");
  Serial.println(resultado, HEX);

  if (resultado == ModbusMaster::ku8MBSuccess) {
    uint16_t word0 = modbus.getResponseBuffer(0);
    uint16_t word1 = quantidade == 2 ? modbus.getResponseBuffer(1) : 0;

    Serial.print("WORD0 decimal=");
    Serial.print(word0);
    Serial.print(" hex=0x");
    Serial.println(word0, HEX);

    if (quantidade == 2) {
      Serial.print("WORD1 decimal=");
      Serial.print(word1);
      Serial.print(" hex=0x");
      Serial.println(word1, HEX);
    }

    if (TIPO_DADO == TipoDado::FLOAT32) {
      float valor = INVERTER_ORDEM_WORDS
          ? lerFloat32(word1, word0)
          : lerFloat32(word0, word1);
      Serial.print("FLOAT32 = ");
      Serial.println(valor, 6);
    } else if (TIPO_DADO == TipoDado::UINT16) {
      Serial.print("UINT16 = ");
      Serial.println(word0);
    } else if (TIPO_DADO == TipoDado::INT16) {
      Serial.print("INT16 = ");
      Serial.println(static_cast<int16_t>(word0));
    } else {
      uint32_t valor = INVERTER_ORDEM_WORDS
          ? (static_cast<uint32_t>(word1) << 16) | word0
          : (static_cast<uint32_t>(word0) << 16) | word1;
      Serial.print("UINT32 = ");
      Serial.println(valor);
    }
  } else {
    Serial.println("Falha: sem leitura valida do flow meter.");
    Serial.println("Confira ID, baud/paridade, A/B, registrador e funcao 03/04.");
  }

  Serial.println("-----------------------------");
  delay(1000);
}
