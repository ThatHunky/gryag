PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    user_id INTEGER,
    role TEXT NOT NULL CHECK(role IN ('user', 'model', 'system')),
    text TEXT,
    media TEXT,
    embedding TEXT,
    ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS quotas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS notices (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    ts INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id, kind)
);

CREATE TABLE IF NOT EXISTS bans (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_thread_ts
    ON messages(chat_id, thread_id, ts);

CREATE INDEX IF NOT EXISTS idx_quotas_chat_user_ts
    ON quotas(chat_id, user_id, ts);

CREATE INDEX IF NOT EXISTS idx_notices_chat_user
    ON notices(chat_id, user_id);

CREATE INDEX IF NOT EXISTS idx_bans_chat_user
    ON bans(chat_id, user_id);
