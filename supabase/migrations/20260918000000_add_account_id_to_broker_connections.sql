-- Migration: account_id de corretora + exposição na view segura
-- Data: 2026-09-18

-- Coluna que guarda o ID da conta na corretora (ex: ID de perfil IQ Option)
ALTER TABLE broker_connections ADD COLUMN IF NOT EXISTS account_id TEXT;

-- Recria a view safe incluindo account_id como ÚLTIMA coluna
-- (CREATE OR REPLACE VIEW exige mesma ordem/nomes das colunas existentes).
-- Continua SEM expor email_encrypted / password_encrypted.
CREATE OR REPLACE VIEW broker_connections_safe AS
SELECT
    id,
    user_id,
    name,
    broker,
    account_type,
    status,
    server,
    error_message,
    last_heartbeat,
    enabled,
    created_at,
    updated_at,
    account_id
FROM broker_connections;
