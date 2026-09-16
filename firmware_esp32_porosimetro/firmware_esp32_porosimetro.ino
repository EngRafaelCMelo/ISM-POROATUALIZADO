#include <Adafruit_ADS1X15.h>
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

// Resistor de medicao do laco 4-20 mA. O valor recomendado e 150 ohms, 0,1%.
// Com ele, 4-20 mA correspondem a 0,6-3,0 V no ADS1115.
constexpr float RESISTOR_SHUNT_OHM = 150.0f;
constexpr float PRESSAO_MIN_BAR = 0.0f;
constexpr float PRESSAO_MAX_BAR = 100.0f;
constexpr float CORRENTE_MIN_MA = 4.0f;
constexpr float CORRENTE_MAX_MA = 20.0f;

// ---------------------------------------------------------------------------
// Flow meter Modbus RTU.
// Vazao nos Holding Registers 0x003A e 0x003B, UINT32 big-endian,
// em milésimos de L/min.
// ---------------------------------------------------------------------------
constexpr uint8_t MODBUS_SLAVE_ID = 1;
constexpr uint32_t MODBUS_BAUD_RATE = 9600;
constexpr uint32_t MODBUS_SERIAL_CONFIG = SERIAL_8N1;
constexpr uint16_t REGISTRADOR_VAZAO = 0x003A;
constexpr uint8_t QUANTIDADE_REGISTRADORES_VAZAO = 2;

enum class TipoDadoVazao : uint8_t {
  FLOAT32,
  UINT16,
  INT16,
  UINT32,
};

constexpr TipoDadoVazao TIPO_DADO_VAZAO = TipoDadoVazao::UINT32;
constexpr bool INVERTER_ORDEM_WORDS = false;
constexpr bool INVERTER_BYTES_NO_WORD = false;
constexpr float ESCALA_VAZAO = 0.001f;
constexpr float OFFSET_VAZAO = 0.0f;
constexpr float VAZAO_MIN_L_MIN = 0.0f;
constexpr float VAZAO_MAX_L_MIN = 5.0f;

constexpr uint32_t INTERVALO_ENVIO_MS = 1000;
constexpr uint8_t AMOSTRAS_PRESSAO = 5;

Adafruit_ADS1115 ads;
HardwareSerial serialModbus(2);

bool adsDisponivel = false;
uint32_t ultimaTentativaAdsMs = 0;
uint32_t ultimoEnvioMs = 0;
uint32_t sequencia = 0;

uint16_t inverterBytes(uint16_t valor) {
  return static_cast<uint16_t>((valor << 8) | (valor >> 8));
}

uint8_t quantidadeRegistradoresVazao() {
  return QUANTIDADE_REGISTRADORES_VAZAO;
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

uint16_t crc16Modbus(const uint8_t *dados, size_t quantidade) {
  uint16_t crc = 0xFFFF;
  for (size_t indice = 0; indice < quantidade; ++indice) {
    crc ^= dados[indice];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
    }
  }
  return crc;
}

void imprimirBytesModbus(const uint8_t *dados, size_t quantidade) {
  Serial.print("bytes recebidos: ");
  if (quantidade == 0) {
    Serial.print("(nenhum)");
  }
  for (size_t indice = 0; indice < quantidade; ++indice) {
    if (indice > 0) Serial.print(' ');
    if (dados[indice] < 0x10) Serial.print('0');
    Serial.print(dados[indice], HEX);
  }
  Serial.print(" | quantidade: ");
  Serial.println(quantidade);
}

size_t consultarFrameModbus(const char *nome, const uint8_t *frame, size_t tamanho,
                            uint8_t *resposta, size_t capacidadeResposta) {
  Serial.print("TX UART2 ");
  Serial.print(nome);
  Serial.print(": ");
  for (size_t indice = 0; indice < tamanho; ++indice) {
    if (indice > 0) Serial.print(' ');
    if (frame[indice] < 0x10) Serial.print('0');
    Serial.print(frame[indice], HEX);
  }
  Serial.println();

  serialModbus.write(frame, tamanho);
  serialModbus.flush();
  const uint32_t inicioResposta = millis();

  size_t quantidadeRecebida = 0;
  while (millis() - inicioResposta < 1500) {
    while (serialModbus.available() && quantidadeRecebida < capacidadeResposta) {
      resposta[quantidadeRecebida++] = static_cast<uint8_t>(serialModbus.read());
    }
    delay(1);
  }
  imprimirBytesModbus(resposta, quantidadeRecebida);
  return quantidadeRecebida;
}

bool lerVazao(float &vazaoLMin, uint8_t &resultadoModbus) {
  // Frame RTU fixo: funcao 03.
  // O modulo RS-485 faz a troca TX/RX automaticamente; nao ha DE/RE.
  const uint8_t frame03[] = {0x01, 0x03, 0x00, 0x3A, 0x00, 0x02, 0xE4, 0x06};
  uint8_t resposta03[32] = {};

  const size_t quantidade03 = consultarFrameModbus("funcao 03", frame03, sizeof(frame03),
                                                   resposta03, sizeof(resposta03));
  if (quantidade03 == 0) {
    resultadoModbus = 0xE2;
    Serial.println("timeout Modbus");
  } else if (quantidade03 < 5) {
    resultadoModbus = 0xE1;
    Serial.println("erro Modbus: resposta incompleta");
  } else {
    const uint16_t crcRecebido = static_cast<uint16_t>(resposta03[quantidade03 - 2]) |
                                  (static_cast<uint16_t>(resposta03[quantidade03 - 1]) << 8);
    const uint16_t crcCalculado = crc16Modbus(resposta03, quantidade03 - 2);
    const bool crcValido = crcRecebido == crcCalculado;
    Serial.print("CRC funcao 03: ");
    Serial.println(crcValido ? "valido" : "invalido");
    if (!crcValido) {
      resultadoModbus = 0xE3;
      Serial.println("erro Modbus: CRC invalido");
    } else if (resposta03[0] != 0x01 || resposta03[1] != 0x03 ||
               resposta03[2] != 4 || quantidade03 != 9) {
      resultadoModbus = 0xE4;
      Serial.println("erro Modbus: resposta inesperada");
    } else {
      const uint16_t reg0 = (static_cast<uint16_t>(resposta03[3]) << 8) | resposta03[4];
      const uint16_t reg1 = (static_cast<uint16_t>(resposta03[5]) << 8) | resposta03[6];
      const uint32_t bruto = (static_cast<uint32_t>(reg0) << 16) | reg1;
      vazaoLMin = static_cast<float>(bruto) / 1000.0f;
      Serial.print("reg0=0x"); Serial.print(reg0, HEX);
      Serial.print(" reg1=0x"); Serial.print(reg1, HEX);
      Serial.print(" bruto="); Serial.print(bruto);
      Serial.print(" vazao_l_min="); Serial.println(vazaoLMin, 3);
      resultadoModbus = 0;
    }
  }

  return resultadoModbus == 0 && std::isfinite(vazaoLMin);
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
    if (resultadoModbus == 0) {
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
  Serial.print(",\"flowmeter_ok\":");
  Serial.print(vazaoDisponivel ? "true" : "false");
  Serial.print(",\"vazao_l_min\":");
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

  serialModbus.begin(MODBUS_BAUD_RATE, MODBUS_SERIAL_CONFIG, PINO_RS485_RX,
                     PINO_RS485_TX);
}

void loop() {
  const uint32_t agora = millis();
  if (agora - ultimoEnvioMs >= INTERVALO_ENVIO_MS) {
    ultimoEnvioMs = agora;
    enviarMedicao();
  }
  delay(2);
}
