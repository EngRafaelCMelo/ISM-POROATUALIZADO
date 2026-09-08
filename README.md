# Supervisório ISM – Permeabilímetro

Aplicação desktop para ensaios de permeabilidade a gás com ESP32, ADS1115, transdutor 4–20 mA e flow meter Modbus RTU/RS-485.

## Fluxo de ensaio

Conecte o ESP32 (ou simulador), cadastre a amostra, informe comprimento e diâmetro, selecione gás, temperatura e viscosidade, estabilize as leituras e calcule a permeabilidade. A correção de Klinkenberg é opcional e usa ao menos dois pontos de pressão média absoluta.

O cálculo usa Darcy para gás compressível: `k = 2 μ L Qref Pref / [A (Pin² − Pout²)]`. Não é usada uma aproximação incompressível.

## Configuração obrigatória do equipamento real

Antes de conectar o equipamento real, confirme no arquivo de configuração a faixa e a unidade do transdutor. O modo real permanece bloqueado sem essa confirmação. O resistor shunt padrão é **149,7 Ω**. Leituras abaixo de 3,6 mA ou acima de 20,5 mA são inválidas.

Também preencha os parâmetros Modbus do manual do flow meter: endereço, função, registradores, tipo de dado, escala e ordens de bytes/palavras. O software não presume esses parâmetros. A pressão de saída pode ser manual, fixa configurada ou atmosférica quando a saída estiver declaradamente aberta.

## Dados e compatibilidade

Os dados novos ficam em `data/permeabilimetro.db` (ou `%LOCALAPPDATA%\ISM\Permeabilimetro` no executável). Na primeira inicialização, uma instalação antiga é copiada apenas depois de `PRAGMA integrity_check`; a base anterior e seu backup são preservados. Registros antigos permanecem disponíveis como dados legados em leitura.

## Executar

```powershell
python -m pip install -r requirements.txt
python app.py
```

Para gerar o executável:

```powershell
.\build.ps1
```

O resultado é `dist\PermeabilimetroSupervisorio_v2_1_0\PermeabilimetroSupervisorio_v2_1_0.exe`.

## Firmware

A fonte principal é `firmware/` (PlatformIO). Ela publica JSON por linha, inclui leituras ADS1115 com reconexão, validação de corrente, estados parciais e suporte configurável a Modbus. A pasta `firmware_esp32_permeabilimetro/` é uma referência de migração da atualização de 08/09 e deve ser incorporada ao fluxo PlatformIO antes da liberação de campo.

## Nota de migração

Versões históricas destinadas a outro equipamento podem conter registros e caminhos com a nomenclatura anterior. Eles são preservados exclusivamente para compatibilidade de dados legados; não fazem parte do fluxo atual.
