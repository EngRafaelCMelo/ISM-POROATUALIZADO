# Supervisor de Porosímetro ISM

Aplicação desktop para monitorar e registrar ensaios de um porosímetro conectado a um ESP32 por USB serial. O sistema foi projetado para uso em laboratório: mantém as leituras visíveis em tempo real, grava cada amostra progressivamente em SQLite, detecta falhas, registra intervenções do operador e exporta o resultado do ensaio.

## Funcionalidades

- comunicação USB serial em thread separada, sem bloquear a interface;
- detecção de portas, baud rate configurável, timeout e contadores de mensagens;
- parser tolerante a campos opcionais e descarte seguro de JSON corrompido;
- simulador integrado com ruído e falhas selecionáveis;
- cartões de pressão, vazão baixa e vazão alta;
- seleção automática de faixa com histerese;
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
2. Escolha a porta do ESP32 e o baud rate, normalmente `115200`.
3. Clique em **Conectar** e confirme que os sensores atualizam.
4. Clique em **Iniciar ensaio**.
5. Preencha a identificação da amostra e os dados operacionais.
6. Acompanhe leituras, gráficos, faixa ativa e alarmes.
7. Use **Adicionar marcação** para registrar uma intervenção ou ocorrência.
8. Finalize o ensaio, acrescente a observação final e exporte o resultado.

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

Referências técnicas: [Micromeritics — gas pycnometry and density](https://micromeritics.com/density/),
[Micromeritics — volume, density and porosity](https://micromeritics.com/resources/measuring-volume-density-and-porosity-of-tablets-for-coating-process-control-and-qc/)
e [USGS — Darcy's law and permeability](https://pubs.usgs.gov/publication/70214996).

Os dados são salvos a cada leitura; não é necessário finalizar para preservar amostras já recebidas.

## Modo simulação

Clique em **Iniciar simulação** na faixa superior. A interface mostra um aviso amarelo e todas as leituras recebem qualidade `simulada`.

O seletor ao lado permite demonstrar:

- operação normal, pressão crescente e transição de faixa;
- sensor desconectado;
- corrente de 3,7 mA ou 3,2 mA;
- corrente de 20,2 mA ou 21,0 mA;
- perda temporária de comunicação.

Selecione novamente **Simulação normal** para recuperar a comunicação ou o sensor. O simulador não usa uma porta física.

## Protocolo do ESP32

O ESP32 deve transmitir um objeto JSON UTF-8 por linha. Cada mensagem deve terminar com `\n`.

Mensagem completa:

```json
{
  "timestamp_ms": 152340,
  "pressao_ma": 11.34,
  "pressao": 3.42,
  "vazao_baixa_ma": 7.26,
  "vazao_baixa": 0.85,
  "vazao_alta_ma": 14.08,
  "vazao_alta": 12.60,
  "status": "OK"
}
```

Também é aceita uma mensagem reduzida:

```json
{"pressao": 3.42, "vazao_baixa": 0.85, "vazao_alta": 12.60}
```

Todos os campos são opcionais, mas a linha precisa conter pelo menos um campo de sensor. Campos numéricos inválidos fazem somente aquela mensagem ser descartada; a aplicação permanece aberta. Quando a corrente está disponível, o sistema calcula também o valor de engenharia para comparação.

## Conversão 4–20 mA e faixas

A conversão utilizada é:

```text
valor = limite_inferior + ((corrente_mA - corrente_mínima) /
        (corrente_máxima - corrente_mínima)) *
        (limite_superior - limite_inferior)
valor_calibrado = valor * ganho + offset
```

As faixas iniciais ficam em `config/default_config.json`:

- pressão: 0–10 bar;
- vazão baixa: 0–5 L/min;
- vazão alta: 0–50 L/min.

Altere-as pela tela **Configurações > Sensores**. Reinicie o programa para recriar o parser e os cartões com as novas faixas. As alterações do operador são gravadas em `config/user_config.json`; o arquivo de padrões permanece intacto.

No modo automático, o sensor de alta vazão passa a ser o principal em 90% da faixa baixa e o sistema retorna à faixa baixa abaixo de 75%. Os dois sensores continuam sendo registrados.

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

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Os testes cobrem parser, mensagens reduzidas e corrompidas, conversão 4–20 mA, ganho e offset, histerese, alarmes, calibração, criação/recuperação de ensaio, SQLite e CSV.

## Gerar o executável

Depois de criar o ambiente virtual:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build.ps1
```

O resultado fica em:

```text
dist\PorosimetroSupervisorio_v1_1_1\PorosimetroSupervisorio_v1_1_1.exe
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
