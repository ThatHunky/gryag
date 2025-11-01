#pragma once

#include "gryag/infrastructure/sqlite.hpp"

#include <chrono>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace gryag::services::rate_limit {

/**
 * Feature-level rate limiting with adaptive throttling based on user reputation.
 *
 * Tracks per-feature usage quotas (e.g., weather API calls per hour, image generations per day).
 * Supports:
 * - Per-feature limits (different quotas for different tools)
 * - Adaptive throttling (adjust limits based on user behavior)
 * - Admin bypass (admins never throttled)
 * - Reputation scoring (good behavior gets higher limits)
 */
class FeatureRateLimiter {
public:
    explicit FeatureRateLimiter(std::shared_ptr<infrastructure::SQLiteConnection> connection);

    /**
     * Feature quota configuration
     */
    struct FeatureQuota {
        std::string feature_name;
        int max_requests_per_hour;
        int max_requests_per_day;
        bool admin_bypass = true;
        double reputation_multiplier_min = 0.5;   // Min reputation reduces quota
        double reputation_multiplier_max = 2.0;   // Max reputation increases quota
    };

    /**
     * Check if user can use a feature
     * @param user_id Telegram user ID
     * @param feature_name Feature to check (e.g., "weather", "image_generation")
     * @param admin_user_ids List of admin user IDs (admins always allowed)
     * @return true if allowed, false if throttled
     */
    bool allow_feature(std::int64_t user_id, const std::string& feature_name,
                       const std::vector<std::int64_t>& admin_user_ids = {});

    /**
     * Register feature with quota
     */
    void register_feature(const FeatureQuota& quota);

    /**
     * Record a feature usage (call this after successful feature use)
     */
    void record_usage(std::int64_t user_id, const std::string& feature_name);

    /**
     * Get current usage stats for a user
     */
    struct UsageStats {
        std::int64_t user_id;
        std::string feature_name;
        int used_this_hour;
        int used_this_day;
        int quota_hour;
        int quota_day;
        double user_reputation = 1.0;
    };
    std::optional<UsageStats> get_usage_stats(std::int64_t user_id, const std::string& feature_name);

    /**
     * Update user reputation (affects adaptive throttling)
     * Value: 0.0 (worst) to 2.0 (best), default 1.0
     */
    void update_user_reputation(std::int64_t user_id, double reputation);

    /**
     * Get user's current reputation multiplier
     */
    double get_reputation_multiplier(std::int64_t user_id);

    /**
     * Reset all quotas for a user (admin action)
     */
    void reset_user_quotas(std::int64_t user_id);

    /**
     * Reset all quotas for a feature (admin action)
     */
    void reset_feature_quotas(const std::string& feature_name);

    /**
     * List all registered features
     */
    std::vector<FeatureQuota> list_features() const;

    /**
     * Cleanup old records (call periodically)
     */
    void cleanup_old_records(int days_to_keep = 7);

private:
    struct FeatureEntry {
        FeatureQuota quota;
        std::chrono::system_clock::time_point last_updated;
    };

    std::shared_ptr<infrastructure::SQLiteConnection> connection_;
    std::unordered_map<std::string, FeatureEntry> features_;
    std::unordered_map<std::int64_t, double> user_reputation_;

    // Helper methods
    int get_current_hour_usage(std::int64_t user_id, const std::string& feature_name);
    int get_current_day_usage(std::int64_t user_id, const std::string& feature_name);
    void record_request_history(std::int64_t user_id, const std::string& feature_name);
    bool is_current_hour_window(std::int64_t timestamp);
    bool is_current_day_window(std::int64_t timestamp);
};

}  // namespace gryag::services::rate_limit
