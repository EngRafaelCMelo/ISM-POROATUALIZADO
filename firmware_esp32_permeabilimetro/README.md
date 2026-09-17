# Firmware ESP32 — pressão

Firmware 2.2.0 da arquitetura de produção. O ESP32 lê **somente** o
transdutor de pressão pelo ADS1115. Não há UART, RS-485 nem Modbus neste
firmware. O flowmeter deve ser conectado diretamente ao computador por um
adaptador USB–RS485.

## Ligações

| ADS1115 | ESP32 / sinal |
|---|---|
| VDD | 3V3 |
| GND | GND |
| SDA | GPIO 21 |
| SCL | GPIO 22 |
| ADDR | GND (0x48) |
| A0 | tensão sobre resistor shunt de 149,7 Ω |

O laço de 4–20 mA não pode ser ligado diretamente ao ESP32. A calibração de
produção usa `3,95 mA = 0 psi` e `20,00 mA = 400 psi`.

## Contrato serial

USB serial, 115200 baud, uma linha JSON UTF-8 por segundo, sem texto de debug:

```json
{"schema_version":1,"timestamp_ms":123456,"sequence":42,"firmware_version":"2.2.0","pressao_raw":12345,"pressao_ma":12.34,"pressao":209.10,"pressao_unidade":"psi","pressao_valida":true,"pressao_status":"OK","status":"OK"}
```

Campos indisponíveis são enviados como `null`; o firmware nunca inventa
valores em modo real. Após três segundos sem conversão nova, a amostra é
invalidada como `PRESSURE_STALE` e o ADS1115 é reinicializado periodicamente.
