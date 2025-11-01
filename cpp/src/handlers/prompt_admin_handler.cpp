#include "gryag/handlers/prompt_admin_handler.hpp"

#include "gryag/services/prompt/system_prompt_manager.hpp"

#include <spdlog/spdlog.h>

#include <algorithm>
#include <sstream>
#include <string_view>

namespace gryag::handlers {

namespace {

std::string_view normalize_command(std::string_view text) {
    if (text.empty() || text.front() != '/') {
        return {};
    }
    auto end = text.find(' ');
    auto command = text.substr(0, end);
    const auto at = command.find('@');
    if (at != std::string_view::npos) {
        command = command.substr(0, at);
    }
    return command;
}

std::string format_prompt_preview(const services::prompt::SystemPrompt& prompt) {
    std::ostringstream oss;
    oss << "🧭 Версія #" << prompt.version << " (" << prompt.scope << ")\n";
    oss << "✍️ Оновив: " << prompt.admin_id << "\n";
    if (prompt.chat_id) {
        oss << "Чат: " << *prompt.chat_id << "\n";
    } else {
        oss << "Чат: глобальний\n";
    }
    oss << "🔓 Активний: " << (prompt.is_active ? "так" : "ні") << "\n\n";
    if (prompt.prompt_text.size() > 800) {
        oss << prompt.prompt_text.substr(0, 800) << "…";
    } else {
        oss << prompt.prompt_text;
    }
    if (prompt.notes && !prompt.notes->empty()) {
        oss << "\n\n📝 Нотатка: " << *prompt.notes;
    }
    return oss.str();
}

}  // namespace

PromptAdminHandler::PromptAdminHandler(HandlerContext& ctx) : ctx_(ctx) {}

bool PromptAdminHandler::handle(const telegram::Message& message, telegram::TelegramClient& client) {
    if (message.text.empty()) {
        return false;
    }
    auto command = normalize_command(message.text);
    if (command == "/gryagprompt" || command == "/prompt") {
        return handle_show_prompt(message, client);
    }
    if (command == "/gryagpromptset" || command == "/promptset") {
        return handle_set_prompt(message, client);
    }
    if (command == "/gryagpromptreset" || command == "/promptreset") {
        return handle_reset_prompt(message, client);
    }
    if (command == "/gryagpromptlist" || command == "/promptlist") {
        return handle_list_prompts(message, client);
    }
    return false;
}

bool PromptAdminHandler::handle_show_prompt(const telegram::Message& message,
                                            telegram::TelegramClient& client) {
    if (!ctx_.prompt_manager) {
        return false;
    }
    const auto prompt = ctx_.prompt_manager->active_prompt(message.chat.id);
    if (!prompt) {
        client.send_message(message.chat.id,
                            "🔧 Активний промпт: використовую стандартну персону.",
                            message.message_id);
        return true;
    }

    auto preview = format_prompt_preview(*prompt);
    client.send_message(message.chat.id, preview, message.message_id);
    return true;
}

bool PromptAdminHandler::handle_set_prompt(const telegram::Message& message,
                                           telegram::TelegramClient& client) {
    if (!ctx_.prompt_manager) {
        return false;
    }
    if (!ensure_admin(message, client)) {
        return true;
    }
    if (!message.from) {
        return true;
    }

    std::string_view text = message.text;
    const auto first_space = text.find(' ');
    if (first_space == std::string_view::npos) {
        client.send_message(message.chat.id,
                            "📌 Використання: /gryagpromptset <текст промпту> [--global]",
                            message.message_id);
        return true;
    }
    text.remove_prefix(first_space + 1);
    auto argument = trim_argument(text);
    if (argument.empty()) {
        client.send_message(message.chat.id,
                            "📌 Дай мені хоч якийсь текст після команди.",
                            message.message_id);
        return true;
    }

    bool global_scope = false;
    if (argument.rfind("--global", 0) == 0) {
        global_scope = true;
        argument = trim_argument(argument.substr(std::string_view{"--global"}.size()));
        if (argument.empty()) {
            client.send_message(message.chat.id,
                                "🤔 Після '--global' все одно треба написати текст промпту.",
                                message.message_id);
            return true;
        }
    }

    try {
        const std::string scope = global_scope ? "global"
            : (message.chat.id > 0 ? "personal" : "chat");
        std::optional<std::int64_t> target_chat;
        if (!global_scope) {
            target_chat = message.chat.id;
        }

        auto prompt = ctx_.prompt_manager->set_prompt(
            message.from->id,
            std::string{argument},
            target_chat,
            scope
        );

        auto preview = format_prompt_preview(prompt);
        client.send_message(message.chat.id,
                            "✅ Оновив промпт:\n\n" + preview,
                            message.message_id);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to set prompt: {}", ex.what());
        client.send_message(message.chat.id,
                            "❌ Не вийшло зберегти промпт. Подробиці в логах.",
                            message.message_id);
    }
    return true;
}

bool PromptAdminHandler::handle_reset_prompt(const telegram::Message& message,
                                             telegram::TelegramClient& client) {
    if (!ctx_.prompt_manager) {
        return false;
    }
    if (!ensure_admin(message, client)) {
        return true;
    }

    try {
        ctx_.prompt_manager->reset_chat_prompt(message.chat.id);
        client.send_message(message.chat.id,
                            "♻️ Скинув чат-промпт. Повертаюся до глобального.",
                            message.message_id);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to reset prompt: {}", ex.what());
        client.send_message(message.chat.id,
                            "❌ Не вдалось скинути промпт. Є помилка у логах.",
                            message.message_id);
    }
    return true;
}

bool PromptAdminHandler::handle_list_prompts(const telegram::Message& message,
                                             telegram::TelegramClient& client) {
    if (!ctx_.prompt_manager) {
        return false;
    }
    if (!ensure_admin(message, client)) {
        return true;
    }

    try {
        auto chat_prompts = ctx_.prompt_manager->list_prompts(message.chat.id, std::nullopt, 5);
        auto global_prompts = ctx_.prompt_manager->list_prompts(std::nullopt, std::string{"global"}, 5);

        std::ostringstream oss;
        if (!chat_prompts.empty()) {
            oss << "📚 Останні чат-промпти:\n";
            for (const auto& prompt : chat_prompts) {
                oss << " • #" << prompt.version << " ("
                    << (prompt.is_active ? "активний" : "архів") << ")"
                    << " — " << prompt.prompt_text.substr(0, 80);
                if (prompt.prompt_text.size() > 80) {
                    oss << "…";
                }
                oss << "\n";
            }
        } else {
            oss << "📚 Для цього чату нема власних промптів.\n";
        }

        if (!global_prompts.empty()) {
            oss << "\n🌍 Глобальні промпти:\n";
            for (const auto& prompt : global_prompts) {
                oss << " • #" << prompt.version << " "
                    << (prompt.is_active ? "(активний)" : "(архів)") << "\n";
            }
        }

        client.send_message(message.chat.id, oss.str(), message.message_id);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to list prompts: {}", ex.what());
        client.send_message(message.chat.id,
                            "❌ Не можу отримати список промптів.",
                            message.message_id);
    }
    return true;
}

bool PromptAdminHandler::ensure_admin(const telegram::Message& message,
                                      telegram::TelegramClient& client) const {
    if (!ctx_.settings || !message.from) {
        return false;
    }
    const auto user_id = message.from->id;
    const auto& admins = ctx_.settings->admin_user_ids;
    const auto is_admin = std::find(admins.begin(), admins.end(), user_id) != admins.end();
    if (!is_admin) {
        client.send_message(message.chat.id,
                            "🚫 Це тільки для адмінів, друже.",
                            message.message_id);
    }
    return is_admin;
}

std::string PromptAdminHandler::trim_argument(std::string_view argument) const {
    const auto start = argument.find_first_not_of(" \t\n\r");
    if (start == std::string_view::npos) {
        return {};
    }
    const auto end = argument.find_last_not_of(" \t\n\r");
    return std::string(argument.substr(start, end - start + 1));
}

}  // namespace gryag::handlers

