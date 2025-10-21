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

-- Adaptive throttling: track user behavior and reputation
-- Add columns to existing user_profiles table for throttle multipliers
-- These will be added via ALTER TABLE if the table exists

-- Note: SQLite doesn't support IF NOT EXISTS for ALTER TABLE
-- This migration should check if columns exist before adding them
-- For safety, use application-level checks or manual migration

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
-- This keeps the table from growing indefinitely
CREATE TRIGGER IF NOT EXISTS cleanup_old_request_history
AFTER INSERT ON user_request_history
BEGIN
    DELETE FROM user_request_history
    WHERE requested_at < (strftime('%s', 'now') - 604800); -- 7 days in seconds
END;
