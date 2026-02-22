-- Add file_id column for Telegram media recall and full-text search index.

-- Store Telegram file_id for photos, videos, documents, voice, etc.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS file_id TEXT;

-- PostgreSQL full-text search: generated tsvector column with GIN index.
-- Searches across text content with Ukrainian + English language support.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', COALESCE(text, '')), 'A') ||
        setweight(to_tsvector('simple', COALESCE(first_name, '')), 'B') ||
        setweight(to_tsvector('simple', COALESCE(username, '')), 'C')
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_messages_search ON messages USING GIN (search_vector);

-- Index for fast file_id lookups (media recall)
CREATE INDEX IF NOT EXISTS idx_messages_file_id ON messages (file_id) WHERE file_id IS NOT NULL;

-- Index for fast chat_id + message_id lookups (deep links)
CREATE INDEX IF NOT EXISTS idx_messages_chat_message ON messages (chat_id, message_id);
