-- Rollback message search additions.

DROP INDEX IF EXISTS idx_messages_chat_message;
DROP INDEX IF EXISTS idx_messages_file_id;
DROP INDEX IF EXISTS idx_messages_search;
ALTER TABLE messages DROP COLUMN IF EXISTS search_vector;
ALTER TABLE messages DROP COLUMN IF EXISTS file_id;
