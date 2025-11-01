#include "gryag/services/rate_limit/feature_rate_limiter.hpp"

#include <SQLiteCpp/Statement.h>
#include <SQLiteCpp/Transaction.h>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <ctime>

namespace gryag::services::rate_limit {

namespace {

constexpr int kSecondsPerHour = 3600;
constexpr int kSecondsPerDay = 86400;

std::int64_t current_unix_time() {
    return std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
}

std::int64_t hour_window_start(std::int64_t timestamp) {
    return (timestamp / kSecondsPerHour) * kSecondsPerHour;
}

std::int64_t day_window_start(std::int64_t timestamp) {
    return (timestamp / kSecondsPerDay) * kSecondsPerDay;
}

}  // namespace

FeatureRateLimiter::FeatureRateLimiter(std::shared_ptr<infrastructure::SQLiteConnection> connection)
    : connection_(std::move(connection)) {
    // Load existing feature configurations from database if any
    try {
        // Initialize in-memory feature registry with defaults
        register_feature(FeatureQuota{"weather", 5, 20, true, 0.5, 2.0});
        register_feature(FeatureQuota{"web_search", 10, 50, true, 0.5, 2.0});
        register_feature(FeatureQuota{"image_generation", 3, 10, true, 0.5, 2.0});
        register_feature(FeatureQuota{"polls", 5, 20, true, 0.5, 2.0});
        register_feature(FeatureQuota{"memory", 20, 100, true, 0.5, 2.0});
        register_feature(FeatureQuota{"currency", 10, 50, true, 0.5, 2.0});
        register_feature(FeatureQuota{"calculator", 50, 200, true, 0.5, 2.0});
    } catch (const std::exception& ex) {
        spdlog::warn("Failed to initialize feature quotas: {}", ex.what());
    }
}

bool FeatureRateLimiter::allow_feature(std::int64_t user_id,
                                       const std::string& feature_name,
                                       const std::vector<std::int64_t>& admin_user_ids) {
    // Admin bypass
    auto is_admin = std::find(admin_user_ids.begin(), admin_user_ids.end(), user_id) !=
                    admin_user_ids.end();
    if (is_admin) {
        return true;
    }

    // Check if feature exists
    auto feature_it = features_.find(feature_name);
    if (feature_it == features_.end()) {
        spdlog::warn("Feature '{}' not registered in rate limiter", feature_name);
        return true;  // Unknown features always allowed
    }

    const auto& quota = feature_it->second.quota;

    try {
        // Get current usage
        int hourly_usage = get_current_hour_usage(user_id, feature_name);
        int daily_usage = get_current_day_usage(user_id, feature_name);

        // Apply reputation multiplier to limits
        double reputation = get_reputation_multiplier(user_id);
        int adjusted_hour_limit = static_cast<int>(quota.max_requests_per_hour * reputation);
        int adjusted_day_limit = static_cast<int>(quota.max_requests_per_day * reputation);

        // Check limits
        if (hourly_usage >= adjusted_hour_limit) {
            spdlog::debug("User {} throttled on feature '{}': hourly limit reached ({}/{})",
                          user_id, feature_name, hourly_usage, adjusted_hour_limit);
            return false;
        }

        if (daily_usage >= adjusted_day_limit) {
            spdlog::debug("User {} throttled on feature '{}': daily limit reached ({}/{})",
                          user_id, feature_name, daily_usage, adjusted_day_limit);
            return false;
        }

        return true;
    } catch (const std::exception& ex) {
        spdlog::error("Error checking feature rate limit for user {} on '{}': {}",
                      user_id, feature_name, ex.what());
        return true;  // Fail open on error
    }
}

void FeatureRateLimiter::register_feature(const FeatureQuota& quota) {
    features_[quota.feature_name] = FeatureEntry{
        .quota = quota,
        .last_updated = std::chrono::system_clock::now()
    };
    spdlog::info("Registered feature quota '{}': {}/hour, {}/day",
                 quota.feature_name, quota.max_requests_per_hour, quota.max_requests_per_day);
}

void FeatureRateLimiter::record_usage(std::int64_t user_id, const std::string& feature_name) {
    try {
        record_request_history(user_id, feature_name);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to record usage for user {} on feature '{}': {}",
                      user_id, feature_name, ex.what());
    }
}

std::optional<FeatureRateLimiter::UsageStats> FeatureRateLimiter::get_usage_stats(
    std::int64_t user_id, const std::string& feature_name) {
    auto feature_it = features_.find(feature_name);
    if (feature_it == features_.end()) {
        return std::nullopt;
    }

    try {
        UsageStats stats;
        stats.user_id = user_id;
        stats.feature_name = feature_name;
        stats.used_this_hour = get_current_hour_usage(user_id, feature_name);
        stats.used_this_day = get_current_day_usage(user_id, feature_name);
        stats.user_reputation = get_reputation_multiplier(user_id);

        const auto& quota = feature_it->second.quota;
        stats.quota_hour = static_cast<int>(quota.max_requests_per_hour * stats.user_reputation);
        stats.quota_day = static_cast<int>(quota.max_requests_per_day * stats.user_reputation);

        return stats;
    } catch (const std::exception& ex) {
        spdlog::error("Failed to get usage stats: {}", ex.what());
        return std::nullopt;
    }
}

void FeatureRateLimiter::update_user_reputation(std::int64_t user_id, double reputation) {
    // Clamp reputation between 0.0 and 2.0
    reputation = std::max(0.0, std::min(2.0, reputation));
    user_reputation_[user_id] = reputation;
    spdlog::debug("Updated user {} reputation to {}", user_id, reputation);
}

double FeatureRateLimiter::get_reputation_multiplier(std::int64_t user_id) {
    auto it = user_reputation_.find(user_id);
    if (it != user_reputation_.end()) {
        return it->second;
    }
    return 1.0;  // Default to neutral reputation
}

void FeatureRateLimiter::reset_user_quotas(std::int64_t user_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "DELETE FROM user_request_history WHERE user_id = ?"
        );
        stmt.bind(1, user_id);
        stmt.exec();
        spdlog::info("Reset all quotas for user {}", user_id);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to reset user quotas: {}", ex.what());
    }
}

void FeatureRateLimiter::reset_feature_quotas(const std::string& feature_name) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "DELETE FROM user_request_history WHERE feature_name = ?"
        );
        stmt.bind(1, feature_name);
        stmt.exec();
        spdlog::info("Reset all quotas for feature '{}'", feature_name);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to reset feature quotas: {}", ex.what());
    }
}

std::vector<FeatureRateLimiter::FeatureQuota> FeatureRateLimiter::list_features() const {
    std::vector<FeatureQuota> result;
    for (const auto& [name, entry] : features_) {
        result.push_back(entry.quota);
    }
    return result;
}

void FeatureRateLimiter::cleanup_old_records(int days_to_keep) {
    try {
        const auto cutoff_timestamp = current_unix_time() - (days_to_keep * kSecondsPerDay);
        SQLite::Statement stmt(
            connection_->db(),
            "DELETE FROM user_request_history WHERE created_at < ?"
        );
        stmt.bind(1, cutoff_timestamp);
        stmt.exec();
        spdlog::info("Cleaned up user request history older than {} days", days_to_keep);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to cleanup old records: {}", ex.what());
    }
}

int FeatureRateLimiter::get_current_hour_usage(std::int64_t user_id,
                                               const std::string& feature_name) {
    const auto now = current_unix_time();
    const auto hour_start = hour_window_start(now);

    SQLite::Statement stmt(
        connection_->db(),
        "SELECT COUNT(*) FROM user_request_history "
        "WHERE user_id = ? AND feature_name = ? AND requested_at >= ? AND requested_at < ?"
    );
    stmt.bind(1, user_id);
    stmt.bind(2, feature_name);
    stmt.bind(3, hour_start);
    stmt.bind(4, hour_start + kSecondsPerHour);

    if (stmt.executeStep()) {
        return stmt.getColumn(0).getInt();
    }
    return 0;
}

int FeatureRateLimiter::get_current_day_usage(std::int64_t user_id,
                                              const std::string& feature_name) {
    const auto now = current_unix_time();
    const auto day_start = day_window_start(now);

    SQLite::Statement stmt(
        connection_->db(),
        "SELECT COUNT(*) FROM user_request_history "
        "WHERE user_id = ? AND feature_name = ? AND requested_at >= ? AND requested_at < ?"
    );
    stmt.bind(1, user_id);
    stmt.bind(2, feature_name);
    stmt.bind(3, day_start);
    stmt.bind(4, day_start + kSecondsPerDay);

    if (stmt.executeStep()) {
        return stmt.getColumn(0).getInt();
    }
    return 0;
}

void FeatureRateLimiter::record_request_history(std::int64_t user_id,
                                                const std::string& feature_name) {
    const auto now = current_unix_time();
    SQLite::Statement stmt(
        connection_->db(),
        "INSERT INTO user_request_history (user_id, feature_name, requested_at, was_throttled, created_at) "
        "VALUES (?, ?, ?, 0, ?)"
    );
    stmt.bind(1, user_id);
    stmt.bind(2, feature_name);
    stmt.bind(3, now);
    stmt.bind(4, now);
    stmt.exec();
}

bool FeatureRateLimiter::is_current_hour_window(std::int64_t timestamp) {
    const auto now = current_unix_time();
    return hour_window_start(timestamp) == hour_window_start(now);
}

bool FeatureRateLimiter::is_current_day_window(std::int64_t timestamp) {
    const auto now = current_unix_time();
    return day_window_start(timestamp) == day_window_start(now);
}

}  // namespace gryag::services::rate_limit
