#pragma once

#include "gryag/core/settings.hpp"
#include "gryag/infrastructure/sqlite.hpp"

#include <chrono>
#include <optional>
#include <string>
#include <vector>

namespace gryag::services {

enum class TurnSender {
    User,
    Assistant,
    System,
    Tool,
};

struct MessageRecord {
    std::int64_t id = 0;
    std::int64_t chat_id = 0;
    std::optional<std::int64_t> thread_id;
    std::int64_t user_id = 0;
    std::string role;
    std::string text;
    std::chrono::system_clock::time_point timestamp;
};

class ContextStore {
public:
    explicit ContextStore(std::shared_ptr<infrastructure::SQLiteConnection> connection);

    void init();
    std::int64_t insert_message(const MessageRecord& record);
    std::vector<MessageRecord> recent_messages(std::int64_t chat_id, std::size_t limit) const;
    void prune_expired(const core::Settings& settings);
    bool is_banned(std::int64_t chat_id, std::int64_t user_id);
    void ban_user(std::int64_t chat_id, std::int64_t user_id);
    void unban_user(std::int64_t chat_id, std::int64_t user_id);
    void reset_rate_limits(std::int64_t chat_id);

private:
    std::shared_ptr<infrastructure::SQLiteConnection> connection_;
};

std::string format_metadata(const MessageRecord& record);
std::string format_speaker_header(TurnSender sender, const std::string& speaker_name);

}  // namespace gryag::services
