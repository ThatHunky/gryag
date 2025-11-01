#include "gryag/services/background/donation_scheduler.hpp"

#include <SQLiteCpp/Statement.h>
#include <SQLiteCpp/Transaction.h>
#include <spdlog/spdlog.h>

namespace gryag::services::background {

namespace {

constexpr std::chrono::seconds kGroupInterval{std::chrono::hours(48)};
constexpr std::chrono::seconds kPrivateInterval{std::chrono::hours(24 * 7)};
constexpr std::chrono::seconds kActivityWindow{std::chrono::hours(24)};
constexpr std::chrono::steady_clock::duration kCheckInterval = std::chrono::minutes(30);

const char* kDonationMessage =
    "щоб гряг продовжував функціонувати треба оплачувати його комуналку (API)\n\n"
    "підтримати проєкт:\n\n"
    "🔗Посилання на банку\n"
    "https://send.monobank.ua/jar/77iG8mGBsH\n\n"
    "💳Номер картки банки\n"
    "4874 1000 2180 1892";

std::int64_t to_unix(const std::chrono::system_clock::time_point& tp) {
    return std::chrono::duration_cast<std::chrono::seconds>(tp.time_since_epoch()).count();
}

std::int64_t now_seconds() {
    return to_unix(std::chrono::system_clock::now());
}

}  // namespace

DonationScheduler::DonationScheduler(std::shared_ptr<infrastructure::SQLiteConnection> connection,
                                     const core::Settings& settings)
    : connection_(std::move(connection)),
      settings_(settings),
      ignored_chats_(settings.donation_ignored_chat_ids.begin(), settings.donation_ignored_chat_ids.end()),
      next_group_check_(std::chrono::steady_clock::now()),
      next_private_check_(std::chrono::steady_clock::now()) {}

void DonationScheduler::tick(telegram::TelegramClient& client) {
    if (!connection_) {
        return;
    }
    std::call_once(table_flag_, [this]() {
        ensure_table();
    });

    const auto now = std::chrono::steady_clock::now();
    const auto now_sec = now_seconds();

    if (now >= next_group_check_) {
        try {
            process_groups(client, now_sec);
        } catch (const std::exception& ex) {
            spdlog::error("DonationScheduler group run failed: {}", ex.what());
        }
        next_group_check_ = now + kCheckInterval;
    }

    if (now >= next_private_check_) {
        try {
            process_privates(client, now_sec);
        } catch (const std::exception& ex) {
            spdlog::error("DonationScheduler private run failed: {}", ex.what());
        }
        next_private_check_ = now + kCheckInterval;
    }
}

void DonationScheduler::ensure_table() {
    SQLite::Statement stmt(
        connection_->db(),
        "CREATE TABLE IF NOT EXISTS donation_sends ("
        "chat_id INTEGER PRIMARY KEY,"
        "last_send_ts INTEGER NOT NULL,"
        "send_count INTEGER DEFAULT 1"
        ")"
    );
    stmt.exec();
}

void DonationScheduler::process_groups(telegram::TelegramClient& client, std::int64_t now_seconds) {
    SQLite::Statement stmt(
        connection_->db(),
        "SELECT chat_id, MAX(ts) AS last_activity "
        "FROM messages WHERE chat_id < 0 GROUP BY chat_id"
    );

    while (stmt.executeStep()) {
        const auto chat_id = stmt.getColumn(0).getInt64();
        if (ignored_chats_.contains(chat_id)) {
            continue;
        }
        const auto last_activity = stmt.getColumn(1).getInt64();
        if (!should_send(chat_id, kGroupInterval.count(), now_seconds, last_activity)) {
            continue;
        }
        try {
            client.send_message(chat_id, kDonationMessage);
            record_send(chat_id, now_seconds);
        } catch (const std::exception& ex) {
            spdlog::warn("Failed to send donation reminder to {}: {}", chat_id, ex.what());
        }
    }
}

void DonationScheduler::process_privates(telegram::TelegramClient& client, std::int64_t now_seconds) {
    SQLite::Statement stmt(
        connection_->db(),
        "SELECT chat_id, MAX(ts) AS last_activity "
        "FROM messages WHERE chat_id > 0 GROUP BY chat_id"
    );

    while (stmt.executeStep()) {
        const auto chat_id = stmt.getColumn(0).getInt64();
        const auto last_activity = stmt.getColumn(1).getInt64();
        if (!should_send(chat_id, kPrivateInterval.count(), now_seconds, last_activity)) {
            continue;
        }
        try {
            client.send_message(chat_id, kDonationMessage);
            record_send(chat_id, now_seconds);
        } catch (const std::exception& ex) {
            spdlog::warn("Failed to send donation reminder to {}: {}", chat_id, ex.what());
        }
    }
}

bool DonationScheduler::should_send(std::int64_t chat_id,
                                    std::int64_t interval_seconds,
                                    std::int64_t now_seconds,
                                    std::int64_t last_activity_ts) {
    if (now_seconds - last_activity_ts > kActivityWindow.count()) {
        return false;
    }

    SQLite::Statement stmt(
        connection_->db(),
        "SELECT last_send_ts FROM donation_sends WHERE chat_id = ?"
    );
    stmt.bind(1, chat_id);
    if (!stmt.executeStep()) {
        return true;
    }
    const auto last_send = stmt.getColumn(0).getInt64();
    return (now_seconds - last_send) >= interval_seconds;
}

void DonationScheduler::record_send(std::int64_t chat_id, std::int64_t timestamp) {
    SQLite::Statement stmt(
        connection_->db(),
        "INSERT INTO donation_sends (chat_id, last_send_ts, send_count) "
        "VALUES (?, ?, 1) "
        "ON CONFLICT(chat_id) DO UPDATE SET "
        "last_send_ts=excluded.last_send_ts, "
        "send_count=donation_sends.send_count+1"
    );
    stmt.bind(1, chat_id);
    stmt.bind(2, timestamp);
    stmt.exec();
}

}  // namespace gryag::services::background
