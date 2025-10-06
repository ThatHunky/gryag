-- Add continuous monitoring tables
-- Enables intelligent learning and proactive responses

CREATE TABLE IF NOT EXISTS message_metadata (
    message_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    classification TEXT NOT NULL CHECK(classification IN ('high', 'medium', 'low', 'noise')),
    classification_reason TEXT,
    classification_confidence REAL,
    features TEXT,
    processed INTEGER DEFAULT 0,
    processing_timestamp INTEGER,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (message_id, chat_id)
);

CREATE TABLE IF NOT EXISTS conversation_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    first_message_id INTEGER NOT NULL,
    last_message_id INTEGER NOT NULL,
    message_count INTEGER DEFAULT 0,
    participant_count INTEGER DEFAULT 0,
    dominant_value TEXT CHECK(dominant_value IN ('high', 'medium', 'low', 'noise')),
    has_high_value INTEGER DEFAULT 0,
    first_timestamp INTEGER NOT NULL,
    last_timestamp INTEGER NOT NULL,
    closed_at INTEGER NOT NULL,
    closure_reason TEXT,
    processed INTEGER DEFAULT 0,
    facts_extracted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fact_quality_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    fact_id INTEGER NOT NULL,
    duplicate_of INTEGER,
    conflict_with INTEGER,
    similarity_score REAL,
    resolution_method TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES user_facts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS proactive_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    window_id INTEGER,
    trigger_reason TEXT NOT NULL,
    trigger_confidence REAL NOT NULL,
    intent_classification TEXT,
    response_sent INTEGER DEFAULT 0,
    response_message_id INTEGER,
    user_reaction TEXT,
    reaction_timestamp INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (window_id) REFERENCES conversation_windows(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS system_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_context TEXT,
    timestamp INTEGER NOT NULL
);

-- Indexes for monitoring tables
CREATE INDEX IF NOT EXISTS idx_message_metadata_chat
    ON message_metadata(chat_id, thread_id);

CREATE INDEX IF NOT EXISTS idx_message_metadata_classification
    ON message_metadata(classification);

CREATE INDEX IF NOT EXISTS idx_message_metadata_processed
    ON message_metadata(processed);

CREATE INDEX IF NOT EXISTS idx_conversation_windows_chat
    ON conversation_windows(chat_id, thread_id);

CREATE INDEX IF NOT EXISTS idx_conversation_windows_closed
    ON conversation_windows(closed_at);

CREATE INDEX IF NOT EXISTS idx_conversation_windows_processed
    ON conversation_windows(processed);

CREATE INDEX IF NOT EXISTS idx_fact_quality_metrics_fact
    ON fact_quality_metrics(fact_id);

CREATE INDEX IF NOT EXISTS idx_fact_quality_metrics_duplicate
    ON fact_quality_metrics(duplicate_of);

CREATE INDEX IF NOT EXISTS idx_fact_quality_metrics_conflict
    ON fact_quality_metrics(conflict_with);

CREATE INDEX IF NOT EXISTS idx_proactive_events_chat
    ON proactive_events(chat_id, thread_id);

CREATE INDEX IF NOT EXISTS idx_proactive_events_window
    ON proactive_events(window_id);

CREATE INDEX IF NOT EXISTS idx_proactive_events_created
    ON proactive_events(created_at);

CREATE INDEX IF NOT EXISTS idx_system_health_metric
    ON system_health(metric_name, timestamp);
