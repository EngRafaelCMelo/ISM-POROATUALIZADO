# Teste do ADS1115 com ESP32

Sketch independente para verificar a comunicacao I2C e as quatro entradas
analogicas do ADS1115.

Este sketch é somente um diagnóstico de bancada e não envia o protocolo do
supervisório. Para operar o equipamento com o MAX3485 e um único flow meter,
use `../firmware_esp32_porosimetro/firmware_esp32_porosimetro.ino`.

## Ligacoes

| ADS1115 | ESP32 |
|---|---|
| VDD | 3V3 |
| GND | GND |
| SDA | GPIO 21 |
| SCL | GPIO 22 |
| ADDR | GND (endereco `0x48`) |

Alimente o modulo em **3,3 V** para manter o barramento I2C compativel com o
ESP32. Todos os dispositivos devem compartilhar o mesmo GND.

## Como executar na Arduino IDE

1. Instale o pacote de placas **ESP32 by Espressif Systems**.
2. No Gerenciador de Bibliotecas, instale **Adafruit ADS1X15**. Aceite tambem a
   instalacao das dependencias sugeridas.
3. Abra `teste_ads1115_esp32.ino`.
4. Selecione sua placa ESP32 e a porta serial correta.
5. Compile e envie o sketch.
6. Abra o Monitor Serial em **115200 baud**.

O programa procura o ADS1115 no endereco padrao `0x48` e mostra, uma vez por
segundo, a leitura bruta e a tensao dos canais A0, A1, A2 e A3.

## Teste rapido

Com o circuito desligado, conecte temporariamente `A0` ao `3V3`. Depois de
ligar, o canal A0 deve indicar aproximadamente 3,3 V. Em seguida, desligue o
circuito antes de mudar a ligacao.

Nao aplique tensao negativa nem tensao superior a VDD nas entradas analogicas.
