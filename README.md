# Supervisório ISM – Permeabilímetro

Aplicativo de aquisição, ensaio e relatório para o permeabilímetro ISM.
Versão do aplicativo: 2.3.0. Firmware atual: 2.2.0 (independente).

## Arquitetura de produção

```text
Transdutor 4–20 mA -> ADS1115 -> ESP32 -> USB serial (JSON Lines) -> PC
Flowmeter ------------------------------------------------> USB–RS485 (Modbus RTU) -> PC
```

O ESP32 lê exclusivamente pressão. O flowmeter não é ligado ao ESP32 e
possui sua própria porta COM. As duas portas devem ser diferentes. Feche o
QModMaster antes de conectar o supervisório, pois uma porta serial não pode ser
aberta pelos dois programas ao mesmo tempo.

## Protocolo ESP32 -> supervisório

115200 baud, UTF-8, uma linha JSON por amostra, schema 1:

```json
{
  "schema_version": 1,
  "timestamp_ms": 123456,
  "sequence": 42,
  "firmware_version": "2.2.0",
  "pressao_raw": 12345,
  "pressao_ma": 12.34,
  "pressao": 200.62,
  "pressao_unidade": "psi",
  "pressao_valida": true,
  "pressao_status": "OK",
  "status": "OK"
}
```

Todos os campos são obrigatórios. Leituras indisponíveis usam `null` e
`pressao_valida=false`; o modo real não gera valores simulados. Se o ADS1115
ficar três segundos sem uma conversão nova, a pressão passa a
`PRESSURE_STALE` e o firmware tenta reinicializar o conversor periodicamente;
uma pressão antiga nunca é republicada como válida.

A calibração instalada do transdutor considera `3,95 mA = 0 psi` e
`20,00 mA = 400 psi`.

## Protocolo PC -> flowmeter

O worker envia somente `03 – Read Holding Registers`:

- Modbus RTU, slave 1, 9600 baud, 8N1;
- endereço bruto `0x003A` (58; algumas ferramentas Base Address 1 exibem 59);
- dois registradores, UINT32 big-endian;
- `vazao = valor_uint32 / 1000.0`; a unidade é selecionada e confirmada na interface;
- frame de consulta: `01 03 00 3A 00 02 E4 06`;
- F16 do medidor: 125 ms;
- intervalo inicial: 1000 ms; timeout permitido: 750–1500 ms.

Não existe comando Modbus de escrita no aplicativo. O parser valida slave,
função, byte count, tamanho e CRC, incluindo exceções Modbus de cinco bytes.

O cálculo com `NL/min` exige pressão e temperatura normais confirmadas no
equipamento. `L/min` e `mL/min` registram a pressão absoluta de referência do
volume. A confirmação é feita na interface, sem editar JSON. As unidades e hipóteses estão em
[docs/arquitetura-e-formulas.md](docs/arquitetura-e-formulas.md).

## Configuração das portas

1. Conecte o ESP32 e o adaptador USB–RS485.
2. Feche QModMaster, Arduino Serial Monitor e qualquer outro programa serial.
3. Em **Visão geral**, clique em **Atualizar portas**.
4. Escolha a porta do ESP32 no primeiro campo e conecte.
5. Escolha outra porta no campo Flowmeter e conecte.
6. Em **Configurações > Modbus**, selecione `L/min`, `NL/min` ou `mL/min` e
   confirme a unidade no manual/equipamento. O preflight real bloqueia o ensaio
   enquanto a unidade e suas referências aplicáveis estiverem pendentes.

VID, PID e número serial são persistidos quando o driver os fornece, permitindo
reencontrar o dispositivo caso o Windows renumere a COM.

## Preflight do ensaio real

O início é bloqueado até confirmar ESP32 e flowmeter conectados, portas
diferentes, leituras válidas e recentes, configuração consistente, calibração
quando exigida e banco gravável. O modo simulado é identificado na tela e nos
dados exportados.

Pressão e vazão mantêm timestamps próprios. A medição combinada para banco e
cálculos é emitida no intervalo de `aquisicao.intervalo_s`; uma atualização de
vazão não altera o timestamp da pressão. Leituras acima do limite de idade são
marcadas `STALE` e deixam de ser válidas.

## Instalação e execução

Requer Python 3.12.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

A configuração do usuário fica em `config/user_config.json` no desenvolvimento
e em `%LOCALAPPDATA%\ISM\Permeabilimetro\config` no executável. O arquivo padrão
é versionado; a configuração local e bancos não são enviados ao Git.

## Testes e qualidade

```powershell
python -m compileall -q app.py communication config core database services ui tests
python -m pytest
python -m ruff check .
python -m ruff format --check .
pio run -d firmware
pyinstaller --clean --noconfirm PermeabilimetroSupervisorio.spec
```

Os testes Qt usam `QT_QPA_PLATFORM=offscreen`. Bancos antigos são migrados de
forma incremental (schema 5): campos legados de vazão são apenas fallback de
leitura e não recebem novas medições. Ensaios antigos mostram a duração como
tempo decorrido legado. Backups SQLite possuem timestamp e retenção configurável.

## Relatório final

O PDF é gerado após a confirmação do encerramento e da persistência do ensaio,
sempre pelo ID da sessão recém-finalizada. Inclui capa, dados da amostra,
aquisição, estatísticas da série integral válida, quatro gráficos de processo,
tabela paginada de permeabilidade, ajuste de Klinkenberg, três gráficos de
análise, ocorrências e assinatura. Ensaios simulados são identificados na capa.
O PDF pode ser exportado novamente pelo histórico.

A logo e as fontes DejaVu Sans ficam em `assets/branding` e `assets/fonts`.
No executável, o `.spec` as copia para `_internal/assets`; `ui/resources.py`
resolve esses arquivos por `sys._MEIPASS`, sem depender do diretório de trabalho.
Para verificar o PDF pelo executável sem acessar dados do operador:

```powershell
dist\PermeabilimetroSupervisorio_v2_3_0\PermeabilimetroSupervisorio_v2_3_0.exe --report-smoke "$env:TEMP\ism-report-smoke"
```

Esse diagnóstico usa um banco SQLite temporário e gera um relatório marcado
como demonstrativo. Não substitui a validação do fluxo real com o equipamento.
O PDF em `artifacts/final-report` também usa dados fictícios de teste; não
representa um ensaio realizado em equipamento físico.

## Build de produção para Windows

Execute `powershell -ExecutionPolicy Bypass -File .\build.ps1` em ambiente com
Python 3.12. O script instala dependências, executa lint, formatação e testes,
compila o firmware, gera o executável, exercita o PDF e grava ZIP e SHA-256 em
`dist/`. A futura assinatura Authenticode requer certificado e chave privada:
em estação controlada, use `signtool sign /fd SHA256 /tr <timestamp> /td SHA256`
e confirme com `signtool verify /pa`. O build não assina automaticamente.

## Firmware

- `firmware/`: build oficial PlatformIO;
- `firmware_esp32_permeabilimetro/`: sketch equivalente para Arduino IDE;
- `firmware/legacy/`: aviso sobre a arquitetura antiga com Modbus no ESP32.

Antes de gravar, confirme a faixa do transdutor de pressão no
`HardwareConfig.h` ou no sketch. A validação final de ruído, escala, polaridade
RS-485 e estabilidade precisa ser feita no equipamento real.
