# Arquitetura, unidades e hipóteses

O ESP32 envia somente pressão obtida pelo ADS1115. O PC lê o flowmeter por
USB–RS485 Modbus RTU: 9600 8N1, slave 1, função 03, registro `0x003A`, dois
registradores UINT32 big-endian e escala `raw/1000`. Não há escrita Modbus.
O parser marca o valor como `NL/min`; a leitura, a medição e a linha SQLite
guardam a unidade. Séries legadas sem unidade permanecem sem classificação.

`NL/min` é volume de gás referido a pressão absoluta `Pn` e temperatura `Tn`
confirmadas no flowmeter. O cálculo usa `Qref = Qn × Tensaio/Tn` e `Pref = Pn`.
Essa transformação vem da conservação do fluxo molar de um gás ideal e requer
temperaturas em Kelvin. `L/min` é volume nas condições informadas para a vazão;
`mL/min` é dividido por 1000 para obter `L/min`. A configuração padrão deixa
`Pn` e `Tn` vazios; o operador deve confirmar a configuração física e registrá-la
antes de calcular com `NL/min`. A pressão de referência na tela é absoluta.

O modelo de Darcy para gás compressível ideal, fluxo estacionário e isotérmico é
`k = 2 μ L Qref Pref / [A (Pin² − Pout²)]`, em SI. `Pin` e `Pout` são pressões
absolutas; a pressão manométrica recebe a pressão atmosférica. `μ` é a
viscosidade dinâmica em Pa·s (`µPa·s × 10⁻⁶`), `L` é o comprimento em metros,
`A = πd²/4` em m², `Qref` em m³/s (`L/min ÷ 60000`) e pressões em Pa.
`1 D = 9,869233×10⁻¹³ m²` e `1 mD = 10⁻³ D`. As viscosidades pré-definidas
são valores de referência próximos de 20 °C; o operador deve informar a
viscosidade adequada à temperatura real do ensaio. Temperatura variável ao
longo da amostra e gás não ideal exigem modelo e validação metrológica próprios.

A correção de Klinkenberg ajusta `k_aparente = k∞ + m/Pm` por mínimos quadrados,
com `Pm=(Pin+Pout)/2` em kPa abs. O fator `b=m/k∞` sai em kPa. `R²=1−SSE/SST`;
quando todos os valores de permeabilidade são iguais e o ajuste é exato, `R²=1`.
São exigidas pelo menos duas pressões médias distintas e `k∞>0`.

O schema SQLite 5 preserva `duracao_segundos` como tempo ativo para ensaios
novos e adiciona duração total e pausada. Para ensaios anteriores, apenas o
valor legado está disponível: o relatório o identifica como tempo decorrido.
