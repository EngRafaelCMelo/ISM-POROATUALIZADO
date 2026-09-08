# Supervisor de Porosímetro ISM

Aplicação desktop para monitorar e registrar ensaios de um porosímetro conectado a um ESP32 por USB serial. O sistema foi projetado para uso em laboratório: mantém as leituras visíveis em tempo real, grava cada amostra progressivamente em SQLite, detecta falhas, registra intervenções do operador e exporta o resultado do ensaio.

O hardware atual possui exatamente um transdutor de pressão 4–20 mA, lido por
um ADS1115, e um flow meter Modbus RTU, ligado ao ESP32 por um MAX3485.

## Funcionalidades

- comunicação USB serial em thread separada, sem bloquear a interface;
- detecção de portas, baud rate configurável, timeout e contadores de mensagens;
- parser tolerante a campos opcionais e descarte seguro de JSON corrompido;
- simulador integrado com ruído e falhas selecionáveis;
- cartões de pressão e vazão;
- criação, pausa, retomada, marcações e finalização de ensaios;
- gravação contínua em SQLite com WAL, transações e índices;
- gráficos em tempo real, zoom, cursor, janelas temporais e exportação PNG;
- alarmes de corrente, faixa, ruído, variação e comunicação;
- histórico pesquisável, invalidação sem exclusão e exclusão confirmada;
- calibração por dois ou múltiplos pontos, histórico e aviso de instabilidade;
- cadastro de comprimento, diâmetro, massa, volume geométrico, gás e temperatura;
- porosimetria por expansão de gás/Lei de Boyle com múltiplos ciclos;
- volume esquelético, volume de poros abertos, porosidade, fração sólida e densidades;
- permeabilidade a gás por Darcy compressível e correção de Klinkenberg;
- exportação CSV, XLSX, JSON e relatório PDF;
- tela de diagnóstico técnico;
- configurações persistentes em JSON;
- logs rotativos e recuperação de ensaios interrompidos;
- preparação para executável Windows com PyInstaller.

## Requisitos

- Windows 10 ou 11;
- Python 3.12 ou superior;
- porta USB com driver do conversor serial do ESP32 instalado.

As bibliotecas principais são PySide6, pyserial, pyqtgraph, pandas, openpyxl e reportlab.

## Instalação no Windows

Abra o PowerShell na pasta do projeto:

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Para executar:

```powershell
.\.venv\Scripts\python.exe app.py
```

Também é possível clicar duas vezes em `iniciar.bat` depois de criar o ambiente virtual.

## Fluxo de uso

1. Abra o programa.
2. Escolha a porta do ESP32 e clique em **Conectar equipamento**.
3. Clique em **Iniciar ensaio** e preencha os dados básicos e a geometria da amostra.
4. Registre pelo menos três ciclos na tela **Calcular porosidade**.
5. Finalize o ensaio. O relatório PDF é criado automaticamente.

A tela inicial mostra a etapa atual desse fluxo e libera as ações no momento certo.
Gráficos detalhados, calibração, configurações e diagnóstico permanecem disponíveis em
**Mostrar opções avançadas**. O baud rate, o simulador e a injeção de falhas ficam em
**Opções de conexão**, evitando controles técnicos durante o uso normal.

## Cálculos de porosimetria e permeabilidade

Os dados físicos são informados na aba **Amostra e gás** ao criar o ensaio e podem ser
ajustados posteriormente na tela **Cálculos**:

- comprimento `L` e diâmetro `D` da amostra;
- massa seca e volume geométrico manual, quando conhecido;
- hélio, nitrogênio, ar, argônio ou dióxido de carbono;
- temperatura e pressão atmosférica local;
- pressões manométricas ou absolutas;
- volumes calibrados da câmara de amostra e da câmara de expansão;
- fatores de compressibilidade `Z0`, `Z1` e `Z2`.

No procedimento de Boyle, a câmara que contém a amostra começa em `P1`, a câmara de
expansão começa em `P0` e, após a abertura da válvula, o conjunto estabiliza em `P2`.
O programa converte as pressões para absolutas e aplica o balanço:

```text
Vlivre = Vexpansão × [P2/(Z2×T2) - P0/(Z0×T0)]
                       / [P1/(Z1×T1) - P2/(Z2×T2)]

Vesquelético = Vcâmara - Vlivre
Porosidade aberta = (Vgeométrico - Vesquelético) / Vgeométrico × 100
```

É possível registrar vários ciclos `P1/P2`. O sistema calcula média, desvio padrão,
coeficiente de variação e informa se a repetibilidade ficou dentro do limite configurado.
O volume geométrico de uma amostra cilíndrica é calculado por `πD²L/4`.

Para permeabilidade, informe ou capture pressão de entrada, pressão de saída e vazão.
A viscosidade aproximada do gás selecionado é preenchida automaticamente e continua
editável para uso do valor certificado pelo laboratório. O resultado é apresentado em
`m²`, darcy e millidarcy. Ensaios em diferentes pressões médias podem ser adicionados à
regressão de Klinkenberg para estimar a permeabilidade intrínseca e o fator de deslizamento.

Os cálculos ficam associados ao ensaio e são incluídos nas exportações XLSX, JSON e PDF.
Como a picnometria de gás mede o volume esquelético acessível ao gás, a qualidade do
resultado depende da calibração dos volumes das câmaras, estabilidade térmica, ausência
de vazamentos e repetição dos ciclos.

Na tela **Ensaio**, o botão **Calcular porosidade** abre diretamente o procedimento
guiado. Informe o volume geométrico manualmente ou através do comprimento e diâmetro,
capture P0, P1 e P2 e registre pelo menos três ciclos. Um único ciclo ainda pode ser
calculado para diagnóstico, mas não é apresentado como repetibilidade aprovada.

Referências técnicas: [Micromeritics — gas pycnometry and density](https://micromeritics.com/density/),
[Micromeritics — volume, density and porosity](https://micromeritics.com/resources/measuring-volume-density-and-porosity-of-tablets-for-coating-process-control-and-qc/)
e [USGS — Darcy's law and permeability](https://pubs.usgs.gov/publication/70214996).

Os dados são salvos a cada leitura; não é necessário finalizar para preservar amostras já recebidas.

## Modo simulação

Clique em **Iniciar simulação** na faixa superior. A interface mostra um aviso amarelo e todas as leituras recebem qualidade `simulada`.

O seletor ao lado permite demonstrar:

- operação normal com pressão e vazão crescentes;
- sensor desconectado;
- corrente de 3,7 mA ou 3,2 mA;
- corrente de 20,2 mA ou 21,0 mA;
- perda temporária de comunicação.

Selecione novamente **Simulação normal** para recuperar a comunicação ou o sensor. O simulador não usa uma porta física.

## Firmware e ligações do ESP32

O firmware integrado está em
`firmware_esp32_porosimetro/firmware_esp32_porosimetro.ino`. As ligações,
bibliotecas e opções que precisam ser conferidas no manual do flow meter estão
documentadas em `firmware_esp32_porosimetro/README.md`.

Arquitetura do equipamento:

```text
Transdutor 4–20 mA -> resistor shunt -> ADS1115 -> I2C -> ESP32
Flow meter          -> RS-485         -> MAX3485 -> UART2 -> ESP32
ESP32                -> USB serial 115200         -> supervisório
```

O endereço do escravo, baud rate, paridade, registrador, tipo do registrador,
formato numérico e escala do flow meter devem ser ajustados no início do
firmware conforme a tabela Modbus do fabricante.

## Protocolo do ESP32

O ESP32 deve transmitir um objeto JSON UTF-8 por linha. Cada mensagem deve terminar com `\n`.

Mensagem completa enviada pelo firmware:

```json
{
  "timestamp_ms": 152340,
  "sequence": 153,
  "pressao_ma": 12.0,
  "pressao": 50.0,
  "pressao_status": "OK",
  "vazao": 0.85,
  "vazao_status": "OK",
  "status": "OK"
}
```

Também é aceita uma mensagem reduzida:

```json
{"pressao": 50.0, "vazao": 0.85}
```

Se o medidor de vazão não responder, o firmware envia
`"vazao": null` e o estado `PARCIAL_SEM_VAZAO`. O supervisório mostra a
pressão normalmente e sinaliza que a vazão está pendente, sem substituir
a leitura ausente por zero.

Da mesma forma, uma falha no ADS1115 produz `"pressao": null` e o estado
`PARCIAL_SEM_PRESSAO`. A tela de diagnóstico mostra `pressao_status` e
`vazao_status`, e o sistema registra um alarme para a leitura ausente.

Para compatibilidade com versões anteriores, `vazao_baixa` e
`vazao_baixa_ma` também são aceitos como aliases de `vazao` e `vazao_ma`.

Todos os campos são opcionais, mas a linha precisa conter pelo menos um campo de sensor. Campos numéricos inválidos fazem somente aquela mensagem ser descartada; a aplicação permanece aberta. Quando a corrente está disponível, o sistema calcula também o valor de engenharia para comparação.

Na configuração padrão, `pressao_ma` é convertida e calibrada pelo
supervisório. O campo `pressao` enviado pelo ESP32 é mantido na leitura bruta
para diagnóstico e é usado como contingência caso a corrente não seja enviada.
O flow meter já entrega `vazao` em L/min pelo protocolo Modbus.

## Conversão 4–20 mA e faixas

A conversão utilizada é:

```text
valor = limite_inferior + ((corrente_mA - corrente_mínima) /
        (corrente_máxima - corrente_mínima)) *
        (limite_superior - limite_inferior)
valor_calibrado = valor * ganho + offset
```

As faixas iniciais ficam em `config/default_config.json`:

- pressão: 0–100 bar, proveniente do sinal 4–20 mA;
- vazão: 0–5 L/min, proveniente do medidor RS-485.

Altere-as pela tela **Configurações > Sensores**. Reinicie o programa para recriar o parser e os cartões com as novas faixas. As alterações do operador são gravadas em `config/user_config.json`; o arquivo de padrões permanece intacto.

O banco mantém algumas colunas legadas de baixa/alta vazão para abrir ensaios
criados por versões anteriores. O equipamento atual utiliza somente a coluna
de baixa vazão, apresentada na interface e nas exportações como **Vazão**.

## Banco de dados

Em desenvolvimento, o banco fica em `data/porosimetro.db`. No executável, os dados ficam em:

```text
%LOCALAPPDATA%\ISM\Porosimetro
```

Tabelas:

- `ensaios` e `amostras`: identificação e resumo;
- `medicoes`: todas as leituras e a mensagem original;
- `alarmes` e `eventos`: ocorrências operacionais;
- `marcacoes`: comentários durante o ensaio;
- `calibracoes`: versões de ganho e offset;
- `configuracoes` e `usuarios`: estrutura para expansão.

O banco usa WAL para reduzir bloqueios. Na inicialização, ensaios encontrados como `em_andamento` ou `pausado` são preservados e marcados como `interrompido`. Se o backup automático estiver ativo, uma cópia recente é criada em `data/backups`.

## Exportações

Na tela **Histórico**, selecione um ensaio e escolha CSV, XLSX ou PDF. O serviço também oferece JSON internamente. Se um nome já existir, um sufixo de data e hora é acrescentado, evitando sobrescrita silenciosa.

- CSV: UTF-8 com BOM, unidades nos cabeçalhos e separador configurável;
- XLSX: abas Resumo, Medições, Alarmes, Marcações e Calibração;
- PDF: identificação, resumo estatístico, alarmes, observações e assinatura;
- PNG: captura do painel completo de gráficos.

Ao finalizar um experimento, resultados calculados que ainda não foram salvos são
gravados no ensaio e o relatório PDF final é gerado automaticamente no diretório
escolhido ao criar o ensaio. Se um ensaio de porosidade ainda não tiver cálculo de
Boyle, o programa avisa antes de finalizar e oferece voltar à tela de cálculos.
O relatório inclui identificação, estatísticas, porosidade, volume de poros,
volume e densidade esqueléticos, repetibilidade, alarmes e observações. Ele pode
ser gerado novamente a qualquer momento em **Histórico > Exportar PDF**.

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Os testes cobrem parser, mensagens reduzidas e corrompidas, conversão 4–20 mA, ganho e offset, alarmes, calibração, criação/recuperação de ensaio, SQLite e exportações.

## Gerar o executável

Depois de criar o ambiente virtual:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build.ps1
```

O resultado fica em:

```text
dist\PorosimetroSupervisorio_v1_5_0\PorosimetroSupervisorio_v1_5_0.exe
```

O executável é criado sem console e inclui o estilo e a configuração padrão. Banco, configurações, logs e exportações ficam fora da pasta do programa para permitir escrita sem privilégios administrativos.

## Solução de problemas da porta serial

**A porta não aparece**

- conecte novamente o ESP32;
- confira o Gerenciador de Dispositivos;
- instale o driver CP210x ou CH340 correspondente à placa;
- clique em **Atualizar portas**;
- feche Arduino Serial Monitor, PlatformIO ou outro programa que possa estar usando a porta.

**A porta aparece, mas não chegam dados**

- confirme `115200` no firmware e no supervisor;
- confirme uma quebra de linha depois de cada JSON;
- valide que o firmware não imprime textos de depuração na mesma serial;
- abra **Diagnóstico** e confira a última mensagem bruta e os contadores.

**A conexão cai**

- troque o cabo USB;
- evite hubs sem alimentação;
- aumente o timeout em **Configurações** se o firmware transmitir em intervalos maiores que um segundo;
- confira os logs em `logs/supervisor.log`.

## Estrutura do projeto

```text
app.py
config/          configuração padrão e carregamento
core/            modelos, cálculos, validação e calibração
communication/   parser, serial e simulador
database/        schema, conexão e repositórios
services/        aquisição, ensaio, alarmes e exportação
ui/              janela, páginas, diálogos, widgets e estilo
tests/           testes essenciais
exports/         destino padrão de relatórios
```

## Segurança operacional

A bomba continua sendo operada manualmente; o software não comanda nem interrompe a bomba. Alarmes são indicativos e não substituem intertravamentos físicos. Antes do uso em produção, valide as faixas, a calibração, os limites de alarme e o comportamento do firmware com o procedimento metrológico do laboratório.
