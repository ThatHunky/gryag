#pragma once

#include "gryag/core/settings.hpp"
#include "gryag/infrastructure/sqlite.hpp"
#include "gryag/telegram/client.hpp"

#include <chrono>
#include <memory>
#include <mutex>
#include <optional>
#include <unordered_set>

namespace gryag::services::background {

class DonationScheduler {
public:
    DonationScheduler(std::shared_ptr<infrastructure::SQLiteConnection> connection,
                      const core::Settings& settings);

    void tick(telegram::TelegramClient& client);

private:
    void ensure_table();
    void process_groups(telegram::TelegramClient& client, std::int64_t now_seconds);
    void process_privates(telegram::TelegramClient& client, std::int64_t now_seconds);
    bool should_send(std::int64_t chat_id,
                     std::int64_t interval_seconds,
                     std::int64_t now_seconds,
                     std::int64_t last_activity_ts);
    void record_send(std::int64_t chat_id, std::int64_t timestamp);

    std::shared_ptr<infrastructure::SQLiteConnection> connection_;
    const core::Settings& settings_;
    std::unordered_set<std::int64_t> ignored_chats_;
    std::chrono::steady_clock::time_point next_group_check_;
    std::chrono::steady_clock::time_point next_private_check_;
    const std::chrono::steady_clock::duration check_interval_ = std::chrono::minutes(15);
    std::once_flag table_flag_;
};

}  // namespace gryag::services::background

