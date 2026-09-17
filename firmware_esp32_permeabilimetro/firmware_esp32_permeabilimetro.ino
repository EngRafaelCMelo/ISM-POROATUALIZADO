#include <Adafruit_ADS1X15.h>
#include <Wire.h>
#include <cmath>

constexpr uint8_t PINO_I2C_SDA = 21;
constexpr uint8_t PINO_I2C_SCL = 22;
constexpr uint8_t ENDERECO_ADS1115 = 0x48;
constexpr float RESISTOR_SHUNT_OHM = 149.7f;
constexpr float PRESSAO_MIN_PSI = 0.0f;
constexpr float PRESSAO_MAX_PSI = 400.0f;
constexpr float CORRENTE_ZERO_MA = 3.95f;
constexpr float CORRENTE_FUNDO_ESCALA_MA = 20.0f;
constexpr uint32_t INTERVALO_ENVIO_MS = 1000;
constexpr uint32_t INTERVALO_RECONEXAO_MS = 5000;
constexpr uint32_t LIMITE_AMOSTRA_DESATUALIZADA_MS = 3000;
constexpr const char *VERSAO_FIRMWARE = "2.2.0";

Adafruit_ADS1115 ads;
bool adsDisponivel = false;
int16_t ultimoRaw = 0;
float ultimaCorrenteMa = NAN;
float ultimaPressaoPsi = NAN;
bool ultimaPressaoValida = false;
const char *ultimoStatus = "ADS1115_UNAVAILABLE";
uint32_t ultimoEnvioMs = 0;
uint32_t ultimaTentativaAdsMs = 0;
uint32_t ultimaAmostraAdsMs = 0;
uint32_t sequencia = 0;

bool inicializarAds1115() {
  if (!ads.begin(ENDERECO_ADS1115, &Wire)) return false;
  ads.setGain(GAIN_ONE);
  ads.setDataRate(RATE_ADS1115_128SPS);
  ads.startADCReading(ADS1X15_REG_CONFIG_MUX_SINGLE_0, false);
  return true;
}

void atualizarPressaoNaoBloqueante() {
  if (!adsDisponivel) {
    const uint32_t agora = millis();
    if (agora - ultimaTentativaAdsMs >= INTERVALO_RECONEXAO_MS) {
      ultimaTentativaAdsMs = agora;
      adsDisponivel = inicializarAds1115();
      if (adsDisponivel) ultimaAmostraAdsMs = agora;
      ultimoStatus = adsDisponivel ? "AGUARDANDO_AMOSTRA" : "ADS1115_UNAVAILABLE";
    }
    return;
  }
  if (!ads.conversionComplete()) {
    const uint32_t agora = millis();
    if (agora - ultimaAmostraAdsMs > LIMITE_AMOSTRA_DESATUALIZADA_MS) {
      ultimaPressaoValida = false;
      ultimoStatus = "PRESSURE_STALE";
      adsDisponivel = false;
      ultimaTentativaAdsMs = agora;
    }
    return;
  }
  ultimoRaw = ads.getLastConversionResults();
  ultimaAmostraAdsMs = millis();
  ads.startADCReading(ADS1X15_REG_CONFIG_MUX_SINGLE_0, false);
  const float tensao = ads.computeVolts(ultimoRaw);
  ultimaCorrenteMa = tensao * 1000.0f / RESISTOR_SHUNT_OHM;
  ultimaPressaoPsi = PRESSAO_MIN_PSI +
      ((ultimaCorrenteMa - CORRENTE_ZERO_MA) /
       (CORRENTE_FUNDO_ESCALA_MA - CORRENTE_ZERO_MA)) *
          (PRESSAO_MAX_PSI - PRESSAO_MIN_PSI);
  ultimaPressaoValida = std::isfinite(ultimaCorrenteMa) && std::isfinite(ultimaPressaoPsi) &&
                        ultimaCorrenteMa >= CORRENTE_ZERO_MA &&
                        ultimaCorrenteMa <= CORRENTE_FUNDO_ESCALA_MA;
  ultimoStatus = ultimaPressaoValida ? "OK" : "PRESSURE_CURRENT_INVALID";
}

void imprimirFloatOuNull(float valor) {
  if (std::isfinite(valor)) Serial.print(valor, 3);
  else Serial.print("null");
}

void enviarAmostra(uint32_t timestampMs) {
  Serial.print("{\"schema_version\":1,\"timestamp_ms\":");
  Serial.print(timestampMs);
  Serial.print(",\"sequence\":");
  Serial.print(++sequencia);
  Serial.print(",\"firmware_version\":\"");
  Serial.print(VERSAO_FIRMWARE);
  Serial.print("\",\"pressao_raw\":");
  Serial.print(ultimoRaw);
  Serial.print(",\"pressao_ma\":");
  imprimirFloatOuNull(ultimaCorrenteMa);
  Serial.print(",\"pressao\":");
  if (ultimaPressaoValida) imprimirFloatOuNull(ultimaPressaoPsi);
  else Serial.print("null");
  Serial.print(",\"pressao_unidade\":\"psi\",\"pressao_valida\":");
  Serial.print(ultimaPressaoValida ? "true" : "false");
  Serial.print(",\"pressao_status\":\"");
  Serial.print(ultimoStatus);
  Serial.print("\",\"status\":\"");
  Serial.print(ultimaPressaoValida ? "OK" : "PRESSURE_INVALID");
  Serial.println("\"}");
}

void setup() {
  Serial.begin(115200);
  Wire.begin(PINO_I2C_SDA, PINO_I2C_SCL);
  adsDisponivel = inicializarAds1115();
  ultimaTentativaAdsMs = millis();
  ultimaAmostraAdsMs = ultimaTentativaAdsMs;
  ultimoStatus = adsDisponivel ? "AGUARDANDO_AMOSTRA" : "ADS1115_UNAVAILABLE";
}

void loop() {
  atualizarPressaoNaoBloqueante();
  const uint32_t agora = millis();
  if (agora - ultimoEnvioMs >= INTERVALO_ENVIO_MS) {
    ultimoEnvioMs = agora;
    enviarAmostra(agora);
  }
  delay(1);
}
