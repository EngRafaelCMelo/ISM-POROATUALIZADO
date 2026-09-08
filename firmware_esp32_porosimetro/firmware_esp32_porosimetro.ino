#include <Adafruit_ADS1X15.h>
#include <ModbusMaster.h>
#include <Wire.h>
#include <cmath>
#include <cstring>

// ---------------------------------------------------------------------------
// Hardware
// ---------------------------------------------------------------------------
constexpr uint8_t PINO_I2C_SDA = 21;
constexpr uint8_t PINO_I2C_SCL = 22;
constexpr uint8_t ENDERECO_ADS1115 = 0x48;
constexpr uint8_t CANAL_PRESSAO_ADS1115 = 0;

constexpr uint8_t PINO_RS485_RX = 16;       // RO do MAX3485
constexpr uint8_t PINO_RS485_TX = 17;       // DI do MAX3485
constexpr uint8_t PINO_RS485_DE_RE = 4;     // DE e /RE unidos

// Resistor de medicao do laco 4-20 mA. O valor recomendado e 150 ohms, 0,1%.
// Com ele, 4-20 mA correspondem a 0,6-3,0 V no ADS1115.
constexpr float RESISTOR_SHUNT_OHM = 150.0f;
constexpr float PRESSAO_MIN_BAR = 0.0f;
constexpr float PRESSAO_MAX_BAR = 100.0f;
constexpr float CORRENTE_MIN_MA = 4.0f;
constexpr float CORRENTE_MAX_MA = 20.0f;

// ---------------------------------------------------------------------------
// Flow meter Modbus RTU - CONFIRA ESTES VALORES NO MANUAL DO SEU MEDIDOR.
// O endereco de registrador usado pela biblioteca e baseado em zero. Assim,
// o registrador 30001/40001 do manual normalmente deve ser configurado como 0.
// ---------------------------------------------------------------------------
constexpr uint8_t MODBUS_SLAVE_ID = 1;
constexpr uint32_t MODBUS_BAUD_RATE = 9600;
constexpr uint32_t MODBUS_SERIAL_CONFIG = SERIAL_8N1;
constexpr uint16_t REGISTRADOR_VAZAO = 0x0000;
constexpr bool REGISTRADOR_EH_INPUT = true;

enum class TipoDadoVazao : uint8_t {
  FLOAT32,
  UINT16,
  INT16,
  UINT32,
};

constexpr TipoDadoVazao TIPO_DADO_VAZAO = TipoDadoVazao::FLOAT32;
constexpr bool INVERTER_ORDEM_WORDS = false;
constexpr bool INVERTER_BYTES_NO_WORD = false;
constexpr float ESCALA_VAZAO = 1.0f;
constexpr float OFFSET_VAZAO = 0.0f;
constexpr float VAZAO_MIN_L_MIN = 0.0f;
constexpr float VAZAO_MAX_L_MIN = 5.0f;

constexpr uint32_t INTERVALO_ENVIO_MS = 1000;
constexpr uint8_t AMOSTRAS_PRESSAO = 5;

Adafruit_ADS1115 ads;
ModbusMaster modbus;
HardwareSerial serialModbus(2);

bool adsDisponivel = false;
uint32_t ultimaTentativaAdsMs = 0;
uint32_t ultimoEnvioMs = 0;
uint32_t sequencia = 0;

void habilitarTransmissaoRs485() {
  digitalWrite(PINO_RS485_DE_RE, HIGH);
  delayMicroseconds(50);
}

void habilitarRecepcaoRs485() {
  delayMicroseconds(50);
  digitalWrite(PINO_RS485_DE_RE, LOW);
}

uint16_t inverterBytes(uint16_t valor) {
  return static_cast<uint16_t>((valor << 8) | (valor >> 8));
}

uint8_t quantidadeRegistradoresVazao() {
  return TIPO_DADO_VAZAO == TipoDadoVazao::UINT16 ||
                 TIPO_DADO_VAZAO == TipoDadoVazao::INT16
             ? 1
             : 2;
}

bool inicializarAds1115() {
  if (!ads.begin(ENDERECO_ADS1115, &Wire)) {
    return false;
  }
  // +/- 4,096 V. Com ADS1115 alimentado em 3,3 V, nunca exceda VDD no A0.
  ads.setGain(GAIN_ONE);
  ads.setDataRate(RATE_ADS1115_128SPS);
  return true;
}

bool lerPressao(float &correnteMa, float &pressaoBar) {
  if (!adsDisponivel) {
    const uint32_t agora = millis();
    if (agora - ultimaTentativaAdsMs < 5000) {
      return false;
    }
    ultimaTentativaAdsMs = agora;
    adsDisponivel = inicializarAds1115();
    if (!adsDisponivel) {
      return false;
    }
  }

  int32_t soma = 0;
  for (uint8_t indice = 0; indice < AMOSTRAS_PRESSAO; ++indice) {
    soma += ads.readADC_SingleEnded(CANAL_PRESSAO_ADS1115);
  }
  const int16_t mediaBruta = static_cast<int16_t>(soma / AMOSTRAS_PRESSAO);
  const float tensao = ads.computeVolts(mediaBruta);
  correnteMa = tensao * 1000.0f / RESISTOR_SHUNT_OHM;
  pressaoBar = PRESSAO_MIN_BAR +
               ((correnteMa - CORRENTE_MIN_MA) /
                (CORRENTE_MAX_MA - CORRENTE_MIN_MA)) *
                   (PRESSAO_MAX_BAR - PRESSAO_MIN_BAR);
  return std::isfinite(correnteMa) && std::isfinite(pressaoBar);
}

float decodificarVazao(uint16_t primeiroWord, uint16_t segundoWord) {
  if (INVERTER_BYTES_NO_WORD) {
    primeiroWord = inverterBytes(primeiroWord);
    segundoWord = inverterBytes(segundoWord);
  }
  if (INVERTER_ORDEM_WORDS) {
    const uint16_t temporario = primeiroWord;
    primeiroWord = segundoWord;
    segundoWord = temporario;
  }

  float valor = 0.0f;
  switch (TIPO_DADO_VAZAO) {
    case TipoDadoVazao::FLOAT32: {
      const uint32_t bits =
          (static_cast<uint32_t>(primeiroWord) << 16) | segundoWord;
      std::memcpy(&valor, &bits, sizeof(valor));
      break;
    }
    case TipoDadoVazao::UINT16:
      valor = static_cast<float>(primeiroWord);
      break;
    case TipoDadoVazao::INT16:
      valor = static_cast<float>(static_cast<int16_t>(primeiroWord));
      break;
    case TipoDadoVazao::UINT32: {
      const uint32_t inteiro =
          (static_cast<uint32_t>(primeiroWord) << 16) | segundoWord;
      valor = static_cast<float>(inteiro);
      break;
    }
  }
  return valor * ESCALA_VAZAO + OFFSET_VAZAO;
}

bool lerVazao(float &vazaoLMin, uint8_t &resultadoModbus) {
  const uint8_t quantidade = quantidadeRegistradoresVazao();
  resultadoModbus = REGISTRADOR_EH_INPUT
                        ? modbus.readInputRegisters(REGISTRADOR_VAZAO, quantidade)
                        : modbus.readHoldingRegisters(REGISTRADOR_VAZAO, quantidade);
  if (resultadoModbus != ModbusMaster::ku8MBSuccess) {
    return false;
  }

  const uint16_t primeiro = modbus.getResponseBuffer(0);
  const uint16_t segundo = quantidade == 2 ? modbus.getResponseBuffer(1) : 0;
  vazaoLMin = decodificarVazao(primeiro, segundo);
  return std::isfinite(vazaoLMin);
}

void imprimirNumeroOuNull(float valor, bool disponivel, uint8_t casas) {
  if (disponivel && std::isfinite(valor)) {
    Serial.print(valor, casas);
  } else {
    Serial.print("null");
  }
}

void enviarMedicao() {
  float correntePressaoMa = NAN;
  float pressaoBar = NAN;
  float vazaoLMin = NAN;
  uint8_t resultadoModbus = 0xFF;

  const bool pressaoDisponivel = lerPressao(correntePressaoMa, pressaoBar);
  const bool vazaoDisponivel = lerVazao(vazaoLMin, resultadoModbus);
  const bool correntePressaoNominal =
      pressaoDisponivel && correntePressaoMa >= 3.6f && correntePressaoMa <= 20.5f;
  const bool vazaoNaFaixa = vazaoDisponivel && vazaoLMin >= VAZAO_MIN_L_MIN &&
                            vazaoLMin <= VAZAO_MAX_L_MIN;

  const char *statusGeral = "OK";
  if (!pressaoDisponivel && !vazaoDisponivel) {
    statusGeral = "FALHA_SENSORES";
  } else if (!pressaoDisponivel) {
    statusGeral = "PARCIAL_SEM_PRESSAO";
  } else if (!vazaoDisponivel) {
    statusGeral = "PARCIAL_SEM_VAZAO";
  } else if (!correntePressaoNominal || !vazaoNaFaixa) {
    statusGeral = "ALERTA_SENSOR";
  }

  char statusVazao[32];
  if (!vazaoDisponivel) {
    if (resultadoModbus == ModbusMaster::ku8MBSuccess) {
      snprintf(statusVazao, sizeof(statusVazao), "DADO_INVALIDO");
    } else {
      snprintf(statusVazao, sizeof(statusVazao), "ERRO_MODBUS_0x%02X",
               resultadoModbus);
    }
  } else if (!vazaoNaFaixa) {
    snprintf(statusVazao, sizeof(statusVazao), "FORA_FAIXA");
  } else {
    snprintf(statusVazao, sizeof(statusVazao), "OK");
  }

  Serial.print("{\"timestamp_ms\":");
  Serial.print(millis());
  Serial.print(",\"sequence\":");
  Serial.print(++sequencia);
  Serial.print(",\"pressao_ma\":");
  imprimirNumeroOuNull(correntePressaoMa, pressaoDisponivel, 3);
  Serial.print(",\"pressao\":");
  imprimirNumeroOuNull(pressaoBar, pressaoDisponivel, 3);
  Serial.print(",\"pressao_status\":\"");
  Serial.print(!pressaoDisponivel
                   ? "ADS1115_INDISPONIVEL"
                   : (correntePressaoNominal ? "OK" : "CORRENTE_FORA_FAIXA"));
  Serial.print("\",\"vazao\":");
  imprimirNumeroOuNull(vazaoLMin, vazaoDisponivel, 5);
  Serial.print(",\"vazao_status\":\"");
  Serial.print(statusVazao);
  Serial.print("\",\"status\":\"");
  Serial.print(statusGeral);
  Serial.println("\"}");
}

void setup() {
  // Esta porta deve transportar apenas uma linha JSON por medicao.
  Serial.begin(115200);
  Wire.begin(PINO_I2C_SDA, PINO_I2C_SCL);
  adsDisponivel = inicializarAds1115();

  pinMode(PINO_RS485_DE_RE, OUTPUT);
  digitalWrite(PINO_RS485_DE_RE, LOW);
  serialModbus.begin(MODBUS_BAUD_RATE, MODBUS_SERIAL_CONFIG, PINO_RS485_RX,
                     PINO_RS485_TX);
  modbus.begin(MODBUS_SLAVE_ID, serialModbus);
  modbus.preTransmission(habilitarTransmissaoRs485);
  modbus.postTransmission(habilitarRecepcaoRs485);
}

void loop() {
  const uint32_t agora = millis();
  if (agora - ultimoEnvioMs >= INTERVALO_ENVIO_MS) {
    ultimoEnvioMs = agora;
    enviarMedicao();
  }
  delay(2);
}
