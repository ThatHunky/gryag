-- ═══════════════════════════════════════════════════════════════════════════════
-- User Profile Embeddings
-- Added: 2025-01-XX
-- Purpose: Add profile_embedding column to user_profiles for semantic user search
-- ═══════════════════════════════════════════════════════════════════════════════

-- Check if column exists before adding (PostgreSQL)
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

