-- Migration: persistência do SSID de sessão white-label (Polarium / Quadcode)
-- Data: 2026-10-20
--
-- Motivo: conexões criadas apenas com SSID (sem e-mail/senha) precisam do
-- cookie ssid para reconectar (POST /connections/{id}/connect e auto-reconnect
-- após restart). O SSID NÃO é exposto na view segura — só é lido internamente
-- pelo backend via get_with_credentials.

-- Coluna que guarda o cookie ssid da sessão Quadcode
ALTER TABLE broker_connections ADD COLUMN IF NOT EXISTS ssid_encrypted TEXT;

COMMENT ON COLUMN broker_connections.ssid_encrypted IS
    'Quadcode session ssid used to reconnect without password (never exposed by broker_connections_safe)';

-- ============================================================
-- FUNCTION: Decrypt broker ssid (espelha decrypt_broker_credentials)
-- Fallback: se o valor não estiver em PGP, retorna o valor cru.
-- ============================================================
CREATE OR REPLACE FUNCTION decrypt_broker_ssid(
    p_ssid_encrypted TEXT,
    p_encryption_key TEXT
)
RETURNS TABLE(ssid TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_ssid TEXT := '';
BEGIN
    IF p_ssid_encrypted IS NOT NULL AND p_ssid_encrypted != '' THEN
        BEGIN
            v_ssid := pgp_sym_decrypt(
                decode(p_ssid_encrypted, 'base64'),
                p_encryption_key
            );
        EXCEPTION WHEN OTHERS THEN
            v_ssid := p_ssid_encrypted;
        END;
    END IF;

    RETURN QUERY SELECT v_ssid;
END;
$$;

GRANT EXECUTE ON FUNCTION decrypt_broker_ssid(TEXT, TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION decrypt_broker_ssid(TEXT, TEXT) TO service_role;
