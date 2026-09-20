# Histórico de versões

## 2.3.0 — 2026-09-20

- Unidade da vazão rastreada desde Modbus; referência normal explícita e bloqueio
  do cálculo `NL/min` sem dados confirmados.
- Duração ativa, pausada e decorrida persistidas no schema 5; duração legada
  identificada como decorrido sem precisão de pausa.
- Pontos de Klinkenberg identificados pela origem e entradas do cálculo;
  duplicação por cliques bloqueada e resultado invalidado após remoção.
- Validações físicas e transações SQLite reforçadas.
- Build Windows com testes, firmware, pacote, smoke PDF e SHA-256.

O firmware segue em 2.2.0; sua versão é independente.
