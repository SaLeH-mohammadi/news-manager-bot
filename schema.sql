-- Supabase Schema for Multi-Tenant News Manager Bot

CREATE TABLE IF NOT EXISTS nm_kv (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nm_hashes (
    hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nm_queue (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    msg_id BIGINT NOT NULL,
    text TEXT,
    media_type TEXT, -- 'photo', 'video', or NULL
    media_file_id TEXT, -- local cached path
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'processing', 'published', 'rejected', 'failed'
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nm_queue_user_status_id ON nm_queue(user_id, status, id);
CREATE INDEX IF NOT EXISTS idx_nm_hashes_user_hash ON nm_hashes(user_id, hash);
