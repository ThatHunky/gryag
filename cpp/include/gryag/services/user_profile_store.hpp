#pragma once

#include "gryag/infrastructure/sqlite.hpp"

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace gryag::services {

/**
 * User profile management system for learning about users over time.
 *
 * Features:
 * - Profile creation and management
 * - Fact extraction and storage
 * - Relationship tracking
 * - Profile summarization support
 * - Membership status tracking
 */
class UserProfileStore {
public:
    explicit UserProfileStore(std::shared_ptr<infrastructure::SQLiteConnection> connection);

    /**
     * User profile structure
     */
    struct Profile {
        std::int64_t user_id = 0;
        std::int64_t chat_id = 0;
        std::string display_name;
        std::string username;
        std::string first_name;
        std::string last_name;
        std::string pronouns;
        std::string summary;
        std::int64_t created_at = 0;
        std::int64_t last_seen = 0;
        std::int64_t updated_at = 0;
        std::int64_t summary_updated_at = 0;
        std::string membership_status = "unknown";  // "member", "left", "kicked", "banned", "unknown"
        int interaction_count = 0;
    };

    /**
     * User fact structure
     */
    struct Fact {
        int id = 0;
        std::int64_t user_id = 0;
        std::int64_t chat_id = 0;
        std::string fact_type;       // "personal", "preference", "trait", "skill", "opinion"
        std::string fact_key;         // Standardized key (e.g., "location", "profession")
        std::string fact_value;       // The actual fact
        double confidence = 0.0;      // 0.7-1.0
        std::string evidence;         // Quote supporting the fact
        std::int64_t extracted_at = 0;
        bool active = true;
    };

    /**
     * Get or create a user profile
     */
    Profile get_or_create_profile(
        std::int64_t user_id,
        std::int64_t chat_id,
        const std::string& display_name = "",
        const std::string& username = ""
    );

    /**
     * Get existing profile (returns nullopt if not found)
     */
    std::optional<Profile> get_profile(std::int64_t user_id, std::int64_t chat_id);

    /**
     * Update profile fields
     */
    void update_profile(
        std::int64_t user_id,
        std::int64_t chat_id,
        const std::string& field,
        const std::string& value
    );

    /**
     * Update profile summary
     */
    void update_summary(std::int64_t user_id, const std::string& summary);

    /**
     * Update pronouns
     */
    void update_pronouns(std::int64_t user_id, std::int64_t chat_id, const std::string& pronouns);

    /**
     * Update interaction count
     */
    void update_interaction_count(std::int64_t user_id, std::int64_t chat_id);

    /**
     * Update membership status
     */
    void update_membership_status(
        std::int64_t user_id,
        std::int64_t chat_id,
        const std::string& status
    );

    /**
     * List all users in a chat
     */
    std::vector<Profile> list_chat_users(
        std::int64_t chat_id,
        bool active_only = true,
        int limit = 100
    );

    /**
     * Add a fact about a user
     */
    int add_fact(
        std::int64_t user_id,
        std::int64_t chat_id,
        const std::string& fact_type,
        const std::string& fact_key,
        const std::string& fact_value,
        double confidence,
        const std::string& evidence = ""
    );

    /**
     * Get facts for a user
     */
    std::vector<Fact> get_facts(
        std::int64_t user_id,
        std::int64_t chat_id,
        bool active_only = true,
        double min_confidence = 0.7
    );

    /**
     * Deactivate a fact (soft delete)
     */
    void deactivate_fact(int fact_id);

    /**
     * Delete a fact permanently
     */
    bool delete_fact(int fact_id);

    /**
     * Get fact count for a user
     */
    int get_fact_count(std::int64_t user_id, std::int64_t chat_id);

    /**
     * Clear all facts for a user
     */
    int clear_user_facts(std::int64_t user_id, std::int64_t chat_id);

    /**
     * Delete profile and all associated data
     */
    void delete_profile(std::int64_t user_id, std::int64_t chat_id);

    /**
     * Prune old facts
     */
    int prune_old_facts(int retention_days);

    /**
     * Get profiles that need summarization
     */
    std::vector<std::int64_t> get_profiles_needing_summarization(int limit = 50);

private:
    std::shared_ptr<infrastructure::SQLiteConnection> connection_;

    // Helper methods
    Profile row_to_profile(SQLite::Statement& stmt);
    Fact row_to_fact(SQLite::Statement& stmt);
    std::int64_t get_current_timestamp();
};

}  // namespace gryag::services
