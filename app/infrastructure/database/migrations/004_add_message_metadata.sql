-- Add metadata column to messages table
-- Stores structured metadata as JSON

ALTER TABLE messages ADD COLUMN metadata TEXT DEFAULT '{}';

-- Add index for faster metadata queries
CREATE INDEX IF NOT EXISTS idx_messages_metadata
    ON messages(metadata) WHERE metadata IS NOT NULL AND metadata != '{}';
