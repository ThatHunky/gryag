#include "gryag/services/prompt/system_prompt_manager.hpp"

#include <SQLiteCpp/Statement.h>
#include <SQLiteCpp/Transaction.h>
#include <spdlog/spdlog.h>

#include <stdexcept>

namespace gryag::services::prompt {

namespace {

constexpr const char* kGlobalScope = "global";
constexpr const char* kChatScope = "chat";
constexpr const char* kPersonalScope = "personal";

std::chrono::system_clock::time_point from_unix(std::int64_t timestamp) {
    return std::chrono::system_clock::time_point{std::chrono::seconds{timestamp}};
}

std::int64_t current_unix_seconds() {
    const auto now = std::chrono::system_clock::now();
    return std::chrono::duration_cast<std::chrono::seconds>(now.time_since_epoch()).count();
}

bool is_valid_scope(const std::string& scope) {
    return scope == kGlobalScope || scope == kChatScope || scope == kPersonalScope;
}

std::optional<std::int64_t> read_optional_int64(const SQLite::Statement& stmt, int column) {
    if (stmt.isColumnNull(column)) {
        return std::nullopt;
    }
    return stmt.getColumn(column).getInt64();
}

std::optional<std::string> read_optional_string(const SQLite::Statement& stmt, int column) {
    if (stmt.isColumnNull(column)) {
        return std::nullopt;
    }
    return stmt.getColumn(column).getString();
}

}  // namespace

SystemPromptManager::SystemPromptManager(std::shared_ptr<infrastructure::SQLiteConnection> connection)
    : connection_(std::move(connection)) {}

std::optional<SystemPrompt> SystemPromptManager::active_prompt(std::optional<std::int64_t> chat_id) {
    if (!connection_) {
        return std::nullopt;
    }

    if (auto cached = get_cached(chat_id)) {
        return cached;
    }

    std::optional<SystemPrompt> prompt;

    try {
        if (chat_id) {
            SQLite::Statement chat_stmt(
                connection_->db(),
                "SELECT id, admin_id, chat_id, scope, prompt_text, is_active, version, notes, "
                "created_at, updated_at, activated_at "
                "FROM system_prompts "
                "WHERE chat_id = ? AND scope = ? AND is_active = 1 "
                "ORDER BY activated_at DESC NULLS LAST, updated_at DESC LIMIT 1"
            );
            chat_stmt.bind(1, *chat_id);
            chat_stmt.bind(2, kChatScope);
            if (chat_stmt.executeStep()) {
                prompt = map_row(chat_stmt);
            }
        }

        if (!prompt) {
            SQLite::Statement global_stmt(
                connection_->db(),
                "SELECT id, admin_id, chat_id, scope, prompt_text, is_active, version, notes, "
                "created_at, updated_at, activated_at "
                "FROM system_prompts "
                "WHERE chat_id IS NULL AND scope = ? AND is_active = 1 "
                "ORDER BY activated_at DESC NULLS LAST, updated_at DESC LIMIT 1"
            );
            global_stmt.bind(1, kGlobalScope);
            if (global_stmt.executeStep()) {
                prompt = map_row(global_stmt);
            }
        }
    } catch (const std::exception& ex) {
        spdlog::error("active_prompt query failed: {}", ex.what());
        prompt = std::nullopt;
    }

    cache_prompt(chat_id, prompt);
    if (chat_id && prompt) {
        cache_prompt(std::nullopt, prompt);
    }
    return prompt;
}

SystemPrompt SystemPromptManager::set_prompt(std::int64_t admin_id,
                                            const std::string& prompt_text,
                                            std::optional<std::int64_t> chat_id,
                                            const std::string& scope,
                                            std::optional<std::string> notes) {
    if (!is_valid_scope(scope)) {
        throw std::invalid_argument("invalid scope for system prompt: " + scope);
    }
    if (scope == kChatScope && !chat_id) {
        throw std::invalid_argument("chat_id required for chat-scoped prompt");
    }

    try {
        SQLite::Transaction txn(connection_->db());

        const auto now = current_unix_seconds();
        std::optional<std::int64_t> normalized_chat_id = chat_id;
        if (scope == kGlobalScope) {
            normalized_chat_id.reset();
        }

        // deactivate existing active prompts for the same scope/chat
        SQLite::Statement deactivate(
            connection_->db(),
            "UPDATE system_prompts "
            "SET is_active = 0, updated_at = ? "
            "WHERE is_active = 1 AND scope = ? AND "
            "( (? IS NULL AND chat_id IS NULL) OR chat_id = ? )"
        );
        deactivate.bind(1, now);
        deactivate.bind(2, scope);
        if (normalized_chat_id) {
            deactivate.bind(3, *normalized_chat_id);
            deactivate.bind(4, *normalized_chat_id);
        } else {
            deactivate.bind(3);
            deactivate.bind(4);
        }
        deactivate.exec();

        SQLite::Statement insert(
            connection_->db(),
            "INSERT INTO system_prompts "
            "(admin_id, chat_id, scope, prompt_text, is_active, version, notes, created_at, updated_at, activated_at) "
            "VALUES (?, ?, ?, ?, 1, "
            "COALESCE((SELECT COALESCE(MAX(version), 0) + 1 FROM system_prompts WHERE scope = ? AND "
            "( (? IS NULL AND chat_id IS NULL) OR chat_id = ? )), 1), "
            "?, ?, ?, ?)"
        );
        insert.bind(1, admin_id);
        if (normalized_chat_id) {
            insert.bind(2, *normalized_chat_id);
        } else {
            insert.bind(2);
        }
        insert.bind(3, scope);
        insert.bind(4, prompt_text);
        insert.bind(5, scope);
        if (normalized_chat_id) {
            insert.bind(6, *normalized_chat_id);
            insert.bind(7, *normalized_chat_id);
        } else {
            insert.bind(6);
            insert.bind(7);
        }
        if (notes) {
            insert.bind(8, *notes);
        } else {
            insert.bind(8);
        }
        insert.bind(9, now);
        insert.bind(10, now);
        insert.bind(11, now);
        insert.exec();

        const auto prompt_id = static_cast<int>(connection_->db().getLastInsertRowid());
        SQLite::Statement select(
            connection_->db(),
            "SELECT id, admin_id, chat_id, scope, prompt_text, is_active, version, notes, "
            "created_at, updated_at, activated_at "
            "FROM system_prompts WHERE id = ?"
        );
        select.bind(1, prompt_id);
        if (!select.executeStep()) {
            throw std::runtime_error("Failed to fetch inserted prompt record");
        }

        txn.commit();

        SystemPrompt prompt = map_row(select);
        invalidate_cache(normalized_chat_id);
        invalidate_cache(std::nullopt);
        cache_prompt(normalized_chat_id, prompt);
        return prompt;
    } catch (const std::exception& ex) {
        spdlog::error("set_prompt failed: {}", ex.what());
        throw;
    }
}

void SystemPromptManager::deactivate_prompt(int prompt_id) {
    try {
        SQLite::Statement fetch(
            connection_->db(),
            "SELECT chat_id FROM system_prompts WHERE id = ?"
        );
        fetch.bind(1, prompt_id);
        std::optional<std::int64_t> chat_id;
        if (fetch.executeStep() && !fetch.isColumnNull(0)) {
            chat_id = fetch.getColumn(0).getInt64();
        }

        SQLite::Statement stmt(
            connection_->db(),
            "UPDATE system_prompts SET is_active = 0, updated_at = ? WHERE id = ?"
        );
        stmt.bind(1, current_unix_seconds());
        stmt.bind(2, prompt_id);
        stmt.exec();

        invalidate_cache(chat_id);
        invalidate_cache(std::nullopt);
    } catch (const std::exception& ex) {
        spdlog::error("deactivate_prompt failed: {}", ex.what());
        throw;
    }
}

void SystemPromptManager::reset_chat_prompt(std::int64_t chat_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "UPDATE system_prompts SET is_active = 0, updated_at = ? "
            "WHERE chat_id = ? AND scope = ? AND is_active = 1"
        );
        stmt.bind(1, current_unix_seconds());
        stmt.bind(2, chat_id);
        stmt.bind(3, kChatScope);
        stmt.exec();
        invalidate_cache(chat_id);
    } catch (const std::exception& ex) {
        spdlog::error("reset_chat_prompt failed: {}", ex.what());
        throw;
    }
}

std::vector<SystemPrompt> SystemPromptManager::list_prompts(std::optional<std::int64_t> chat_id,
                                                            std::optional<std::string> scope,
                                                            std::size_t limit) {
    std::vector<SystemPrompt> prompts;
    try {
        std::string query =
            "SELECT id, admin_id, chat_id, scope, prompt_text, is_active, version, notes, "
            "created_at, updated_at, activated_at "
            "FROM system_prompts WHERE 1=1 ";
        if (chat_id) {
            query += "AND chat_id = ? ";
        }
        if (scope) {
            query += "AND scope = ? ";
        }
        query += "ORDER BY updated_at DESC LIMIT ?";

        SQLite::Statement stmt(connection_->db(), query);
        int param_index = 1;
        if (chat_id) {
            stmt.bind(param_index++, *chat_id);
        }
        if (scope) {
            stmt.bind(param_index++, *scope);
        }
        stmt.bind(param_index, static_cast<int>(limit));

        while (stmt.executeStep()) {
            prompts.push_back(map_row(stmt));
        }
    } catch (const std::exception& ex) {
        spdlog::error("list_prompts failed: {}", ex.what());
    }
    return prompts;
}

void SystemPromptManager::purge_cache() {
    std::lock_guard guard(cache_mutex_);
    cache_.clear();
}

SystemPrompt SystemPromptManager::map_row(const SQLite::Statement& stmt) const {
    SystemPrompt prompt;
    prompt.id = stmt.getColumn(0).getInt();
    prompt.admin_id = stmt.getColumn(1).getInt64();
    prompt.chat_id = read_optional_int64(stmt, 2);
    prompt.scope = stmt.getColumn(3).getString();
    prompt.prompt_text = stmt.getColumn(4).getString();
    prompt.is_active = stmt.getColumn(5).getInt() != 0;
    prompt.version = stmt.getColumn(6).getInt();
    prompt.notes = read_optional_string(stmt, 7);
    prompt.created_at = from_unix(stmt.getColumn(8).getInt64());
    prompt.updated_at = from_unix(stmt.getColumn(9).getInt64());
    if (auto activated = read_optional_int64(stmt, 10)) {
        prompt.activated_at = from_unix(*activated);
    }
    return prompt;
}

void SystemPromptManager::cache_prompt(std::optional<std::int64_t> chat_id,
                                       const std::optional<SystemPrompt>& prompt) {
    std::lock_guard guard(cache_mutex_);
    cache_[chat_id] = CacheEntry{
        .prompt = prompt,
        .stored_at = std::chrono::steady_clock::now()
    };
}

std::optional<SystemPrompt> SystemPromptManager::get_cached(std::optional<std::int64_t> chat_id) {
    std::lock_guard guard(cache_mutex_);
    auto it = cache_.find(chat_id);
    if (it == cache_.end()) {
        return std::nullopt;
    }
    const auto now = std::chrono::steady_clock::now();
    if (now - it->second.stored_at > cache_ttl_) {
        cache_.erase(it);
        return std::nullopt;
    }
    return it->second.prompt;
}

void SystemPromptManager::invalidate_cache(std::optional<std::int64_t> chat_id) {
    std::lock_guard guard(cache_mutex_);
    if (chat_id.has_value()) {
        cache_.erase(chat_id);
    } else {
        cache_.erase(std::nullopt);
    }
}

}  // namespace gryag::services::prompt

