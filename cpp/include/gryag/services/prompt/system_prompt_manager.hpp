#pragma once

#include "gryag/infrastructure/sqlite.hpp"

#include <SQLiteCpp/Statement.h>

#include <chrono>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace gryag::services::prompt {

struct SystemPrompt {
    int id = 0;
    std::int64_t admin_id = 0;
    std::optional<std::int64_t> chat_id;
    std::string scope;
    std::string prompt_text;
    bool is_active = false;
    int version = 1;
    std::optional<std::string> notes;
    std::chrono::system_clock::time_point created_at;
    std::chrono::system_clock::time_point updated_at;
    std::optional<std::chrono::system_clock::time_point> activated_at;
};

class SystemPromptManager {
public:
    explicit SystemPromptManager(std::shared_ptr<infrastructure::SQLiteConnection> connection);

    std::optional<SystemPrompt> active_prompt(std::optional<std::int64_t> chat_id);

    SystemPrompt set_prompt(std::int64_t admin_id,
                             const std::string& prompt_text,
                             std::optional<std::int64_t> chat_id = std::nullopt,
                             const std::string& scope = "global",
                             std::optional<std::string> notes = std::nullopt);

    void deactivate_prompt(int prompt_id);
    void reset_chat_prompt(std::int64_t chat_id);
    std::vector<SystemPrompt> list_prompts(std::optional<std::int64_t> chat_id = std::nullopt,
                                           std::optional<std::string> scope = std::nullopt,
                                           std::size_t limit = 20);
    void purge_cache();

private:
    SystemPrompt map_row(const SQLite::Statement& stmt) const;
    void cache_prompt(std::optional<std::int64_t> chat_id, const std::optional<SystemPrompt>& prompt);
    std::optional<SystemPrompt> get_cached(std::optional<std::int64_t> chat_id);
    void invalidate_cache(std::optional<std::int64_t> chat_id);

    std::shared_ptr<infrastructure::SQLiteConnection> connection_;

    struct CacheEntry {
        std::optional<SystemPrompt> prompt;
        std::chrono::steady_clock::time_point stored_at;
    };
    std::map<std::optional<std::int64_t>, CacheEntry> cache_;
    std::chrono::seconds cache_ttl_{std::chrono::hours(1)};
    std::mutex cache_mutex_;
};

}  // namespace gryag::services::prompt

