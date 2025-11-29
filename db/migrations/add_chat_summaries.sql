-- ═══════════════════════════════════════════════════════════════════════════════
-- Chat Summaries Table
-- Added: 2025-01-XX
-- Purpose: Store 30-day and 7-day chat history summaries for dynamic system instructions
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS chat_summaries (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    summary_type TEXT NOT NULL CHECK(summary_type IN ('30days', '7days')),
    period_start BIGINT NOT NULL,
    period_end BIGINT NOT NULL,
    summary_text TEXT NOT NULL,
    token_count INTEGER,
    generated_at BIGINT NOT NULL,
    model_version TEXT,
    UNIQUE(chat_id, summary_type, period_start)
);

CREATE INDEX IF NOT EXISTS idx_chat_summaries_chat_type
    ON chat_summaries(chat_id, summary_type, period_end DESC);

CREATE INDEX IF NOT EXISTS idx_chat_summaries_period
    ON chat_summaries(period_start, period_end);

