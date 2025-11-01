#include "gryag/services/context_store.hpp"

#include <SQLiteCpp/Statement.h>
#include <spdlog/spdlog.h>
#include <spdlog/fmt/fmt.h>

#include <cstdint>

#include <filesystem>
#include <fstream>

namespace fs = std::filesystem;

namespace gryag::services {

namespace {

std::string read_schema_file() {
    // Build list of candidate paths to search
    std::vector<fs::path> candidates;

    // 1. Check environment variable first (allows explicit override)
    if (const char* env_path = std::getenv("GRYAG_SCHEMA_PATH")) {
        candidates.emplace_back(env_path);
    }

    // 2. Try relative paths from current working directory
    candidates.emplace_back("db/schema.sql");
    candidates.emplace_back("../db/schema.sql");
    candidates.emplace_back("../../db/schema.sql");

    // 3. Try common installation paths
    candidates.emplace_back("/usr/local/share/gryag/db/schema.sql");
    candidates.emplace_back("/usr/share/gryag/db/schema.sql");

    // 4. Try path relative to executable directory
    try {
        const auto exe_path = fs::read_symlink("/proc/self/exe").parent_path();
        candidates.emplace_back(exe_path / "db/schema.sql");
        candidates.emplace_back(exe_path / "../db/schema.sql");
        candidates.emplace_back(exe_path / "../../db/schema.sql");
    } catch (...) {
        // /proc/self/exe not available on all systems, ignore
    }

    // Try each candidate path
    for (const auto& candidate : candidates) {
        if (fs::exists(candidate)) {
            std::ifstream file(candidate);
            if (file.good()) {
                spdlog::info("Loading schema from {}", candidate.string());
                return std::string((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
            }
        }
    }

    // If we get here, schema file was not found
    spdlog::error("Failed to find db/schema.sql. Searched paths:");
    for (const auto& candidate : candidates) {
        spdlog::error("  - {}", candidate.string());
    }
    throw std::runtime_error(
        "Unable to locate db/schema.sql. "
        "Set GRYAG_SCHEMA_PATH environment variable to specify location, "
        "or run from the project root directory."
    );
}

TurnSender to_sender(const std::string& role) {
    if (role == "user") {
        return TurnSender::User;
    }
    if (role == "assistant" || role == "model") {
        return TurnSender::Assistant;
    }
    if (role == "tool") {
        return TurnSender::Tool;
    }
    return TurnSender::System;
}

}  // namespace

ContextStore::ContextStore(std::shared_ptr<infrastructure::SQLiteConnection> connection)
    : connection_(std::move(connection)) {}

void ContextStore::init() {
    const auto schema = read_schema_file();
    connection_->execute_script(schema);
}

std::int64_t ContextStore::insert_message(const MessageRecord& record) {
    SQLite::Statement insert(
        connection_->db(),
        "INSERT INTO messages (chat_id, thread_id, user_id, role, text, ts) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    );

    insert.bind(1, record.chat_id);
    if (record.thread_id) {
        insert.bind(2, *record.thread_id);
    } else {
        insert.bind(2);
    }
    insert.bind(3, record.user_id);
    insert.bind(4, record.role);
    insert.bind(5, record.text);
    const auto timestamp = std::chrono::duration_cast<std::chrono::seconds>(
        record.timestamp.time_since_epoch()
    ).count();
    insert.bind(6, static_cast<std::int64_t>(timestamp));

    insert.exec();
    return connection_->db().getLastInsertRowid();
}

std::vector<MessageRecord> ContextStore::recent_messages(std::int64_t chat_id, std::size_t limit) const {
    SQLite::Statement query(
        connection_->db(),
        "SELECT id, chat_id, thread_id, user_id, role, text, ts "
        "FROM messages WHERE chat_id = ? ORDER BY ts DESC LIMIT ?"
    );

    query.bind(1, chat_id);
    query.bind(2, static_cast<int>(limit));

    std::vector<MessageRecord> results;
    while (query.executeStep()) {
        MessageRecord record;
        record.id = query.getColumn(0).getInt64();
        record.chat_id = query.getColumn(1).getInt64();
        if (!query.isColumnNull(2)) {
            record.thread_id = query.getColumn(2).getInt64();
        }
        record.user_id = query.getColumn(3).getInt64();
        record.role = query.getColumn(4).getString();
        record.text = query.getColumn(5).getString();
        const auto ts = query.getColumn(6).getInt64();
        record.timestamp = std::chrono::system_clock::time_point{std::chrono::seconds{ts}};
        results.emplace_back(std::move(record));
    }

    // reverse to chronological order
    std::reverse(results.begin(), results.end());
    return results;
}

void ContextStore::prune_expired(const core::Settings& settings) {
    if (!settings.retention_enabled) {
        return;
    }

    const auto cutoff = std::chrono::system_clock::now() - std::chrono::hours(settings.retention_days * 24);
    const auto cutoff_seconds = std::chrono::duration_cast<std::chrono::seconds>(
        cutoff.time_since_epoch()
    ).count();

    SQLite::Statement pruner(
        connection_->db(),
        "DELETE FROM messages WHERE ts < ?"
    );
    pruner.bind(1, static_cast<std::int64_t>(cutoff_seconds));
    const int deleted = pruner.exec();
    spdlog::debug("Retention pruning removed {} rows", deleted);
}

std::string format_metadata(const MessageRecord& record) {
    return fmt::format("chat_id={}, user_id={}", record.chat_id, record.user_id);
}

std::string format_speaker_header(TurnSender sender, const std::string& speaker_name) {
    switch (sender) {
        case TurnSender::User:
            return speaker_name.empty() ? "Користувач:" : speaker_name + ":";
        case TurnSender::Assistant:
            return "Гряґ:";
        case TurnSender::System:
            return "Система:";
        case TurnSender::Tool:
            return "Інструмент:";
        default:
            return "Співрозмовник:";
    }
}

bool ContextStore::is_banned(std::int64_t chat_id, std::int64_t user_id) {
    SQLite::Statement stmt(
        connection_->db(),
        "SELECT 1 FROM bans WHERE chat_id = ? AND user_id = ?"
    );
    stmt.bind(1, chat_id);
    stmt.bind(2, user_id);
    return stmt.executeStep();
}

void ContextStore::ban_user(std::int64_t chat_id, std::int64_t user_id) {
    SQLite::Statement stmt(
        connection_->db(),
        "INSERT OR REPLACE INTO bans (chat_id, user_id, ts) VALUES (?, ?, strftime('%s','now'))"
    );
    stmt.bind(1, chat_id);
    stmt.bind(2, user_id);
    stmt.exec();
}

void ContextStore::unban_user(std::int64_t chat_id, std::int64_t user_id) {
    SQLite::Statement stmt(
        connection_->db(),
        "DELETE FROM bans WHERE chat_id = ? AND user_id = ?"
    );
    stmt.bind(1, chat_id);
    stmt.bind(2, user_id);
    stmt.exec();
}

void ContextStore::reset_rate_limits(std::int64_t chat_id) {
    SQLite::Statement stmt(
        connection_->db(),
        "DELETE FROM rate_limits WHERE user_id IN (SELECT DISTINCT user_id FROM messages WHERE chat_id = ?)"
    );
    stmt.bind(1, chat_id);
    stmt.exec();
}

}  // namespace gryag::services
