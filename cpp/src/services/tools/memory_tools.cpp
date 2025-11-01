#include "gryag/services/tools/memory_tools.hpp"
#include "gryag/repositories/memory_repository.hpp"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <optional>
#include <string>

namespace gryag::services::tools {

namespace {

std::int64_t to_int64(const nlohmann::json& value, std::int64_t fallback = 0) {
    if (value.is_number_integer()) {
        return value.get<std::int64_t>();
    }
    if (value.is_string()) {
        try {
            return std::stoll(value.get<std::string>());
        } catch (...) {
            return fallback;
        }
    }
    return fallback;
}

void add_memory(repositories::MemoryRepository& repo,
                std::int64_t user_id,
                std::int64_t chat_id,
                const std::string& text) {
    repo.add_memory(user_id, chat_id, text);
}

nlohmann::json load_memories(repositories::MemoryRepository& repo,
                             std::int64_t user_id,
                             std::int64_t chat_id,
                             int limit) {
    auto memories_vec = repo.get_memories_for_user(user_id, chat_id);

    nlohmann::json memories = nlohmann::json::array();
    // Return most recent first, up to limit
    int count = 0;
    for (auto it = memories_vec.rbegin(); it != memories_vec.rend() && count < limit; ++it, ++count) {
        memories.push_back({
            {"id", it->id},
            {"memory_text", it->memory_text},
            {"created_at", it->created_at}
        });
    }
    return memories;
}

void delete_memory(repositories::MemoryRepository& repo,
                   std::int64_t user_id,
                   std::int64_t chat_id,
                   std::optional<std::int64_t> memory_id,
                   std::optional<std::string> memory_text) {
    if (memory_id) {
        // Verify the memory belongs to the user before deleting
        auto memory = repo.get_memory_by_id(*memory_id);
        if (memory && memory->user_id == user_id && memory->chat_id == chat_id) {
            repo.delete_memory(*memory_id);
        }
        return;
    }
    if (memory_text) {
        // Find memory by text and delete it
        auto memories = repo.get_memories_for_user(user_id, chat_id);
        for (const auto& mem : memories) {
            if (mem.memory_text == *memory_text) {
                repo.delete_memory(mem.id);
                break;
            }
        }
    }
}

void clear_memories(repositories::MemoryRepository& repo,
                    std::int64_t user_id,
                    std::int64_t chat_id) {
    repo.delete_all_memories(user_id, chat_id);
}

std::int64_t resolve_user_id(const nlohmann::json& args, const ToolContext& ctx) {
    if (args.contains("user_id")) {
        return to_int64(args["user_id"], ctx.state.value("user_id", 0LL));
    }
    if (args.contains("target_user_id")) {
        return to_int64(args["target_user_id"], ctx.state.value("user_id", 0LL));
    }
    return ctx.state.value("user_id", 0LL);
}

std::int64_t resolve_chat_id(const nlohmann::json& args, const ToolContext& ctx) {
    if (args.contains("chat_id")) {
        return to_int64(args["chat_id"], ctx.state.value("chat_id", 0LL));
    }
    return ctx.state.value("chat_id", 0LL);
}

}  // namespace

void register_memory_tools(ToolRegistry& registry,
                           repositories::MemoryRepository* memory_repository,
                           bool enabled) {
    if (!enabled || !memory_repository) {
        return;
    }

    // remember_memory
    registry.register_tool(
        ToolDefinition{
            .name = "remember_memory",
            .description = "Зберегти новий факт про користувача",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"memory_text", {
                        {"type", "string"},
                        {"description", "Текст факту"}
                    }},
                    {"user_id", {{"type", "integer"}}},
                    {"chat_id", {{"type", "integer"}}}
                }},
                {"required", {"memory_text"}}
            }
        },
        [memory_repository](const nlohmann::json& args, ToolContext& ctx) {
            const auto text = args.value("memory_text", std::string{});
            if (text.empty()) {
                return nlohmann::json{{"success", false}, {"error", "memory_text required"}};
            }
            const auto user_id = resolve_user_id(args, ctx);
            const auto chat_id = resolve_chat_id(args, ctx);
            if (user_id == 0 || chat_id == 0) {
                return nlohmann::json{{"success", false}, {"error", "user_id or chat_id missing"}};
            }
            try {
                add_memory(*memory_repository, user_id, chat_id, text);
            } catch (const std::exception& ex) {
                return nlohmann::json{{"success", false}, {"error", ex.what()}};
            }
            return nlohmann::json{{"success", true}};
        }
    );

    // recall_memories
    registry.register_tool(
        ToolDefinition{
            .name = "recall_memories",
            .description = "Отримати факти про користувача",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"limit", {{"type", "integer"}}},
                    {"user_id", {{"type", "integer"}}},
                    {"chat_id", {{"type", "integer"}}}
                }},
                {"required", {}}
            }
        },
        [memory_repository](const nlohmann::json& args, ToolContext& ctx) {
            const auto user_id = resolve_user_id(args, ctx);
            const auto chat_id = resolve_chat_id(args, ctx);
            if (user_id == 0 || chat_id == 0) {
                return nlohmann::json{{"success", false}, {"error", "user_id or chat_id missing"}};
            }
            const int limit = std::clamp(args.value("limit", 5), 1, 15);
            auto memories = load_memories(*memory_repository, user_id, chat_id, limit);
            return nlohmann::json{{"success", true}, {"memories", memories}};
        }
    );

    // forget_memory
    registry.register_tool(
        ToolDefinition{
            .name = "forget_memory",
            .description = "Видалити конкретний факт",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"memory_id", {{"type", "integer"}}},
                    {"memory_text", {{"type", "string"}}},
                    {"user_id", {{"type", "integer"}}},
                    {"chat_id", {{"type", "integer"}}}
                }},
                {"required", {}}
            }
        },
        [memory_repository](const nlohmann::json& args, ToolContext& ctx) {
            const auto user_id = resolve_user_id(args, ctx);
            const auto chat_id = resolve_chat_id(args, ctx);
            if (user_id == 0 || chat_id == 0) {
                return nlohmann::json{{"success", false}, {"error", "user_id or chat_id missing"}};
            }
            std::optional<std::int64_t> memory_id;
            if (args.contains("memory_id")) {
                memory_id = to_int64(args["memory_id"]);
            }
            std::optional<std::string> memory_text;
            if (args.contains("memory_text") && args["memory_text"].is_string()) {
                memory_text = args["memory_text"].get<std::string>();
            }
            delete_memory(*memory_repository, user_id, chat_id, memory_id, memory_text);
            return nlohmann::json{{"success", true}};
        }
    );

    // forget_all_memories
    registry.register_tool(
        ToolDefinition{
            .name = "forget_all_memories",
            .description = "Видалити всі факти про користувача",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"user_id", {{"type", "integer"}}},
                    {"chat_id", {{"type", "integer"}}}
                }},
                {"required", {}}
            }
        },
        [memory_repository](const nlohmann::json& args, ToolContext& ctx) {
            const auto user_id = resolve_user_id(args, ctx);
            const auto chat_id = resolve_chat_id(args, ctx);
            if (user_id == 0 || chat_id == 0) {
                return nlohmann::json{{"success", false}, {"error", "user_id or chat_id missing"}};
            }
            clear_memories(*memory_repository, user_id, chat_id);
            return nlohmann::json{{"success", true}};
        }
    );

    // Note: set_pronouns tool removed - should be refactored to use UserProfileStore
}

}  // namespace gryag::services::tools
