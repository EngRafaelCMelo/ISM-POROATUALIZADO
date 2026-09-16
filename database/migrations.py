from __future__ import annotations

import sqlite3


SCHEMA_VERSION = 3

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
INSERT INTO schema_version(version)
SELECT 3 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    ativo INTEGER NOT NULL DEFAULT 1
);
INSERT OR IGNORE INTO usuarios(nome) VALUES ('Operador');

CREATE TABLE IF NOT EXISTS amostras (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    identificacao TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ensaios (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE,
    amostra_id INTEGER,
    amostra_nome TEXT NOT NULL,
    amostra_identificacao TEXT,
    operador TEXT NOT NULL,
    descricao TEXT,
    tipo TEXT,
    observacoes TEXT,
    observacao_final TEXT,
    faixa_pressao TEXT,
    flow_meter_principal TEXT,
    unidade_pressao TEXT,
    unidade_vazao TEXT,
    intervalo_aquisicao REAL,
    diretorio_exportacao TEXT,
    comprimento_amostra_mm REAL,
    diametro_amostra_mm REAL,
    massa_amostra_g REAL,
    volume_geometrico_cm3 REAL,
    tipo_gas TEXT,
    temperatura_c REAL,
    pressao_atmosferica_kpa REAL,
    referencia_pressao TEXT,
    configuracao_json TEXT,
    versao_firmware TEXT,
    simulado INTEGER NOT NULL DEFAULT 0,
    inicio TEXT NOT NULL,
    fim TEXT,
    duracao_segundos REAL DEFAULT 0,
    quantidade_amostras INTEGER DEFAULT 0,
    pressao_maxima REAL,
    vazao_maxima REAL,
    status TEXT NOT NULL,
    FOREIGN KEY(amostra_id) REFERENCES amostras(id)
);

CREATE TABLE IF NOT EXISTS medicoes (
    id INTEGER PRIMARY KEY,
    ensaio_id INTEGER NOT NULL,
    timestamp_computador TEXT NOT NULL,
    timestamp_esp32 INTEGER,
    pressao_ma REAL,
    pressao REAL,
    pressao_ads_raw REAL,
    unidade_pressao TEXT,
    pressao_valida INTEGER,
    vazao_raw REAL,
    vazao REAL,
    unidade_vazao TEXT,
    vazao_valida INTEGER,
    sequencia INTEGER,
    versao_schema INTEGER,
    versao_firmware TEXT,
    simulado INTEGER NOT NULL DEFAULT 0,
    vazao_baixa_ma REAL,
    vazao_baixa REAL,
    vazao_alta_ma REAL,
    vazao_alta REAL,
    flow_meter_ativo TEXT,
    qualidade TEXT,
    estado_comunicacao TEXT,
    mensagem_original TEXT,
    FOREIGN KEY(ensaio_id) REFERENCES ensaios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY,
    ensaio_id INTEGER,
    timestamp TEXT NOT NULL,
    categoria TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    detalhes TEXT,
    FOREIGN KEY(ensaio_id) REFERENCES ensaios(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS alarmes (
    id INTEGER PRIMARY KEY,
    ensaio_id INTEGER,
    timestamp TEXT NOT NULL,
    sensor TEXT,
    severidade TEXT NOT NULL,
    categoria TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    valor_medido REAL,
    limite REAL,
    reconhecido INTEGER DEFAULT 0,
    observacao_operador TEXT,
    FOREIGN KEY(ensaio_id) REFERENCES ensaios(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS calibracoes (
    id INTEGER PRIMARY KEY,
    sensor TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    operador TEXT NOT NULL,
    ganho REAL NOT NULL,
    offset REAL NOT NULL,
    erro REAL,
    estavel INTEGER NOT NULL,
    pontos_json TEXT NOT NULL,
    observacoes TEXT,
    ativa INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor_json TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS marcacoes (
    id INTEGER PRIMARY KEY,
    ensaio_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    categoria TEXT,
    comentario TEXT NOT NULL,
    FOREIGN KEY(ensaio_id) REFERENCES ensaios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS calculos (
    id INTEGER PRIMARY KEY,
    ensaio_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    tipo TEXT NOT NULL,
    entradas_json TEXT NOT NULL,
    resultados_json TEXT NOT NULL,
    valido INTEGER NOT NULL DEFAULT 1,
    observacoes TEXT,
    FOREIGN KEY(ensaio_id) REFERENCES ensaios(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_medicoes_ensaio_tempo
ON medicoes(ensaio_id, timestamp_computador);
CREATE INDEX IF NOT EXISTS idx_alarmes_ensaio_tempo
ON alarmes(ensaio_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_ensaios_inicio ON ensaios(inicio);
CREATE INDEX IF NOT EXISTS idx_calculos_ensaio ON calculos(ensaio_id, timestamp);
"""


TEST_COLUMNS: dict[str, str] = {
    "comprimento_amostra_mm": "REAL",
    "diametro_amostra_mm": "REAL",
    "massa_amostra_g": "REAL",
    "volume_geometrico_cm3": "REAL",
    "tipo_gas": "TEXT",
    "temperatura_c": "REAL",
    "pressao_atmosferica_kpa": "REAL",
    "referencia_pressao": "TEXT",
    "configuracao_json": "TEXT",
    "versao_firmware": "TEXT",
    "simulado": "INTEGER NOT NULL DEFAULT 0",
}

MEASUREMENT_COLUMNS: dict[str, str] = {
    "pressao_ads_raw": "REAL", "unidade_pressao": "TEXT", "pressao_valida": "INTEGER",
    "vazao_raw": "REAL", "vazao": "REAL", "unidade_vazao": "TEXT", "vazao_valida": "INTEGER",
    "sequencia": "INTEGER", "versao_schema": "INTEGER", "versao_firmware": "TEXT",
    "simulado": "INTEGER NOT NULL DEFAULT 0",
}


def apply_migrations(connection: sqlite3.Connection) -> None:
    """Atualiza bancos existentes sem descartar dados."""
    existing = {
        row[1] for row in connection.execute("PRAGMA table_info(ensaios)").fetchall()
    }
    for name, sql_type in TEST_COLUMNS.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE ensaios ADD COLUMN {name} {sql_type}")
    measurement_existing = {row[1] for row in connection.execute("PRAGMA table_info(medicoes)")}
    for name, sql_type in MEASUREMENT_COLUMNS.items():
        if name not in measurement_existing:
            connection.execute(f"ALTER TABLE medicoes ADD COLUMN {name} {sql_type}")
    connection.execute(
        """UPDATE medicoes SET vazao=COALESCE(vazao, vazao_baixa, vazao_alta),
           unidade_vazao=COALESCE(unidade_vazao, 'L/min'), versao_schema=COALESCE(versao_schema, 0)
           WHERE vazao IS NULL"""
    )
    connection.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
