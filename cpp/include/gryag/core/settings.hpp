#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace gryag::core {

struct Settings {
    std::string telegram_token;
    std::string gemini_api_key;
    std::vector<std::string> gemini_api_keys;
    std::string gemini_model = "gemini-1.5-pro";
    std::string gemini_embed_model = "embedding-001";
    std::string db_path = "gryag_cpp.db";
    bool enable_multi_level_context = true;
    int context_token_budget = 8000;
    int immediate_context_size = 5;
    int recent_context_size = 30;
    int relevant_context_size = 10;
    bool enable_keyword_search = true;
    bool enable_hybrid_search = true;
    bool enable_temporal_boosting = true;
    int max_search_candidates = 500;
    double semantic_weight = 0.5;
    double keyword_weight = 0.3;
    double temporal_weight = 0.2;
    bool enable_image_generation = false;
    bool enable_web_search = false;
    bool enable_persona_templates = true;
    bool enable_chat_memory = true;
    bool enable_episodic_memory = true;
    double episode_min_importance = 0.6;
    int episode_min_messages = 5;
    int episode_detection_interval_seconds = 300;
    int episode_monitor_interval_seconds = 300;
    int episode_window_timeout = 1800;
    int episode_window_max_messages = 50;
    bool retention_enabled = true;
    std::int64_t retention_days = 30;
    std::int64_t retention_prune_interval_seconds = 3600;
    std::vector<std::int64_t> admin_user_ids;
    std::vector<std::int64_t> allowed_chat_ids;
    std::vector<std::int64_t> blocked_chat_ids;
    std::vector<std::string> trigger_patterns;
    std::string bot_username = "";  // Filled at runtime via getMe
    std::int64_t bot_id = 0;  // Filled at runtime via getMe
    std::string redis_url = "";
    bool use_redis = false;
    bool enable_bot_self_learning = false;
    bool auto_create_episodes = false;
    std::string persona_config_path = "";
    std::string response_templates_path = "";
    bool enable_chat_fact_extraction = false;
    std::string chat_fact_extraction_method = "gemini";
    std::string openweather_api_key = "";
    std::string openweather_base_url = "https://api.openweathermap.org/data/2.5";
    std::string exchange_rate_api_key = "";
    std::string exchange_rate_base_url = "https://v6.exchangerate-api.com";
    std::string image_generation_api_key = "";
    int image_generation_daily_limit = 3;
    int per_user_per_hour = 5;
    bool enable_tool_based_memory = true;
    bool enable_command_throttling = true;
    bool enable_feature_throttling = true;
    bool enable_adaptive_throttling = true;
    int command_cooldown_seconds = 300;
    std::vector<std::int64_t> donation_ignored_chat_ids;

    static Settings from_env();
    void validate() const;
};

std::vector<std::string> split_comma_list(const std::string& value);
std::vector<std::int64_t> parse_int_list(const std::string& value);

}  // namespace gryag::core
