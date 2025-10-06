-- Normalize message table column names
-- Rename 'id' to 'message_id' and 'ts' to 'created_at' for consistency

-- Create new table with correct column names
CREATE TABLE messages_new (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    user_id INTEGER,
    role TEXT NOT NULL CHECK(role IN ('user', 'model', 'system')),
    text TEXT,
    media TEXT,
    embedding TEXT,
    metadata TEXT DEFAULT '{}',
    created_at INTEGER NOT NULL
);

-- Copy data from old table
INSERT INTO messages_new (
    message_id, chat_id, thread_id, user_id, role,
    text, media, embedding, metadata, created_at
)
SELECT 
    id, chat_id, thread_id, user_id, role,
    text, media, embedding,
    COALESCE(metadata, '{}'),
    ts
FROM messages;

-- Drop old table
DROP TABLE messages;

-- Rename new table
ALTER TABLE messages_new RENAME TO messages;

-- Recreate indexes with new column names
CREATE INDEX IF NOT EXISTS idx_messages_chat_thread_created
    ON messages(chat_id, thread_id, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_metadata
    ON messages(metadata) WHERE metadata IS NOT NULL AND metadata != '{}';
