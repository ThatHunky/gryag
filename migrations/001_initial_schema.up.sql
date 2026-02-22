-- ============================================================
-- Gryag V2 — Initial Database Schema
-- ============================================================

-- Message log: every incoming message is stored for context.
-- Throttled messages are also logged here (Section 10).
CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    chat_id         BIGINT NOT NULL,
    user_id         BIGINT,
    username        TEXT,
    first_name      TEXT,
    text            TEXT,
    message_id      BIGINT,
    media_type      TEXT,
    is_bot_reply    BOOLEAN DEFAULT FALSE,
    request_id      TEXT,
    was_throttled   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_chat_id ON messages (chat_id);
CREATE INDEX idx_messages_user_id ON messages (user_id);
CREATE INDEX idx_messages_created_at ON messages (created_at DESC);
CREATE INDEX idx_messages_chat_created ON messages (chat_id, created_at DESC);

-- User facts: long-term memory about individual users (Section 7).
CREATE TABLE IF NOT EXISTS user_facts (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    fact_text   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_facts_lookup ON user_facts (chat_id, user_id);
CREATE UNIQUE INDEX idx_user_facts_dedup ON user_facts (chat_id, user_id, md5(fact_text));

-- Chat summaries: consolidated 7-day and 30-day summaries (Section 8).
CREATE TABLE IF NOT EXISTS chat_summaries (
    id              BIGSERIAL PRIMARY KEY,
    chat_id         BIGINT NOT NULL,
    summary_type    TEXT NOT NULL CHECK (summary_type IN ('7day', '30day')),
    summary_text    TEXT NOT NULL,
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chat_summaries_lookup ON chat_summaries (chat_id, summary_type, period_end DESC);

-- Media cache: temporary storage references for generated images (Section 9).
CREATE TABLE IF NOT EXISTS media_cache (
    id          BIGSERIAL PRIMARY KEY,
    media_id    TEXT UNIQUE NOT NULL,
    chat_id     BIGINT NOT NULL,
    user_id     BIGINT,
    file_path   TEXT NOT NULL,
    media_type  TEXT NOT NULL DEFAULT 'image',
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_media_cache_media_id ON media_cache (media_id);
CREATE INDEX idx_media_cache_expires ON media_cache (expires_at);
