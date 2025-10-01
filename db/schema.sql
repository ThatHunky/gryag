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

CREATE TABLE IF NOT EXISTS polls (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    creator_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    options TEXT NOT NULL, -- JSON array of poll options
    poll_type TEXT NOT NULL CHECK(poll_type IN ('regular', 'multiple', 'anonymous')),
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    is_closed INTEGER NOT NULL DEFAULT 0,
    allow_multiple INTEGER NOT NULL DEFAULT 0,
    is_anonymous INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS poll_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    option_index INTEGER NOT NULL,
    voted_at INTEGER NOT NULL,
    FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE,
    UNIQUE (poll_id, user_id, option_index)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_thread_ts
    ON messages(chat_id, thread_id, ts);

CREATE INDEX IF NOT EXISTS idx_quotas_chat_user_ts
    ON quotas(chat_id, user_id, ts);

CREATE INDEX IF NOT EXISTS idx_notices_chat_user
    ON notices(chat_id, user_id);

CREATE INDEX IF NOT EXISTS idx_bans_chat_user
    ON bans(chat_id, user_id);

CREATE INDEX IF NOT EXISTS idx_polls_chat_thread
    ON polls(chat_id, thread_id);

CREATE INDEX IF NOT EXISTS idx_polls_creator
    ON polls(creator_id);

CREATE INDEX IF NOT EXISTS idx_polls_expires
    ON polls(expires_at);

CREATE INDEX IF NOT EXISTS idx_poll_votes_poll_user
    ON poll_votes(poll_id, user_id);

CREATE INDEX IF NOT EXISTS idx_poll_votes_user
    ON poll_votes(user_id);

-- User profiling tables for learning about users over time
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    display_name TEXT,
    username TEXT,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    last_active_thread INTEGER,
    interaction_count INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    summary TEXT,
    profile_version INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS user_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    fact_type TEXT NOT NULL CHECK(fact_type IN ('personal', 'preference', 'trait', 'relationship', 'skill', 'opinion')),
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source_message_id INTEGER,
    evidence_text TEXT,
    is_active INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_mentioned INTEGER,
    FOREIGN KEY (user_id, chat_id) REFERENCES user_profiles(user_id, chat_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    related_user_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL CHECK(relationship_type IN ('friend', 'colleague', 'family', 'adversary', 'mentioned', 'unknown')),
    relationship_label TEXT,
    strength REAL DEFAULT 0.5,
    interaction_count INTEGER DEFAULT 0,
    last_interaction INTEGER,
    sentiment TEXT DEFAULT 'neutral' CHECK(sentiment IN ('positive', 'negative', 'neutral', 'mixed')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (user_id, chat_id, related_user_id),
    FOREIGN KEY (user_id, chat_id) REFERENCES user_profiles(user_id, chat_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_user
    ON user_profiles(user_id);

CREATE INDEX IF NOT EXISTS idx_user_profiles_chat
    ON user_profiles(chat_id);

CREATE INDEX IF NOT EXISTS idx_user_profiles_last_seen
    ON user_profiles(last_seen);

CREATE INDEX IF NOT EXISTS idx_user_facts_user_chat
    ON user_facts(user_id, chat_id);

CREATE INDEX IF NOT EXISTS idx_user_facts_type
    ON user_facts(fact_type);

CREATE INDEX IF NOT EXISTS idx_user_facts_key
    ON user_facts(fact_key);

CREATE INDEX IF NOT EXISTS idx_user_facts_active
    ON user_facts(is_active);

CREATE INDEX IF NOT EXISTS idx_user_facts_confidence
    ON user_facts(confidence);

CREATE INDEX IF NOT EXISTS idx_user_relationships_user
    ON user_relationships(user_id, chat_id);

CREATE INDEX IF NOT EXISTS idx_user_relationships_related
    ON user_relationships(related_user_id);

CREATE INDEX IF NOT EXISTS idx_user_relationships_type
    ON user_relationships(relationship_type);

CREATE INDEX IF NOT EXISTS idx_user_relationships_strength
    ON user_relationships(strength);

