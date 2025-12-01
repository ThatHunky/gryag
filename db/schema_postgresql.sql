-- PostgreSQL 18 Schema for gryag bot
-- Converted from SQLite schema
-- Foreign keys enabled by default in PostgreSQL

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Messages table
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    thread_id BIGINT,
    user_id BIGINT,
    -- External IDs stored as text to avoid precision loss in JSON or clients
    external_message_id TEXT,
    external_user_id TEXT,
    reply_to_external_message_id TEXT,
    reply_to_external_user_id TEXT,
    sender_role TEXT CHECK(sender_role IN ('user', 'assistant', 'system', 'tool')),
    sender_name TEXT,
    sender_username TEXT,
    sender_is_bot INTEGER DEFAULT 0,
    role TEXT NOT NULL CHECK(role IN ('user', 'model', 'system')),
    text TEXT,
    media TEXT,
    embedding TEXT,
    ts BIGINT NOT NULL
);

-- Indexes for external ID lookups
CREATE INDEX IF NOT EXISTS idx_messages_chat_external_msg
    ON messages(chat_id, external_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat_external_user
    ON messages(chat_id, external_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat_reply_external_msg
    ON messages(chat_id, reply_to_external_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_chat_reply_external_user
    ON messages(chat_id, reply_to_external_user_id);

CREATE TABLE IF NOT EXISTS bans (
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    ts BIGINT NOT NULL,
    last_notice_time BIGINT,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS rate_limits (
    user_id BIGINT NOT NULL,
    window_start BIGINT NOT NULL,
    request_count INTEGER NOT NULL,
    last_seen BIGINT NOT NULL,
    PRIMARY KEY (user_id, window_start)
);

CREATE INDEX IF NOT EXISTS idx_rate_limits_window
    ON rate_limits(window_start);

CREATE TABLE IF NOT EXISTS polls (
    id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    thread_id BIGINT,
    creator_id BIGINT NOT NULL,
    question TEXT NOT NULL,
    options TEXT NOT NULL, -- JSON array of poll options
    poll_type TEXT NOT NULL CHECK(poll_type IN ('regular', 'multiple', 'anonymous')),
    created_at BIGINT NOT NULL,
    expires_at BIGINT,
    is_closed INTEGER NOT NULL DEFAULT 0,
    allow_multiple INTEGER NOT NULL DEFAULT 0,
    is_anonymous INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS poll_votes (
    id BIGSERIAL PRIMARY KEY,
    poll_id TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    option_index INTEGER NOT NULL,
    voted_at BIGINT NOT NULL,
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

-- User profiling tables
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    display_name TEXT,
    username TEXT,
    pronouns TEXT,
    membership_status TEXT DEFAULT 'unknown',
    first_seen BIGINT NOT NULL,
    last_seen BIGINT NOT NULL,
    last_active_thread BIGINT,
    interaction_count INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    summary TEXT,
    profile_version INTEGER DEFAULT 1,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (user_id, chat_id)
);

-- Simplified user memory storage
CREATE TABLE IF NOT EXISTS user_memories (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    memory_text TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    UNIQUE(user_id, chat_id, memory_text)
);

-- Trigger function to enforce memory limit
CREATE OR REPLACE FUNCTION enforce_user_memory_limit()
RETURNS TRIGGER AS $$
BEGIN
    IF (SELECT COUNT(*) FROM user_memories WHERE user_id = NEW.user_id AND chat_id = NEW.chat_id) >= 15 THEN
        RAISE EXCEPTION 'User has reached the maximum of 15 memories in this chat.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_user_memory_limit_trigger ON user_memories;
CREATE TRIGGER enforce_user_memory_limit_trigger
BEFORE INSERT ON user_memories
FOR EACH ROW
EXECUTE FUNCTION enforce_user_memory_limit();

CREATE INDEX IF NOT EXISTS idx_user_memories_user_chat
    ON user_memories(user_id, chat_id);

CREATE TABLE IF NOT EXISTS user_relationships (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    related_user_id BIGINT NOT NULL,
    relationship_type TEXT NOT NULL CHECK(relationship_type IN ('friend', 'colleague', 'family', 'adversary', 'mentioned', 'unknown')),
    relationship_label TEXT,
    strength REAL DEFAULT 0.5,
    interaction_count INTEGER DEFAULT 0,
    last_interaction BIGINT,
    sentiment TEXT DEFAULT 'neutral' CHECK(sentiment IN ('positive', 'negative', 'neutral', 'mixed')),
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    UNIQUE (user_id, chat_id, related_user_id),
    FOREIGN KEY (user_id, chat_id) REFERENCES user_profiles(user_id, chat_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_user
    ON user_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_chat
    ON user_profiles(chat_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_last_seen
    ON user_profiles(last_seen);
CREATE INDEX IF NOT EXISTS idx_user_relationships_user
    ON user_relationships(user_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_user_relationships_related
    ON user_relationships(related_user_id);
CREATE INDEX IF NOT EXISTS idx_user_relationships_type
    ON user_relationships(relationship_type);
CREATE INDEX IF NOT EXISTS idx_user_relationships_strength
    ON user_relationships(strength);

-- Continuous monitoring tables
CREATE TABLE IF NOT EXISTS message_metadata (
    message_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    thread_id BIGINT,
    classification TEXT NOT NULL CHECK(classification IN ('high', 'medium', 'low', 'noise')),
    classification_reason TEXT,
    classification_confidence REAL,
    features TEXT, -- JSON of classification features
    processed INTEGER DEFAULT 0,
    processing_timestamp BIGINT,
    created_at BIGINT NOT NULL,
    PRIMARY KEY (message_id, chat_id)
);

CREATE TABLE IF NOT EXISTS conversation_windows (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    thread_id BIGINT,
    first_message_id BIGINT NOT NULL,
    last_message_id BIGINT NOT NULL,
    message_count INTEGER DEFAULT 0,
    participant_count INTEGER DEFAULT 0,
    dominant_value TEXT CHECK(dominant_value IN ('high', 'medium', 'low', 'noise')),
    has_high_value INTEGER DEFAULT 0,
    first_timestamp BIGINT NOT NULL,
    last_timestamp BIGINT NOT NULL,
    closed_at BIGINT NOT NULL,
    closure_reason TEXT,
    processed INTEGER DEFAULT 0,
    facts_extracted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS proactive_events (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    thread_id BIGINT,
    window_id BIGINT,
    trigger_reason TEXT NOT NULL,
    trigger_confidence REAL NOT NULL,
    intent_classification TEXT,
    response_sent INTEGER DEFAULT 0,
    response_message_id BIGINT,
    user_reaction TEXT,
    reaction_timestamp BIGINT,
    created_at BIGINT NOT NULL,
    FOREIGN KEY (window_id) REFERENCES conversation_windows(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS system_health (
    id BIGSERIAL PRIMARY KEY,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_context TEXT,
    timestamp BIGINT NOT NULL
);

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
CREATE INDEX IF NOT EXISTS idx_proactive_events_chat
    ON proactive_events(chat_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_proactive_events_window
    ON proactive_events(window_id);
CREATE INDEX IF NOT EXISTS idx_proactive_events_created
    ON proactive_events(created_at);
CREATE INDEX IF NOT EXISTS idx_system_health_metric
    ON system_health(metric_name, timestamp);

-- Full-Text Search using PostgreSQL tsvector
ALTER TABLE messages ADD COLUMN IF NOT EXISTS text_search_vector tsvector;

CREATE INDEX IF NOT EXISTS idx_messages_text_search
    ON messages USING GIN(text_search_vector);

-- Trigger function to update text search vector
CREATE OR REPLACE FUNCTION messages_tsvector_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.text_search_vector := to_tsvector('english', COALESCE(NEW.text, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER messages_tsvector_update_trigger
BEFORE INSERT OR UPDATE ON messages
FOR EACH ROW
EXECUTE FUNCTION messages_tsvector_update();

-- Message importance tracking
CREATE TABLE IF NOT EXISTS message_importance (
    message_id BIGINT PRIMARY KEY,
    importance_score REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER DEFAULT 0,
    last_accessed BIGINT,
    retention_days INTEGER,
    consolidated INTEGER DEFAULT 0,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_message_importance_score 
    ON message_importance(importance_score DESC);
CREATE INDEX IF NOT EXISTS idx_message_importance_retention 
    ON message_importance(retention_days ASC);
CREATE INDEX IF NOT EXISTS idx_message_importance_consolidated
    ON message_importance(consolidated);

-- Episodic memory
CREATE TABLE IF NOT EXISTS episodes (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    thread_id BIGINT,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    summary_embedding TEXT,  -- JSON array of floats
    importance REAL DEFAULT 0.5,
    emotional_valence TEXT CHECK(emotional_valence IN ('positive', 'negative', 'neutral', 'mixed')),
    message_ids TEXT NOT NULL,  -- JSON array of message IDs
    participant_ids TEXT NOT NULL,  -- JSON array of user IDs
    tags TEXT,  -- JSON array of keywords/tags
    created_at BIGINT NOT NULL,
    last_accessed BIGINT,
    access_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_episodes_chat ON episodes(chat_id, importance DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_importance ON episodes(importance DESC);

CREATE TABLE IF NOT EXISTS episode_accesses (
    episode_id BIGINT NOT NULL,
    accessed_at BIGINT NOT NULL,
    access_type TEXT CHECK(access_type IN ('retrieval', 'reference', 'update')),
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_episode_accesses ON episode_accesses(episode_id, accessed_at DESC);

-- Additional indexes for performance
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts DESC);
CREATE INDEX IF NOT EXISTS idx_messages_user_ts ON messages(user_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
-- Note: No index on embedding column - embeddings are large JSON arrays
-- and cannot be indexed directly. Similarity search is done by loading
-- embeddings and comparing in memory, so an index wouldn't help anyway.

-- Unified Facts Table (for user and chat facts)
CREATE TABLE IF NOT EXISTS facts (
    id BIGSERIAL PRIMARY KEY,
    
    -- Entity identification
    entity_type TEXT NOT NULL CHECK(entity_type IN ('user', 'chat')),
    entity_id BIGINT NOT NULL,  -- user_id or chat_id
    chat_context BIGINT,  -- chat_id where this was learned (for user facts only)
    
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
    source_message_id BIGINT,
    
    -- Consensus (for chat facts)
    participant_consensus REAL,
    participant_ids TEXT,  -- JSON array
    
    -- Lifecycle
    first_observed BIGINT NOT NULL,
    last_reinforced BIGINT NOT NULL,
    is_active INTEGER DEFAULT 1,
    decay_rate REAL DEFAULT 0.0,
    
    -- Metadata
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    
    -- Embedding for semantic search
    embedding TEXT,
    
    -- Composite unique constraint
    UNIQUE(entity_type, entity_id, chat_context, fact_category, fact_key)
);

-- Indexes for facts table
CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_chat_context ON facts(chat_context) WHERE entity_type = 'user';
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(fact_category);
CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(is_active) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_facts_confidence ON facts(confidence);
CREATE INDEX IF NOT EXISTS idx_facts_last_reinforced ON facts(last_reinforced);

-- Bot Self-Learning System
CREATE TABLE IF NOT EXISTS bot_profiles (
    id BIGSERIAL PRIMARY KEY,
    bot_id BIGINT NOT NULL,
    bot_username TEXT,
    bot_name TEXT,
    chat_id BIGINT,
    profile_version INTEGER DEFAULT 1,
    total_interactions INTEGER DEFAULT 0,
    positive_interactions INTEGER DEFAULT 0,
    negative_interactions INTEGER DEFAULT 0,
    effectiveness_score REAL DEFAULT 0.5,
    last_self_reflection BIGINT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    UNIQUE(bot_id, chat_id)
);

CREATE TABLE IF NOT EXISTS bot_facts (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL,
    fact_category TEXT NOT NULL CHECK(fact_category IN (
        'communication_style', 'knowledge_domain', 'tool_effectiveness',
        'user_interaction', 'persona_adjustment', 'mistake_pattern',
        'temporal_pattern', 'performance_metric'
    )),
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    evidence_count INTEGER DEFAULT 1,
    last_reinforced BIGINT,
    context_tags TEXT,
    source_type TEXT CHECK(source_type IN (
        'user_feedback', 'reaction_analysis', 'success_metric',
        'error_pattern', 'admin_input', 'gemini_insight', 'episode_learning'
    )),
    fact_embedding TEXT,
    is_active INTEGER DEFAULT 1,
    decay_rate REAL DEFAULT 0.0,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot_interaction_outcomes (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL,
    message_id BIGINT,
    chat_id BIGINT NOT NULL,
    thread_id BIGINT,
    interaction_type TEXT NOT NULL CHECK(interaction_type IN (
        'response', 'proactive', 'tool_usage', 'error_recovery', 'clarification'
    )),
    outcome TEXT NOT NULL CHECK(outcome IN (
        'positive', 'neutral', 'negative', 'corrected', 'ignored', 'praised'
    )),
    sentiment_score REAL,
    context_snapshot TEXT,
    response_text TEXT,
    response_length INTEGER,
    response_time_ms INTEGER,
    token_count INTEGER,
    tools_used TEXT,
    user_reaction TEXT,
    reaction_delay_seconds INTEGER,
    learned_from INTEGER DEFAULT 0,
    episode_id BIGINT,
    created_at BIGINT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL,
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS bot_insights (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL,
    insight_type TEXT NOT NULL CHECK(insight_type IN (
        'effectiveness_trend', 'communication_pattern', 'knowledge_gap',
        'user_preference', 'temporal_insight', 'improvement_suggestion'
    )),
    insight_text TEXT NOT NULL,
    supporting_data TEXT,
    confidence REAL DEFAULT 0.5,
    actionable INTEGER DEFAULT 0,
    applied INTEGER DEFAULT 0,
    created_at BIGINT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot_persona_rules (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL,
    rule_name TEXT NOT NULL,
    rule_condition TEXT NOT NULL,
    persona_modification TEXT NOT NULL,
    priority INTEGER DEFAULT 50,
    activation_count INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.5,
    is_active INTEGER DEFAULT 1,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot_performance_metrics (
    id BIGSERIAL PRIMARY KEY,
    profile_id BIGINT NOT NULL,
    metric_type TEXT NOT NULL CHECK(metric_type IN (
        'response_time', 'token_usage', 'tool_success_rate',
        'error_rate', 'user_satisfaction', 'embedding_cache_hit'
    )),
    metric_value REAL NOT NULL,
    context_tags TEXT,
    measured_at BIGINT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES bot_profiles(id) ON DELETE CASCADE
);

-- Bot learning indexes
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

-- System Prompts
CREATE TABLE IF NOT EXISTS system_prompts (
    id BIGSERIAL PRIMARY KEY,
    admin_id BIGINT NOT NULL,
    chat_id BIGINT,
    scope TEXT NOT NULL DEFAULT 'global' CHECK(scope IN ('global', 'chat', 'personal')),
    prompt_text TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    version INTEGER DEFAULT 1,
    notes TEXT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    activated_at BIGINT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_prompts_active_unique 
    ON system_prompts(chat_id, scope) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_system_prompts_active ON system_prompts(is_active, scope, chat_id);
CREATE INDEX IF NOT EXISTS idx_system_prompts_admin ON system_prompts(admin_id);
CREATE INDEX IF NOT EXISTS idx_system_prompts_chat ON system_prompts(chat_id);
CREATE INDEX IF NOT EXISTS idx_system_prompts_created ON system_prompts(created_at DESC);

-- Chat Profiles
CREATE TABLE IF NOT EXISTS chat_profiles (
    chat_id BIGINT PRIMARY KEY,
    chat_type TEXT CHECK(chat_type IN ('group', 'supergroup', 'channel')),
    chat_title TEXT,
    participant_count INTEGER DEFAULT 0,
    bot_joined_at BIGINT NOT NULL,
    last_active BIGINT NOT NULL,
    culture_summary TEXT,
    profile_version INTEGER DEFAULT 1,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_profiles_type 
    ON chat_profiles(chat_type);
CREATE INDEX IF NOT EXISTS idx_chat_profiles_active 
    ON chat_profiles(last_active DESC);

-- Image Quotas
CREATE TABLE IF NOT EXISTS image_quotas (
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    generation_date TEXT NOT NULL,
    images_generated INTEGER DEFAULT 0,
    last_generation_ts BIGINT,
    PRIMARY KEY (user_id, chat_id, generation_date)
);

CREATE INDEX IF NOT EXISTS idx_image_quotas_user_date
    ON image_quotas(user_id, generation_date);
CREATE INDEX IF NOT EXISTS idx_image_quotas_chat_date
    ON image_quotas(chat_id, generation_date);
CREATE INDEX IF NOT EXISTS idx_image_quotas_last_gen
    ON image_quotas(last_generation_ts);

-- Feature Rate Limiting
CREATE TABLE IF NOT EXISTS feature_rate_limits (
    user_id BIGINT NOT NULL,
    feature_name TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    last_request BIGINT NOT NULL,
    PRIMARY KEY (user_id, feature_name, window_start)
);

CREATE INDEX IF NOT EXISTS idx_feature_rate_limits_window
    ON feature_rate_limits(window_start);
CREATE INDEX IF NOT EXISTS idx_feature_rate_limits_user_feature
    ON feature_rate_limits(user_id, feature_name);
CREATE INDEX IF NOT EXISTS idx_feature_rate_limits_last_request
    ON feature_rate_limits(last_request);

CREATE TABLE IF NOT EXISTS feature_cooldowns (
    user_id BIGINT NOT NULL,
    feature_name TEXT NOT NULL,
    last_used BIGINT NOT NULL,
    cooldown_seconds INTEGER NOT NULL,
    PRIMARY KEY (user_id, feature_name)
);

CREATE INDEX IF NOT EXISTS idx_feature_cooldowns_last_used
    ON feature_cooldowns(last_used);

CREATE TABLE IF NOT EXISTS user_throttle_metrics (
    user_id BIGINT PRIMARY KEY,
    throttle_multiplier REAL DEFAULT 1.0,
    spam_score REAL DEFAULT 0.0,
    total_requests INTEGER DEFAULT 0,
    throttled_requests INTEGER DEFAULT 0,
    burst_requests INTEGER DEFAULT 0,
    avg_request_spacing_seconds REAL DEFAULT 0.0,
    last_reputation_update BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_throttle_metrics_multiplier
    ON user_throttle_metrics(throttle_multiplier);
CREATE INDEX IF NOT EXISTS idx_user_throttle_metrics_spam_score
    ON user_throttle_metrics(spam_score DESC);

CREATE TABLE IF NOT EXISTS user_request_history (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    feature_name TEXT NOT NULL,
    requested_at BIGINT NOT NULL,
    was_throttled INTEGER NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_request_history_user_time
    ON user_request_history(user_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_request_history_feature
    ON user_request_history(feature_name);
CREATE INDEX IF NOT EXISTS idx_user_request_history_throttled
    ON user_request_history(was_throttled) WHERE was_throttled = 1;

-- Cleanup trigger for request history
CREATE OR REPLACE FUNCTION cleanup_old_request_history()
RETURNS TRIGGER AS $$
BEGIN
    DELETE FROM user_request_history
    WHERE requested_at < (EXTRACT(EPOCH FROM NOW())::BIGINT - 604800);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cleanup_old_request_history_trigger
AFTER INSERT ON user_request_history
FOR EACH ROW
EXECUTE FUNCTION cleanup_old_request_history();

-- Donation Scheduler
CREATE TABLE IF NOT EXISTS donation_sends (
    chat_id BIGINT PRIMARY KEY,
    last_send_ts BIGINT NOT NULL,
    send_count INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_donation_sends_last_send
    ON donation_sends(last_send_ts);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Checkers Game - User vs. user challenge-based gameplay
-- Added: Implementation date
-- Supports public challenges with accept/cancel flow and tracked board messages
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS checkers_games (
    id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    thread_id BIGINT,
    challenger_id BIGINT NOT NULL,
    opponent_id BIGINT,
    current_player BIGINT,
    game_state TEXT NOT NULL,  -- JSON board state (empty JSON while pending)
    game_status TEXT NOT NULL CHECK(game_status IN ('pending', 'active', 'finished', 'cancelled')),
    winner_id BIGINT,
    challenge_message_id BIGINT,
    board_message_id BIGINT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checkers_games_chat_thread
    ON checkers_games(chat_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_checkers_games_challenger
    ON checkers_games(challenger_id);
CREATE INDEX IF NOT EXISTS idx_checkers_games_opponent
    ON checkers_games(opponent_id);
CREATE INDEX IF NOT EXISTS idx_checkers_games_status
    ON checkers_games(game_status);

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

-- ═══════════════════════════════════════════════════════════════════════════════
-- User Profile Embeddings
-- Added: 2025-01-XX
-- Purpose: Add profile_embedding column to user_profiles for semantic user search
-- ═══════════════════════════════════════════════════════════════════════════════

-- Add profile_embedding column to user_profiles if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'user_profiles' AND column_name = 'profile_embedding'
    ) THEN
        ALTER TABLE user_profiles ADD COLUMN profile_embedding TEXT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_user_profiles_embedding
    ON user_profiles(profile_embedding) WHERE profile_embedding IS NOT NULL;

