# Firmware ESP32 do permeabilímetro

Firmware de produção para exatamente dois instrumentos:

- um transdutor de pressão 4–20 mA lido pelo ADS1115;
- um flow meter lido em Modbus RTU através do MAX3485.

O ESP32 envia uma linha JSON por segundo ao supervisório através da USB em
115200 baud.

## Bibliotecas

Instale pela Arduino IDE:

- **Adafruit ADS1X15**, da Adafruit;
- **ModbusMaster**, de Doc Walker;
- pacote de placas **esp32**, da Espressif Systems.

## Ligações do ADS1115

| ADS1115 | ESP32 / sinal |
|---|---|
| VDD | 3V3 |
| GND | GND |
| SDA | GPIO 21 |
| SCL | GPIO 22 |
| ADDR | GND, endereço 0x48 |
| A0 | tensão sobre o resistor shunt |

O sinal 4–20 mA **não deve ser ligado diretamente** ao ADC. O firmware está
configurado para um resistor shunt de precisão de **150 ohms, 0,1%**, que gera
0,6 V em 4 mA e 3,0 V em 20 mA. Use potência nominal de pelo menos 0,25 W.

Ligação típica do laço:

```text
+24 V ---- (+ transdutor -) ---- A0/ADS1115 ---- resistor 150 ohms ---- 0 V
                                      |
                                  tensão medida
```

O GND do ADS1115 precisa ter a mesma referência do lado inferior do resistor.
Em instalações industriais com terras diferentes, use isolamento apropriado.

## Ligações do MAX3485

| MAX3485 | ESP32 / barramento |
|---|---|
| VCC | 3V3 |
| GND | GND |
| RO | GPIO 16 (RX2) |
| DI | GPIO 17 (TX2) |
| DE | GPIO 4 |
| /RE | GPIO 4 |
| A | A/RS-485 do medidor |
| B | B/RS-485 do medidor |

Use cabo de par trançado. Em um barramento longo, coloque terminação de 120
ohms somente nas duas extremidades. Alguns fabricantes invertem a nomenclatura
A/B; confira o manual do medidor.

## Configuração obrigatória do flow meter

Antes de gravar, ajuste no início do arquivo `.ino`:

- `MODBUS_SLAVE_ID`;
- `MODBUS_BAUD_RATE`;
- `MODBUS_SERIAL_CONFIG` (`SERIAL_8N1`, `SERIAL_8E1`, etc.);
- `REGISTRADOR_VAZAO`;
- `REGISTRADOR_EH_INPUT`;
- `TIPO_DADO_VAZAO`;
- `INVERTER_ORDEM_WORDS` e `INVERTER_BYTES_NO_WORD`;
- `ESCALA_VAZAO` e `OFFSET_VAZAO`.

O endereço passado à biblioteca é baseado em zero. Por exemplo, o registrador
40001 descrito no manual normalmente corresponde ao endereço `0`; confirme na
tabela Modbus do fabricante.

## Saída enviada ao programa

Operação normal:

```json
{"timestamp_ms":152340,"sequence":153,"pressao_ma":12.000,"pressao":50.000,"pressao_status":"OK","vazao":0.85000,"vazao_status":"OK","status":"OK"}
```

Se o flow meter não responder, a pressão continua sendo enviada:

```json
{"timestamp_ms":153340,"sequence":154,"pressao_ma":12.000,"pressao":50.000,"pressao_status":"OK","vazao":null,"vazao_status":"ERRO_MODBUS_0xE2","status":"PARCIAL_SEM_VAZAO"}
```

Não imprima textos de depuração em `Serial`, pois a mesma porta é usada pelo
protocolo JSON. Para depuração adicional, use outra UART ou remova os textos
antes de conectar ao supervisório.
