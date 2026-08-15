# Supervisor de Porosímetro ISM 2.0

Sistema para ensaios com um ESP32, um transdutor de pressão 4–20 mA e um único flow meter Modbus RTU. O supervisório em Python recebe JSON por USB serial, valida, exibe, grava em SQLite e exporta CSV, XLSX, JSON e PDF. O firmware fica em `firmware/` e usa PlatformIO.

> Estado de segurança: a faixa real do transdutor e o mapa Modbus ainda não foram informados. O modo real permanece bloqueado até esses campos serem configurados. Nenhum registrador, escala ou faixa foi presumido.

## Arquitetura

- `firmware/`: aquisição no ESP32, ADS1115, Modbus/RS-485 e protocolo JSON.
- `communication/`: serial, reconexão, simulador e adaptador do protocolo legado.
- `core/`: modelos, validação, unidades, calibração e cálculos.
- `services/`: aquisição, alarmes, ensaios e exportação.
- `database/`: SQLite, repositórios e migrações aditivas.
- `ui/`: interface PySide6; domínio visual com apenas pressão e vazão.
- `tests/`: regras de negócio, protocolo, persistência, relatórios e interface.

## Componentes e conexões

| Componente | Pino/sinal | Ligação |
|---|---|---|
| ESP32 | GPIO16 / RX2 | `RO` do MAX3485 |
| ESP32 | GPIO17 / TX2 | `DI` do MAX3485 |
| ESP32 | GPIO4 | `DE` e `/RE` unidos no MAX3485 |
| MAX3485 | VCC | 3,3 V |
| MAX3485 | A/B | Par RS-485 do flow meter |
| ESP32 | GPIO21 / SDA | SDA do ADS1115 |
| ESP32 | GPIO22 / SCL | SCL do ADS1115 |
| ADS1115 | endereço | `0x48` |
| ADS1115 | A0 | tensão sobre o shunt de 149,7 Ω, single-ended para GND |
| Fonte externa | 24 V | Alimentação do flow meter e do laço do transdutor |
| GND | comum | ESP32, MAX3485, ADS1115 e negativo da fonte de 24 V |

**Nunca aplique 24 V ao ESP32, ADS1115 ou MAX3485.** O par `D+`/`D−` pertence somente ao lado RS-485. Confirme no manual se `D+` corresponde a A ou B: fabricantes adotam convenções diferentes; inverter o par é um teste comum quando não há resposta.

O resistor shunt de **149,7 Ω** converte corrente em tensão e não é a terminação RS-485. A terminação de **120 Ω entre A e B** é opcional e depende do comprimento/topologia do barramento.

## Pressão e ADS1115

O firmware usa `GAIN_ONE`, faixa de ±4,096 V, que comporta a tensão esperada sem saturar:

- 4 mA × 149,7 Ω = 0,5988 V;
- 20 mA × 149,7 Ω = 2,994 V.

Conversão: `corrente_mA = (tensao_V / 149,7) × 1000`.

Preencha `sensores.pressao.limite_inferior`, `limite_superior` e `unidade` no `config/user_config.json` após confirmar a placa do transdutor. Ganho e offset podem ser calibrados no supervisório; a aplicação usa `valor_calibrado = valor_convertido × ganho + offset`. Não é necessário mudar o firmware para calibração posterior do supervisório.

## Configuração Modbus obrigatória

Copie os valores confirmados do manual para a seção `flow_meter` do `user_config.json`. O modelo completo está em `config/flow_meter.example.json`:

- endereço do escravo, baud rate, paridade e stop bits;
- função 03 ou 04, registrador inicial e quantidade;
- tipo do dado, ordem de bytes e palavras;
- fator de escala e unidade nativa;
- timeout, tentativas e limites físicos.

Defina `configurado: true` somente depois de validar todos os itens. O firmware de referência implementa decodificação `UINT16`/um registrador; outros tipos exigem acrescentar a decodificação confirmada no manual, sem alterar o contrato serial.

## Protocolo serial JSON Lines

Cada mensagem é um objeto JSON UTF-8 terminado por `\n`:

```json
{"schema_version":1,"sequence":152,"uptime_ms":152000,"firmware_version":"2.0.0","pressao":{"ads_raw":12000,"voltage_v":1.502,"current_ma":10.033,"value":null,"unit":"UNCONFIGURED","valid":false},"vazao":{"raw_register":1326,"value":132.6,"unit":"L/min","valid":true,"consecutive_failures":0},"status":"ERROR","alarms":["PRESSURE_RANGE_UNCONFIGURED"]}
```

`status` só é `OK` quando os dois sensores obrigatórios são válidos. O supervisório aceita temporariamente mensagens antigas em um único adaptador, escolhendo `vazao_baixa` antes de `vazao_alta` para preservar bancos/equipamentos anteriores.

## Instalação e execução no Windows

Requer Python 3.11 ou posterior:

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Executar testes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Gerar executável:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build.ps1
```

Saída: `dist\PorosimetroSupervisorio_v2_0_0\PorosimetroSupervisorio_v2_0_0.exe`.

## Firmware

Com VS Code e PlatformIO, abra a pasta `firmware`, revise `include/HardwareConfig.h`, conecte o ESP32 e use **Upload** e **Monitor**. Pela Arduino IDE, instale as bibliotecas listadas em `platformio.ini`, selecione uma placa ESP32, copie os arquivos de `include/` e `src/` para um sketch e preserve `main.cpp` como arquivo principal (renomeando-o para `.ino` se necessário).

USB serial usa 115200 baud; a UART2 é exclusiva do Modbus. A aquisição ocorre a cada 1 segundo com `millis()`, sem `delay()` bloqueante. Timeouts/CRC/respostas inválidas são reportados pelo código de resultado Modbus; falhas consecutivas são contadas e uma resposta válida zera o contador automaticamente.

## Simulação, armazenamento e relatórios

O modo simulado exige confirmação ao iniciar um ensaio, aparece em destaque e é persistido. PDFs de simulação recebem marca explícita. Medições inválidas são armazenadas para diagnóstico, mas ficam fora dos máximos e estatísticas. Cada ensaio guarda snapshot da configuração, unidades, modo e versão de firmware.

O SQLite usa WAL. Antes da migração, o backup usa `sqlite3.Connection.backup()` e passa por `PRAGMA integrity_check`. A migração 3 mantém as colunas antigas e preenche a coluna única `vazao`; nenhum dado legado é apagado.

## Procedimento antes do equipamento real

1. Energize primeiro ESP32/USB sem 24 V e confirme que o ADS1115 aparece em `0x48`.
2. Meça o shunt com o sistema desenergizado e confirme 149,7 Ω.
3. Aplique corrente conhecida com calibrador: confira aproximadamente 0,599 V em 4 mA e 2,994 V em 20 mA.
4. Confirme faixa/unidade do transdutor e preencha a configuração.
5. Consulte o manual do flow meter e preencha todos os parâmetros Modbus.
6. Com 24 V desligados, revise polaridade, GND comum e isolamento entre potência e lógica.
7. Ligue o flow meter; teste A/B e, se necessário, inverta o par — nunca conecte D+/D− ao ESP32.
8. Observe JSON no monitor serial e confirme sequência crescente, `status: OK`, unidades e valores plausíveis.
9. Rode os testes e faça um ensaio simulado antes de liberar o modo real.

## Solução de problemas

- `MODBUS_UNCONFIGURED`: preencha o manual e recompile o firmware.
- `MODBUS_TIMEOUT`: verifique endereço, baud/paridade, A/B, GND, alimentação e terminação.
- `MODBUS_INVALID_RESPONSE`: confirme função, registrador, quantidade e CRC/ruído do barramento.
- `PRESSURE_RANGE_UNCONFIGURED`: informe faixa e unidade reais do transdutor.
- `PRESSURE_CURRENT_INVALID`: confira laço de 24 V, shunt, A0/GND e corrente fora de 3,6–20,5 mA.
- Porta ausente: feche outros monitores seriais, reconecte o USB e confira driver CP210x/CH340.
- Mensagens perdidas: confira sequência, cabo USB, ruído e aterramento; a aplicação reconecta automaticamente.
