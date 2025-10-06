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

-- Continuous monitoring tables for intelligent learning system

-- Message metadata for classification and analysis
CREATE TABLE IF NOT EXISTS message_metadata (
    message_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    classification TEXT NOT NULL CHECK(classification IN ('high', 'medium', 'low', 'noise')),
    classification_reason TEXT,
    classification_confidence REAL,
    features TEXT, -- JSON of classification features
    processed INTEGER DEFAULT 0,
    processing_timestamp INTEGER,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (message_id, chat_id)
);

-- Conversation windows for grouping related messages
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

-- Fact quality metrics for tracking deduplication and conflicts
CREATE TABLE IF NOT EXISTS fact_quality_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    fact_id INTEGER NOT NULL, -- References user_facts.id
    duplicate_of INTEGER, -- References another fact_id if deduplicated
    conflict_with INTEGER, -- References another fact_id if conflicting
    similarity_score REAL, -- Semantic similarity score
    resolution_method TEXT, -- How conflict was resolved: recency, confidence, merge
    created_at INTEGER NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES user_facts(id) ON DELETE CASCADE
);

-- Proactive response events and user reactions
CREATE TABLE IF NOT EXISTS proactive_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    window_id INTEGER, -- References conversation_windows.id
    trigger_reason TEXT NOT NULL,
    trigger_confidence REAL NOT NULL,
    intent_classification TEXT, -- JSON of intent analysis
    response_sent INTEGER DEFAULT 0,
    response_message_id INTEGER,
    user_reaction TEXT, -- positive, negative, neutral, ignored
    reaction_timestamp INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (window_id) REFERENCES conversation_windows(id) ON DELETE SET NULL
);

-- System health metrics for monitoring
CREATE TABLE IF NOT EXISTS system_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_context TEXT, -- JSON with additional context
    timestamp INTEGER NOT NULL
);

-- Indexes for continuous monitoring tables

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

-- ═══════════════════════════════════════════════════════════════════════════════
-- Phase 1: Memory and Context Improvements - Foundation
-- Added: October 6, 2025
-- ═══════════════════════════════════════════════════════════════════════════════

-- Full-Text Search for keyword-based retrieval (complement to semantic search)
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    content='messages',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync with messages table
CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    UPDATE messages_fts SET text = new.text WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.id;
END;

-- Message importance tracking for adaptive memory management
CREATE TABLE IF NOT EXISTS message_importance (
    message_id INTEGER PRIMARY KEY,
    importance_score REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER DEFAULT 0,
    last_accessed INTEGER,
    retention_days INTEGER,
    consolidated INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_message_importance_score 
    ON message_importance(importance_score DESC);
CREATE INDEX IF NOT EXISTS idx_message_importance_retention 
    ON message_importance(retention_days ASC);
CREATE INDEX IF NOT EXISTS idx_message_importance_consolidated
    ON message_importance(consolidated);

-- Episodic memory for significant conversation events
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    summary_embedding TEXT,  -- JSON array of floats
    importance REAL DEFAULT 0.5,
    emotional_valence TEXT CHECK(emotional_valence IN ('positive', 'negative', 'neutral', 'mixed')),
    message_ids TEXT NOT NULL,  -- JSON array of message IDs
    participant_ids TEXT NOT NULL,  -- JSON array of user IDs
    tags TEXT,  -- JSON array of keywords/tags
    created_at INTEGER NOT NULL,
    last_accessed INTEGER,
    access_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_episodes_chat ON episodes(chat_id, importance DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_importance ON episodes(importance DESC);

-- Episode access log (for importance adjustment)
CREATE TABLE IF NOT EXISTS episode_accesses (
    episode_id INTEGER NOT NULL,
    accessed_at INTEGER NOT NULL,
    access_type TEXT CHECK(access_type IN ('retrieval', 'reference', 'update')),
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_episode_accesses ON episode_accesses(episode_id, accessed_at DESC);

-- Fact relationships for knowledge graph construction
CREATE TABLE IF NOT EXISTS fact_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact1_id INTEGER NOT NULL,
    fact2_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    weight REAL DEFAULT 0.5,
    inferred INTEGER DEFAULT 1,  -- 0 = explicit, 1 = inferred
    evidence TEXT,  -- JSON metadata
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (fact1_id) REFERENCES user_facts(id) ON DELETE CASCADE,
    FOREIGN KEY (fact2_id) REFERENCES user_facts(id) ON DELETE CASCADE,
    UNIQUE (fact1_id, fact2_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_fact_relationships_fact1 
    ON fact_relationships(fact1_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_fact_relationships_fact2 
    ON fact_relationships(fact2_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_fact_relationships_type
    ON fact_relationships(relationship_type);

-- Fact versions for temporal tracking
CREATE TABLE IF NOT EXISTS fact_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER NOT NULL,
    previous_version_id INTEGER,
    version_number INTEGER NOT NULL,
    change_type TEXT CHECK(change_type IN ('creation', 'reinforcement', 'evolution', 'correction', 'contradiction')),
    confidence_delta REAL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES user_facts(id) ON DELETE CASCADE,
    FOREIGN KEY (previous_version_id) REFERENCES user_facts(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_fact_versions_fact 
    ON fact_versions(fact_id, version_number);
CREATE INDEX IF NOT EXISTS idx_fact_versions_previous 
    ON fact_versions(previous_version_id);

-- Fact clusters for topic-based organization
CREATE TABLE IF NOT EXISTS fact_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    cluster_name TEXT NOT NULL,
    fact_ids TEXT NOT NULL,  -- JSON array
    centroid_embedding TEXT,  -- JSON array
    coherence_score REAL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fact_clusters_user 
    ON fact_clusters(user_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_fact_clusters_coherence
    ON fact_clusters(coherence_score DESC);

-- Additional indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts DESC);
CREATE INDEX IF NOT EXISTS idx_messages_user_ts ON messages(user_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, ts DESC);

-- Context retrieval performance indexes
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS idx_messages_embedding_not_null ON messages(embedding) WHERE embedding IS NOT NULL;


