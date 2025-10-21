PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    user_id INTEGER,
    -- External IDs stored as text to avoid precision loss in JSON or clients
    external_message_id TEXT,
    external_user_id TEXT,
    reply_to_external_message_id TEXT,
    reply_to_external_user_id TEXT,
    role TEXT NOT NULL CHECK(role IN ('user', 'model', 'system')),
    text TEXT,
    media TEXT,
    embedding TEXT,
    ts INTEGER NOT NULL
);

-- Indexes for external ID lookups (Phase A)
CREATE INDEX IF NOT EXISTS idx_messages_chat_external_msg
    ON messages(chat_id, external_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat_external_user
    ON messages(chat_id, external_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat_reply_external_msg
    ON messages(chat_id, reply_to_external_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat_reply_external_user
    ON messages(chat_id, reply_to_external_user_id);

CREATE TABLE IF NOT EXISTS bans (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    last_notice_time INTEGER,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS rate_limits (
    user_id INTEGER NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    PRIMARY KEY (user_id, window_start)
);

CREATE INDEX IF NOT EXISTS idx_rate_limits_window
    ON rate_limits(window_start);

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
    pronouns TEXT,
    membership_status TEXT DEFAULT 'unknown',
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

-- Unified fact storage shared by user and chat memories
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Entity identification
    entity_type TEXT NOT NULL CHECK(entity_type IN ('user', 'chat')),
    entity_id INTEGER NOT NULL,  -- user_id or chat_id
    chat_context INTEGER,  -- chat_id where this was learned (for user facts only)

    -- Fact taxonomy (unified categories)
    fact_category TEXT NOT NULL CHECK(fact_category IN (
        -- User-level categories
        'personal', 'preference', 'skill', 'trait', 'opinion', 'relationship',
        -- Chat-level categories
        'tradition', 'rule', 'norm', 'topic', 'culture', 'event', 'shared_knowledge'
    )),

    -- Fact content
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    fact_description TEXT,

    -- Confidence and evidence
    confidence REAL DEFAULT 0.7 CHECK(confidence >= 0 AND confidence <= 1),
    evidence_count INTEGER DEFAULT 1,
    evidence_text TEXT,
    source_message_id INTEGER,

    -- Consensus (for chat facts)
    participant_consensus REAL,
    participant_ids TEXT,  -- JSON array

    -- Lifecycle
    first_observed INTEGER NOT NULL,
    last_reinforced INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,
    decay_rate REAL DEFAULT 0.0,

    -- Metadata
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,

    -- Embedding for semantic search
    embedding TEXT,

    -- Composite unique constraint
    UNIQUE(entity_type, entity_id, chat_context, fact_category, fact_key)
);

CREATE INDEX IF NOT EXISTS idx_facts_entity
    ON facts(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_facts_chat_context
    ON facts(chat_context) WHERE entity_type = 'user';

CREATE INDEX IF NOT EXISTS idx_facts_category
    ON facts(fact_category);

CREATE INDEX IF NOT EXISTS idx_facts_active
    ON facts(is_active) WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_facts_confidence
    ON facts(confidence);

CREATE INDEX IF NOT EXISTS idx_facts_last_reinforced
    ON facts(last_reinforced);

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

-- ═══════════════════════════════════════════════════════════════════════════════
-- Bot Self-Learning System - Phase 5
-- Added: October 6, 2025
-- Bot learns about itself, tracks effectiveness, adapts persona dynamically
-- ═══════════════════════════════════════════════════════════════════════════════

-- Bot identity and version tracking (support for multiple bot instances)
CREATE TABLE IF NOT EXISTS bot_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,  -- Telegram bot user ID (can have multiple profiles per bot)
    bot_username TEXT,
    bot_name TEXT,
    chat_id INTEGER,  -- NULL for global facts, specific for per-chat learning
    profile_version INTEGER DEFAULT 1,
    total_interactions INTEGER DEFAULT 0,
    positive_interactions INTEGER DEFAULT 0,
    negative_interactions INTEGER DEFAULT 0,
    effectiveness_score REAL DEFAULT 0.5,  -- Running effectiveness metric
    last_self_reflection INTEGER,  -- Last Gemini-powered insight generation
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(bot_id, chat_id)  -- Separate profiles per chat + one global
);

-- Facts the bot learns about itself (parallel to user_facts)
CREATE TABLE IF NOT EXISTS bot_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    fact_category TEXT NOT NULL CHECK(fact_category IN (
        'communication_style',  -- Learned tone/approach preferences
        'knowledge_domain',     -- Topics bot knows well/poorly
        'tool_effectiveness',   -- Which tools work when
        'user_interaction',     -- Patterns in user responses
        'persona_adjustment',   -- Context-based personality tweaks
        'mistake_pattern',      -- Common errors to avoid
        'temporal_pattern',     -- Time-based behavior (e.g., evening vs morning)
        'performance_metric'    -- Response time, token usage patterns
    )),
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    evidence_count INTEGER DEFAULT 1,  -- How many times observed
    last_reinforced INTEGER,
    context_tags TEXT,  -- JSON array: ["formal", "technical", "evening", "weekend"]
    source_type TEXT CHECK(source_type IN (
        'user_feedback',      -- User explicitly told us
        'reaction_analysis',  -- Inferred from emoji/replies
        'success_metric',     -- Measured outcome (response time, etc.)
        'error_pattern',      -- Detected from failures
        'admin_input',        -- Admin commands
        'gemini_insight',     -- Generated from self-reflection
        'episode_learning'    -- Learned from episodic memory
    )),
    fact_embedding TEXT,  -- JSON array for semantic deduplication
    is_active INTEGER DEFAULT 1,
    decay_rate REAL DEFAULT 0.0,  -- For temporal decay (0.0 = no decay)
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE
);

-- Track specific interaction outcomes (similar to proactive_events but bot-focused)
CREATE TABLE IF NOT EXISTS bot_interaction_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    message_id INTEGER,  -- References messages table (bot's response)
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    interaction_type TEXT NOT NULL CHECK(interaction_type IN (
        'response',          -- Regular response to user
        'proactive',         -- Unsolicited contribution
        'tool_usage',        -- Used a tool
        'error_recovery',    -- Handled an error
        'clarification'      -- Asked for clarification
    )),
    outcome TEXT NOT NULL CHECK(outcome IN (
        'positive',          -- User engaged positively (thanks, emoji, follow-up)
        'neutral',           -- No reaction or neutral
        'negative',          -- User expressed frustration
        'corrected',         -- User corrected bot
        'ignored',           -- User didn't respond at all
        'praised'            -- Explicit praise
    )),
    sentiment_score REAL,  -- -1.0 to 1.0 from reaction analysis
    context_snapshot TEXT,  -- JSON with chat state, time of day, etc.
    response_text TEXT,     -- What bot said
    response_length INTEGER,  -- Character count
    response_time_ms INTEGER,  -- How long to generate
    token_count INTEGER,    -- Tokens used
    tools_used TEXT,        -- JSON array of tool names
    user_reaction TEXT,     -- What user said/did
    reaction_delay_seconds INTEGER,  -- Time until user reacted
    learned_from INTEGER DEFAULT 0,  -- Whether this updated bot_facts
    episode_id INTEGER,     -- Link to episode if part of one
    created_at INTEGER NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL,
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE SET NULL
);

-- Bot self-reflection insights (Gemini-generated periodic analysis)
CREATE TABLE IF NOT EXISTS bot_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    insight_type TEXT NOT NULL CHECK(insight_type IN (
        'effectiveness_trend',   -- Overall effectiveness analysis
        'communication_pattern', -- What works/doesn't work
        'knowledge_gap',         -- Topics bot struggles with
        'user_preference',       -- What users prefer from bot
        'temporal_insight',      -- Time-based patterns
        'improvement_suggestion' -- Self-improvement ideas
    )),
    insight_text TEXT NOT NULL,
    supporting_data TEXT,  -- JSON with stats/evidence
    confidence REAL DEFAULT 0.5,
    actionable INTEGER DEFAULT 0,  -- Whether this should trigger changes
    applied INTEGER DEFAULT 0,  -- Whether changes were applied
    created_at INTEGER NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE
);

-- Persona adaptation rules (dynamically generated from learning)
CREATE TABLE IF NOT EXISTS bot_persona_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    rule_name TEXT NOT NULL,
    rule_condition TEXT NOT NULL,  -- JSON: {"time_of_day": "evening", "chat_type": "technical"}
    persona_modification TEXT NOT NULL,  -- Text to append to system prompt
    priority INTEGER DEFAULT 50,  -- 0-100, higher = more important
    activation_count INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.5,
    is_active INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE
);

-- Performance metrics tracking
CREATE TABLE IF NOT EXISTS bot_performance_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    metric_type TEXT NOT NULL CHECK(metric_type IN (
        'response_time',
        'token_usage',
        'tool_success_rate',
        'error_rate',
        'user_satisfaction',
        'embedding_cache_hit'
    )),
    metric_value REAL NOT NULL,
    context_tags TEXT,  -- JSON array for grouping
    measured_at INTEGER NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE
);

-- Indexes for bot learning tables

CREATE INDEX IF NOT EXISTS idx_bot_profiles_bot_id ON bot_profiles(bot_id);
CREATE INDEX IF NOT EXISTS idx_bot_profiles_chat_id ON bot_profiles(chat_id);
CREATE INDEX IF NOT EXISTS idx_bot_profiles_effectiveness ON bot_profiles(effectiveness_score DESC);

CREATE INDEX IF NOT EXISTS idx_bot_facts_profile ON bot_facts(profile_id);
CREATE INDEX IF NOT EXISTS idx_bot_facts_category ON bot_facts(fact_category);
CREATE INDEX IF NOT EXISTS idx_bot_facts_active ON bot_facts(is_active);
CREATE INDEX IF NOT EXISTS idx_bot_facts_confidence ON bot_facts(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_bot_facts_key ON bot_facts(fact_key);
CREATE INDEX IF NOT EXISTS idx_bot_facts_updated ON bot_facts(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_bot_interaction_outcomes_profile ON bot_interaction_outcomes(profile_id);
CREATE INDEX IF NOT EXISTS idx_bot_interaction_outcomes_outcome ON bot_interaction_outcomes(outcome);
CREATE INDEX IF NOT EXISTS idx_bot_interaction_outcomes_chat ON bot_interaction_outcomes(chat_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_bot_interaction_outcomes_created ON bot_interaction_outcomes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bot_interaction_outcomes_episode ON bot_interaction_outcomes(episode_id);

CREATE INDEX IF NOT EXISTS idx_bot_insights_profile ON bot_insights(profile_id);
CREATE INDEX IF NOT EXISTS idx_bot_insights_type ON bot_insights(insight_type);
CREATE INDEX IF NOT EXISTS idx_bot_insights_actionable ON bot_insights(actionable) WHERE actionable = 1;
CREATE INDEX IF NOT EXISTS idx_bot_insights_created ON bot_insights(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bot_persona_rules_profile ON bot_persona_rules(profile_id);
CREATE INDEX IF NOT EXISTS idx_bot_persona_rules_active ON bot_persona_rules(is_active) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_bot_persona_rules_priority ON bot_persona_rules(priority DESC);

CREATE INDEX IF NOT EXISTS idx_bot_performance_metrics_profile ON bot_performance_metrics(profile_id);
CREATE INDEX IF NOT EXISTS idx_bot_performance_metrics_type ON bot_performance_metrics(metric_type);
CREATE INDEX IF NOT EXISTS idx_bot_performance_metrics_measured ON bot_performance_metrics(measured_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Custom System Prompts - Admin Configuration
-- Added: October 7, 2025
-- Allows admins to customize system prompts per chat or globally via bot commands
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS system_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,  -- Admin who created/modified this prompt
    chat_id INTEGER,  -- NULL for global/default, specific chat_id for per-chat override
    scope TEXT NOT NULL DEFAULT 'global' CHECK(scope IN ('global', 'chat', 'personal')),
    prompt_text TEXT NOT NULL,  -- The actual system prompt
    is_active INTEGER NOT NULL DEFAULT 1,  -- Can have multiple prompts, only one active per scope
    version INTEGER DEFAULT 1,  -- Track versions for rollback
    notes TEXT,  -- Admin notes about what changed or why
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    activated_at INTEGER  -- When this prompt was activated
);

-- Partial unique index: only one active prompt per scope per chat
CREATE UNIQUE INDEX IF NOT EXISTS idx_system_prompts_active_unique 
    ON system_prompts(chat_id, scope) WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_system_prompts_active ON system_prompts(is_active, scope, chat_id);
CREATE INDEX IF NOT EXISTS idx_system_prompts_admin ON system_prompts(admin_id);
CREATE INDEX IF NOT EXISTS idx_system_prompts_chat ON system_prompts(chat_id);
CREATE INDEX IF NOT EXISTS idx_system_prompts_created ON system_prompts(created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Chat Public Memory - Group-level facts and preferences
-- Added: October 8, 2025
-- Allows bot to remember chat-wide context (preferences, traditions, rules, culture)
-- ═══════════════════════════════════════════════════════════════════════════════

-- Chat profile metadata (one per chat)
CREATE TABLE IF NOT EXISTS chat_profiles (
    chat_id INTEGER PRIMARY KEY,
    chat_type TEXT CHECK(chat_type IN ('group', 'supergroup', 'channel')),
    chat_title TEXT,
    participant_count INTEGER DEFAULT 0,
    bot_joined_at INTEGER NOT NULL,
    last_active INTEGER NOT NULL,
    culture_summary TEXT,  -- Optional AI-generated summary
    profile_version INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- Chat-level facts (group preferences, traditions, norms)
CREATE TABLE IF NOT EXISTS chat_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    fact_category TEXT NOT NULL CHECK(fact_category IN (
        'preference',    -- "prefers dark humor", "likes technical discussions"
        'tradition',     -- "Friday recap", "Monday memes"
        'rule',          -- "no politics", "Ukrainian only"
        'norm',          -- "emoji reactions common", "voice messages rare"
        'topic',         -- "frequently discusses AI", "crypto enthusiasts"
        'culture',       -- "sarcastic", "supportive", "competitive"
        'event',         -- "monthly meetups", "annual party planning"
        'shared_knowledge'  -- "discussed movie X", "planning trip to Y"
    )),
    fact_key TEXT NOT NULL,      -- e.g., "humor_style", "weekly_tradition"
    fact_value TEXT NOT NULL,    -- e.g., "dark_sarcastic", "friday_recap"
    fact_description TEXT,       -- Human-readable: "Group prefers dark humor"
    confidence REAL DEFAULT 0.7,
    evidence_count INTEGER DEFAULT 1,  -- How many times reinforced
    first_observed INTEGER NOT NULL,
    last_reinforced INTEGER NOT NULL,
    participant_consensus REAL,  -- 0-1: what % of users agree
    is_active INTEGER DEFAULT 1,
    decay_rate REAL DEFAULT 0.0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (chat_id) REFERENCES chat_profiles(chat_id) ON DELETE CASCADE
);

-- Chat fact versions (track changes over time)
CREATE TABLE IF NOT EXISTS chat_fact_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER NOT NULL,
    previous_version_id INTEGER,
    version_number INTEGER NOT NULL,
    change_type TEXT CHECK(change_type IN (
        'creation', 'reinforcement', 'evolution', 'correction', 'deprecation'
    )),
    confidence_delta REAL,
    change_evidence TEXT,  -- What triggered the change
    created_at INTEGER NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES chat_facts(id) ON DELETE CASCADE,
    FOREIGN KEY (previous_version_id) REFERENCES chat_facts(id) ON DELETE SET NULL
);

-- Chat fact quality metrics (deduplication, conflicts)
CREATE TABLE IF NOT EXISTS chat_fact_quality_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    fact_id INTEGER NOT NULL,
    duplicate_of INTEGER,  -- References another chat_fact id
    conflict_with INTEGER,
    similarity_score REAL,
    resolution_method TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES chat_facts(id) ON DELETE CASCADE,
    FOREIGN KEY (chat_id) REFERENCES chat_profiles(chat_id) ON DELETE CASCADE
);

-- Indexes for chat public memory
CREATE INDEX IF NOT EXISTS idx_chat_profiles_type 
    ON chat_profiles(chat_type);
CREATE INDEX IF NOT EXISTS idx_chat_profiles_active 
    ON chat_profiles(last_active DESC);

CREATE INDEX IF NOT EXISTS idx_chat_facts_chat 
    ON chat_facts(chat_id, is_active);
CREATE INDEX IF NOT EXISTS idx_chat_facts_category 
    ON chat_facts(fact_category);
CREATE INDEX IF NOT EXISTS idx_chat_facts_confidence 
    ON chat_facts(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_chat_facts_reinforced 
    ON chat_facts(last_reinforced DESC);
CREATE INDEX IF NOT EXISTS idx_chat_facts_key 
    ON chat_facts(chat_id, fact_key);

CREATE INDEX IF NOT EXISTS idx_chat_fact_versions_fact 
    ON chat_fact_versions(fact_id, version_number);
CREATE INDEX IF NOT EXISTS idx_chat_fact_versions_previous 
    ON chat_fact_versions(previous_version_id);

CREATE INDEX IF NOT EXISTS idx_chat_fact_quality_chat 
    ON chat_fact_quality_metrics(chat_id);
CREATE INDEX IF NOT EXISTS idx_chat_fact_quality_fact 
    ON chat_fact_quality_metrics(fact_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Image Generation Quotas - Daily limits for image generation per user
-- Added: October 17, 2025
-- Tracks daily image generation usage to enforce rate limits
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS image_quotas (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    generation_date TEXT NOT NULL,  -- YYYY-MM-DD format
    images_generated INTEGER DEFAULT 0,
    last_generation_ts INTEGER,
    PRIMARY KEY (user_id, chat_id, generation_date)
);

CREATE INDEX IF NOT EXISTS idx_image_quotas_user_date
    ON image_quotas(user_id, generation_date);
CREATE INDEX IF NOT EXISTS idx_image_quotas_chat_date
    ON image_quotas(chat_id, generation_date);
CREATE INDEX IF NOT EXISTS idx_image_quotas_last_gen
    ON image_quotas(last_generation_ts);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Feature-Level Throttling and Adaptive Rate Limiting
-- Added: October 21, 2025
-- Comprehensive throttling system with per-feature limits and adaptive reputation
-- ═══════════════════════════════════════════════════════════════════════════════

-- Feature-specific rate limiting (weather, currency, images, polls, memory, etc.)
CREATE TABLE IF NOT EXISTS feature_rate_limits (
    user_id INTEGER NOT NULL,
    feature_name TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    last_request INTEGER NOT NULL,
    PRIMARY KEY (user_id, feature_name, window_start)
);

CREATE INDEX IF NOT EXISTS idx_feature_rate_limits_window
    ON feature_rate_limits(window_start);

CREATE INDEX IF NOT EXISTS idx_feature_rate_limits_user_feature
    ON feature_rate_limits(user_id, feature_name);

CREATE INDEX IF NOT EXISTS idx_feature_rate_limits_last_request
    ON feature_rate_limits(last_request);

-- Cooldown tracking for per-request cooldowns (e.g., image generation)
CREATE TABLE IF NOT EXISTS feature_cooldowns (
    user_id INTEGER NOT NULL,
    feature_name TEXT NOT NULL,
    last_used INTEGER NOT NULL,
    cooldown_seconds INTEGER NOT NULL,
    PRIMARY KEY (user_id, feature_name)
);

CREATE INDEX IF NOT EXISTS idx_feature_cooldowns_last_used
    ON feature_cooldowns(last_used);

-- User reputation and throttle adjustment
CREATE TABLE IF NOT EXISTS user_throttle_metrics (
    user_id INTEGER PRIMARY KEY,
    throttle_multiplier REAL DEFAULT 1.0,  -- 0.5-2.0 range (higher = more lenient)
    spam_score REAL DEFAULT 0.0,           -- 0.0-1.0 (higher = more spammy)
    total_requests INTEGER DEFAULT 0,
    throttled_requests INTEGER DEFAULT 0,
    burst_requests INTEGER DEFAULT 0,      -- Requests in short time spans
    avg_request_spacing_seconds REAL DEFAULT 0.0,
    last_reputation_update INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_throttle_metrics_multiplier
    ON user_throttle_metrics(throttle_multiplier);

CREATE INDEX IF NOT EXISTS idx_user_throttle_metrics_spam_score
    ON user_throttle_metrics(spam_score DESC);

-- Request history for pattern analysis
CREATE TABLE IF NOT EXISTS user_request_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    feature_name TEXT NOT NULL,
    requested_at INTEGER NOT NULL,
    was_throttled INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_request_history_user_time
    ON user_request_history(user_id, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_request_history_feature
    ON user_request_history(feature_name);

CREATE INDEX IF NOT EXISTS idx_user_request_history_throttled
    ON user_request_history(was_throttled) WHERE was_throttled = 1;

-- Cleanup trigger: auto-delete request history older than 7 days
CREATE TRIGGER IF NOT EXISTS cleanup_old_request_history
AFTER INSERT ON user_request_history
BEGIN
    DELETE FROM user_request_history
    WHERE requested_at < (strftime('%s', 'now') - 604800); -- 7 days in seconds
END;
