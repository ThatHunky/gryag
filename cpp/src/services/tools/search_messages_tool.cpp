#include "gryag/services/tools/search_messages_tool.hpp"

#include <SQLiteCpp/Statement.h>
#include <nlohmann/json.hpp>
#include <spdlog/fmt/fmt.h>

#include <algorithm>
#include <optional>

namespace gryag::services::tools {

namespace {

nlohmann::json run_search(SQLite::Database& db,
                          const std::string& query,
                          std::int64_t chat_id,
                          std::optional<std::int64_t> thread_id,
                          int limit) {
    SQLite::Statement stmt(
        db,
        thread_id ?
            "SELECT id, user_id, role, text, ts FROM messages "
            "WHERE chat_id = ? AND thread_id = ? AND text LIKE ? ORDER BY ts DESC LIMIT ?"
            :
            "SELECT id, user_id, role, text, ts FROM messages "
            "WHERE chat_id = ? AND text LIKE ? ORDER BY ts DESC LIMIT ?"
    );

    stmt.bind(1, chat_id);
    int bind_index = 2;
    if (thread_id) {
        stmt.bind(bind_index++, *thread_id);
    }
    const auto like_query = "%" + query + "%";
    stmt.bind(bind_index++, like_query);
    stmt.bind(bind_index, limit);

    nlohmann::json results = nlohmann::json::array();
    while (stmt.executeStep()) {
        nlohmann::json item;
        item["message_id"] = stmt.getColumn(0).getInt64();
        item["user_id"] = stmt.getColumn(1).getInt64();
        item["role"] = stmt.getColumn(2).getString();
        item["text"] = stmt.getColumn(3).getString();
        item["timestamp"] = stmt.getColumn(4).getInt64();
        item["metadata"] = {
            {"chat_id", chat_id},
            {"user_id", item["user_id"]},
            {"role", item["role"]}
        };
        item["score"] = 1.0;
        item["metadata_text"] = fmt::format("chat_id={} user_id={}", chat_id, item["user_id"].get<std::int64_t>());
        results.push_back(item);
    }

    // Return in chronological order (oldest first)
    std::reverse(results.begin(), results.end());
    return results;
}

}  // namespace

void register_search_messages_tool(ToolRegistry& registry,
                                   std::shared_ptr<infrastructure::SQLiteConnection> connection) {
    registry.register_tool(
        ToolDefinition{
            .name = "search_messages",
            .description = "Шукати релевантні повідомлення в історії чату за текстовою відповідністю",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"query", {
                        {"type", "string"},
                        {"description", "Пошуковий запит"}
                    }},
                    {"limit", {
                        {"type", "integer"},
                        {"description", "Кількість результатів (1-10)"}
                    }},
                    {"thread_only", {
                        {"type", "boolean"},
                        {"description", "Обмежити пошук поточним тредом"}
                    }}
                }},
                {"required", {"query"}}
            }
        },
        [connection](const nlohmann::json& args, ToolContext& ctx) {
            const auto query = args.value("query", std::string{});
            if (query.empty()) {
                return nlohmann::json{{"results", nlohmann::json::array()}};
            }
            const int limit = std::clamp(args.value("limit", 5), 1, 10);
            const bool thread_only = args.value("thread_only", true);
            const auto chat_id = ctx.state.value("chat_id", 0LL);
            const auto thread_id_opt = ctx.state.contains("thread_id")
                ? std::optional<std::int64_t>(ctx.state["thread_id"].get<std::int64_t>())
                : std::optional<std::int64_t>{};

            if (chat_id == 0) {
                return nlohmann::json{{"results", nlohmann::json::array()}, {"error", "chat_id missing"}};
            }

            nlohmann::json results;
            if (thread_only && thread_id_opt) {
                results = run_search(connection->db(), query, chat_id, thread_id_opt, limit);
            } else {
                results = run_search(connection->db(), query, chat_id, std::nullopt, limit);
            }

            return nlohmann::json{
                {"results", results},
                {"query", query},
                {"count", results.size()}
            };
        }
    );
}

}  // namespace gryag::services::tools
