-- ============================================================
-- BROKER GATEWAY - Database Migration
-- Projeto: dytkmkydqatprzeshjns.supabase.co
-- Execute este SQL no Supabase Dashboard > SQL Editor
-- ============================================================

-- Enable pgcrypto for encryption
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- TABLE: broker_connections
-- Stores broker connection configurations with encrypted credentials
-- ============================================================
CREATE TABLE IF NOT EXISTS broker_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    broker TEXT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'practice' CHECK (account_type IN ('practice', 'real', 'demo')),
    status TEXT NOT NULL DEFAULT 'disconnected' CHECK (status IN ('disconnected', 'connecting', 'connected', 'ready', 'error')),
    email_encrypted TEXT,
    password_encrypted TEXT,
    server TEXT,
    error_message TEXT,
    last_heartbeat TIMESTAMPTZ,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_broker_connections_user_id ON broker_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_broker_connections_broker ON broker_connections(broker);
CREATE INDEX IF NOT EXISTS idx_broker_connections_status ON broker_connections(status);

-- ============================================================
-- TABLE: broker_orders
-- Stores order history from all brokers
-- ============================================================
CREATE TABLE IF NOT EXISTS broker_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES broker_connections(id) ON DELETE CASCADE,
    broker_order_id TEXT,
    asset TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('CALL', 'PUT')),
    amount NUMERIC(12,2) NOT NULL,
    expiration INTEGER DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'pending', 'accepted', 'rejected', 'open', 'closed', 'error', 'timeout')),
    result TEXT CHECK (result IN ('WIN', 'LOSS', 'DRAW')),
    profit NUMERIC(12,2) DEFAULT 0,
    payout NUMERIC(8,4) DEFAULT 0,
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_broker_orders_connection_id ON broker_orders(connection_id);
CREATE INDEX IF NOT EXISTS idx_broker_orders_status ON broker_orders(status);
CREATE INDEX IF NOT EXISTS idx_broker_orders_created_at ON broker_orders(created_at DESC);

-- ============================================================
-- TABLE: broker_events
-- Stores event history for auditing and logging
-- ============================================================
CREATE TABLE IF NOT EXISTS broker_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID REFERENCES broker_connections(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    event_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_broker_events_connection_id ON broker_events(connection_id);
CREATE INDEX IF NOT EXISTS idx_broker_events_type ON broker_events(event_type);
CREATE INDEX IF NOT EXISTS idx_broker_events_created_at ON broker_events(created_at DESC);

-- ============================================================
-- FUNCTION: Auto-update updated_at on broker_connections
-- ============================================================
CREATE OR REPLACE FUNCTION update_broker_connections_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_broker_connections_updated_at ON broker_connections;
CREATE TRIGGER trigger_update_broker_connections_updated_at
    BEFORE UPDATE ON broker_connections
    FOR EACH ROW
    EXECUTE FUNCTION update_broker_connections_updated_at();

-- ============================================================
-- FUNCTION: Decrypt broker credentials
-- ============================================================
CREATE OR REPLACE FUNCTION decrypt_broker_credentials(
    p_email_encrypted TEXT,
    p_password_encrypted TEXT,
    p_encryption_key TEXT
)
RETURNS TABLE(email TEXT, password TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_email TEXT := '';
    v_password TEXT := '';
BEGIN
    IF p_email_encrypted IS NOT NULL AND p_email_encrypted != '' THEN
        BEGIN
            v_email := pgp_sym_decrypt(
                decode(p_email_encrypted, 'base64'),
                p_encryption_key
            );
        EXCEPTION WHEN OTHERS THEN
            v_email := p_email_encrypted;
        END;
    END IF;
    
    IF p_password_encrypted IS NOT NULL AND p_password_encrypted != '' THEN
        BEGIN
            v_password := pgp_sym_decrypt(
                decode(p_password_encrypted, 'base64'),
                p_encryption_key
            );
        EXCEPTION WHEN OTHERS THEN
            v_password := p_password_encrypted;
        END;
    END IF;
    
    RETURN QUERY SELECT v_email, v_password;
END;
$$;

GRANT EXECUTE ON FUNCTION decrypt_broker_credentials(TEXT, TEXT, TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION decrypt_broker_credentials(TEXT, TEXT, TEXT) TO service_role;

-- ============================================================
-- VIEW: Safe view without encrypted credentials
-- ============================================================
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
    updated_at
FROM broker_connections;

-- ============================================================
-- RLS Policies (Row Level Security)
-- ============================================================
ALTER TABLE broker_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE broker_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE broker_events ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist
DROP POLICY IF EXISTS "Users can view own broker connections" ON broker_connections;
DROP POLICY IF EXISTS "Users can insert own broker connections" ON broker_connections;
DROP POLICY IF EXISTS "Users can update own broker connections" ON broker_connections;
DROP POLICY IF EXISTS "Users can delete own broker connections" ON broker_connections;
DROP POLICY IF EXISTS "Users can view own broker orders" ON broker_orders;
DROP POLICY IF EXISTS "Users can insert own broker orders" ON broker_orders;
DROP POLICY IF EXISTS "Users can view own broker events" ON broker_events;
DROP POLICY IF EXISTS "Users can insert own broker events" ON broker_events;

-- Broker connections policies
CREATE POLICY "Users can view own broker connections"
    ON broker_connections FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own broker connections"
    ON broker_connections FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own broker connections"
    ON broker_connections FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own broker connections"
    ON broker_connections FOR DELETE
    USING (auth.uid() = user_id);

-- Broker orders policies
CREATE POLICY "Users can view own broker orders"
    ON broker_orders FOR SELECT
    USING (
        connection_id IN (
            SELECT id FROM broker_connections WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert own broker orders"
    ON broker_orders FOR INSERT
    WITH CHECK (
        connection_id IN (
            SELECT id FROM broker_connections WHERE user_id = auth.uid()
        )
    );

-- Broker events policies
CREATE POLICY "Users can view own broker events"
    ON broker_events FOR SELECT
    USING (
        connection_id IS NULL OR
        connection_id IN (
            SELECT id FROM broker_connections WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert own broker events"
    ON broker_events FOR INSERT
    WITH CHECK (
        connection_id IS NULL OR
        connection_id IN (
            SELECT id FROM broker_connections WHERE user_id = auth.uid()
        )
    );

-- ============================================================
-- Comments for documentation
-- ============================================================
COMMENT ON TABLE broker_connections IS 'Stores broker connection configurations with encrypted credentials';
COMMENT ON TABLE broker_orders IS 'Stores order history from all brokers';
COMMENT ON TABLE broker_events IS 'Stores event history for auditing and logging';
COMMENT ON COLUMN broker_connections.email_encrypted IS 'Encrypted broker login email (pgp_sym_encrypt)';
COMMENT ON COLUMN broker_connections.password_encrypted IS 'Encrypted broker login password (pgp_sym_encrypt)';
