#include "gryag/core/settings.hpp"

#include <algorithm>
#include <cstdlib>
#include <sstream>
#include <stdexcept>

namespace {

std::optional<std::string> get_env(const char* name) {
    const char* value = std::getenv(name);
    if (value == nullptr) {
        return std::nullopt;
    }
    return std::string{value};
}

bool parse_bool(const std::string& value) {
    std::string lower = value;
    std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return lower == "1" || lower == "true" || lower == "yes" || lower == "y";
}

std::int64_t parse_int64(const std::string& value, std::int64_t fallback) {
    if (value.empty()) {
        return fallback;
    }
    try {
        return std::stoll(value);
    } catch (...) {
        return fallback;
    }
}

double parse_double(const std::string& value, double fallback) {
    if (value.empty()) {
        return fallback;
    }
    try {
        return std::stod(value);
    } catch (...) {
        return fallback;
    }
}

}  // namespace

namespace gryag::core {

Settings Settings::from_env() {
    Settings settings;

    if (auto token = get_env("TELEGRAM_TOKEN")) {
        settings.telegram_token = *token;
    }

    if (auto key = get_env("GEMINI_API_KEY")) {
        settings.gemini_api_key = *key;
    }

    if (auto keys = get_env("GEMINI_API_KEYS")) {
        settings.gemini_api_keys = split_comma_list(*keys);
    }

    if (auto model = get_env("GEMINI_MODEL")) {
        settings.gemini_model = *model;
    }

    if (auto embed_model = get_env("GEMINI_EMBED_MODEL")) {
        settings.gemini_embed_model = *embed_model;
    }

    if (auto db = get_env("DB_PATH")) {
        settings.db_path = *db;
    }

    if (auto mlc = get_env("ENABLE_MULTI_LEVEL_CONTEXT")) {
        settings.enable_multi_level_context = parse_bool(*mlc);
    }
    if (auto token_budget = get_env("CONTEXT_TOKEN_BUDGET")) {
        settings.context_token_budget = static_cast<int>(parse_int64(*token_budget, settings.context_token_budget));
    }
    if (auto immediate = get_env("IMMEDIATE_CONTEXT_SIZE")) {
        settings.immediate_context_size = static_cast<int>(parse_int64(*immediate, settings.immediate_context_size));
    }
    if (auto recent = get_env("RECENT_CONTEXT_SIZE")) {
        settings.recent_context_size = static_cast<int>(parse_int64(*recent, settings.recent_context_size));
    }
    if (auto relevant = get_env("RELEVANT_CONTEXT_SIZE")) {
        settings.relevant_context_size = static_cast<int>(parse_int64(*relevant, settings.relevant_context_size));
    }
    if (auto hybrid = get_env("ENABLE_HYBRID_SEARCH")) {
        settings.enable_hybrid_search = parse_bool(*hybrid);
    }
    if (auto keyword = get_env("ENABLE_KEYWORD_SEARCH")) {
        settings.enable_keyword_search = parse_bool(*keyword);
    }
    if (auto temporal = get_env("ENABLE_TEMPORAL_BOOSTING")) {
        settings.enable_temporal_boosting = parse_bool(*temporal);
    }
    if (auto max_candidates = get_env("MAX_SEARCH_CANDIDATES")) {
        settings.max_search_candidates = static_cast<int>(parse_int64(*max_candidates, settings.max_search_candidates));
    }
    if (auto semantic_weight = get_env("SEMANTIC_WEIGHT")) {
        settings.semantic_weight = parse_double(*semantic_weight, settings.semantic_weight);
    }
    if (auto keyword_weight = get_env("KEYWORD_WEIGHT")) {
        settings.keyword_weight = parse_double(*keyword_weight, settings.keyword_weight);
    }
    if (auto temporal_weight = get_env("TEMPORAL_WEIGHT")) {
        settings.temporal_weight = parse_double(*temporal_weight, settings.temporal_weight);
    }

    if (auto image = get_env("ENABLE_IMAGE_GENERATION")) {
        settings.enable_image_generation = parse_bool(*image);
    }

    if (auto web = get_env("ENABLE_WEB_SEARCH")) {
        settings.enable_web_search = parse_bool(*web);
    }

    if (auto persona = get_env("ENABLE_PERSONA_TEMPLATES")) {
        settings.enable_persona_templates = parse_bool(*persona);
    }

    if (auto chat_memory = get_env("ENABLE_CHAT_MEMORY")) {
        settings.enable_chat_memory = parse_bool(*chat_memory);
    }
    if (auto episodic = get_env("ENABLE_EPISODIC_MEMORY")) {
        settings.enable_episodic_memory = parse_bool(*episodic);
    }
    if (auto importance = get_env("EPISODE_MIN_IMPORTANCE")) {
        settings.episode_min_importance = parse_double(*importance, settings.episode_min_importance);
    }
    if (auto min_messages = get_env("EPISODE_MIN_MESSAGES")) {
        settings.episode_min_messages = static_cast<int>(parse_int64(*min_messages, settings.episode_min_messages));
    }
    if (auto detection_interval = get_env("EPISODE_DETECTION_INTERVAL")) {
        settings.episode_detection_interval_seconds =
            static_cast<int>(parse_int64(*detection_interval, settings.episode_detection_interval_seconds));
    }
    if (auto monitor_interval = get_env("EPISODE_MONITOR_INTERVAL")) {
        settings.episode_monitor_interval_seconds =
            static_cast<int>(parse_int64(*monitor_interval, settings.episode_monitor_interval_seconds));
    }
    if (auto window_timeout = get_env("EPISODE_WINDOW_TIMEOUT")) {
        settings.episode_window_timeout =
            static_cast<int>(parse_int64(*window_timeout, settings.episode_window_timeout));
    }
    if (auto window_max = get_env("EPISODE_WINDOW_MAX_MESSAGES")) {
        settings.episode_window_max_messages =
            static_cast<int>(parse_int64(*window_max, settings.episode_window_max_messages));
    }

    if (auto retention = get_env("RETENTION_ENABLED")) {
        settings.retention_enabled = parse_bool(*retention);
    }

    if (auto retention_days = get_env("RETENTION_DAYS")) {
        settings.retention_days = parse_int64(*retention_days, settings.retention_days);
    }

    if (auto prune_interval = get_env("RETENTION_PRUNE_INTERVAL_SECONDS")) {
        settings.retention_prune_interval_seconds =
            parse_int64(*prune_interval, settings.retention_prune_interval_seconds);
    }

    if (auto admin_ids = get_env("ADMIN_USER_IDS")) {
        settings.admin_user_ids = parse_int_list(*admin_ids);
    }

    if (auto allowed_ids = get_env("ALLOWED_CHAT_IDS")) {
        settings.allowed_chat_ids = parse_int_list(*allowed_ids);
    }

    if (auto blocked_ids = get_env("BLOCKED_CHAT_IDS")) {
        settings.blocked_chat_ids = parse_int_list(*blocked_ids);
    }

    if (auto patterns = get_env("BOT_TRIGGER_PATTERNS")) {
        settings.trigger_patterns = split_comma_list(*patterns);
    }

    if (auto redis = get_env("REDIS_URL")) {
        settings.redis_url = *redis;
        settings.use_redis = !settings.redis_url.empty();
    }

    if (auto redis_flag = get_env("USE_REDIS")) {
        settings.use_redis = parse_bool(*redis_flag);
    }

    if (auto self_learning = get_env("ENABLE_BOT_SELF_LEARNING")) {
        settings.enable_bot_self_learning = parse_bool(*self_learning);
    }

    if (auto episodes = get_env("AUTO_CREATE_EPISODES")) {
        settings.auto_create_episodes = parse_bool(*episodes);
    }

    if (auto persona_config = get_env("PERSONA_CONFIG")) {
        settings.persona_config_path = *persona_config;
    }

    if (auto response_templates = get_env("RESPONSE_TEMPLATES")) {
        settings.response_templates_path = *response_templates;
    }

    if (auto extracted = get_env("ENABLE_CHAT_FACT_EXTRACTION")) {
        settings.enable_chat_fact_extraction = parse_bool(*extracted);
    }
    if (auto extraction_method = get_env("CHAT_FACT_EXTRACTION_METHOD")) {
        settings.chat_fact_extraction_method = *extraction_method;
    }

    if (auto weather_key = get_env("OPENWEATHER_API_KEY")) {
        settings.openweather_api_key = *weather_key;
    }
    if (auto weather_url = get_env("OPENWEATHER_BASE_URL")) {
        settings.openweather_base_url = *weather_url;
    }
    if (auto exchange_key = get_env("EXCHANGE_RATE_API_KEY")) {
        settings.exchange_rate_api_key = *exchange_key;
    }
    if (auto exchange_url = get_env("EXCHANGE_RATE_BASE_URL")) {
        settings.exchange_rate_base_url = *exchange_url;
    }
    if (auto image_key = get_env("IMAGE_GENERATION_API_KEY")) {
        settings.image_generation_api_key = *image_key;
    }
    if (auto image_limit = get_env("IMAGE_GENERATION_DAILY_LIMIT")) {
        settings.image_generation_daily_limit =
            static_cast<int>(parse_int64(*image_limit, settings.image_generation_daily_limit));
    }
    if (auto per_user = get_env("PER_USER_PER_HOUR")) {
        settings.per_user_per_hour = static_cast<int>(parse_int64(*per_user, settings.per_user_per_hour));
    }
    if (auto tool_memory = get_env("ENABLE_TOOL_BASED_MEMORY")) {
        settings.enable_tool_based_memory = parse_bool(*tool_memory);
    }
    if (auto command_throttle = get_env("ENABLE_COMMAND_THROTTLING")) {
        settings.enable_command_throttling = parse_bool(*command_throttle);
    }
    if (auto feature_throttle = get_env("ENABLE_FEATURE_THROTTLING")) {
        settings.enable_feature_throttling = parse_bool(*feature_throttle);
    }
    if (auto adaptive_throttle = get_env("ENABLE_ADAPTIVE_THROTTLING")) {
        settings.enable_adaptive_throttling = parse_bool(*adaptive_throttle);
    }
    if (auto cooldown = get_env("COMMAND_COOLDOWN_SECONDS")) {
        settings.command_cooldown_seconds = static_cast<int>(parse_int64(*cooldown, settings.command_cooldown_seconds));
    }
    if (auto donation_ignore = get_env("DONATION_IGNORED_CHAT_IDS")) {
        settings.donation_ignored_chat_ids = parse_int_list(*donation_ignore);
    }

    return settings;
}

void Settings::validate() const {
    if (telegram_token.empty()) {
        throw std::runtime_error("TELEGRAM_TOKEN must be set");
    }
    if (gemini_api_key.empty() && gemini_api_keys.empty()) {
        throw std::runtime_error("Provide GEMINI_API_KEY or GEMINI_API_KEYS");
    }
    if (db_path.empty()) {
        throw std::runtime_error("DB_PATH must not be empty");
    }
}

std::vector<std::string> split_comma_list(const std::string& value) {
    std::vector<std::string> result;
    std::stringstream ss(value);
    std::string item;
    while (std::getline(ss, item, ',')) {
        if (!item.empty()) {
            // trim whitespace
            const auto start = item.find_first_not_of(" \t\n\r");
            const auto end = item.find_last_not_of(" \t\n\r");
            if (start != std::string::npos && end != std::string::npos) {
                result.emplace_back(item.substr(start, end - start + 1));
            }
        }
    }
    return result;
}

std::vector<std::int64_t> parse_int_list(const std::string& value) {
    std::vector<std::int64_t> result;
    for (const auto& token : split_comma_list(value)) {
        try {
            result.push_back(std::stoll(token));
        } catch (...) {
            // ignore malformed entries; validation can warn later
        }
    }
    return result;
}

}  // namespace gryag::core
