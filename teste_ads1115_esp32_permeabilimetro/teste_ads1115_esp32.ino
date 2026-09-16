#include <Wire.h>
#include <Adafruit_ADS1X15.h>

// Pinos I2C usados pelo ESP32.
constexpr uint8_t PINO_SDA = 21;
constexpr uint8_t PINO_SCL = 22;

// Endereco padrao do ADS1115 quando o pino ADDR esta ligado ao GND.
constexpr uint8_t ENDERECO_ADS1115 = 0x48;

Adafruit_ADS1115 ads;

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("Teste ESP32 + ADS1115");
  Serial.printf("I2C: SDA = GPIO %u, SCL = GPIO %u\n", PINO_SDA, PINO_SCL);

  Wire.begin(PINO_SDA, PINO_SCL);

  if (!ads.begin(ENDERECO_ADS1115, &Wire)) {
    Serial.printf("ERRO: ADS1115 nao encontrado no endereco 0x%02X.\n",
                  ENDERECO_ADS1115);
    Serial.println("Confira alimentacao, fios SDA/SCL e o pino ADDR.");

    while (true) {
      delay(1000);
    }
  }

  // Faixa de entrada: +/- 4,096 V. Nao aplique tensao negativa nem tensao
  // acima da alimentacao do ADS1115 em nenhuma entrada analogica.
  ads.setGain(GAIN_ONE);

  Serial.println("ADS1115 encontrado. Iniciando leituras...");
}

void loop() {
  for (uint8_t canal = 0; canal < 4; canal++) {
    int16_t leitura = ads.readADC_SingleEnded(canal);
    float tensao = ads.computeVolts(leitura);

    Serial.printf("A%u: %6d  |  %.4f V", canal, leitura, tensao);
    if (canal < 3) {
      Serial.print("    ");
    }
  }

  Serial.println();
  delay(1000);
}
