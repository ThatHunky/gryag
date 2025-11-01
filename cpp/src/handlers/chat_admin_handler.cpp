#include "gryag/handlers/chat_admin_handler.hpp"

#include <SQLiteCpp/Statement.h>
#include <SQLiteCpp/Transaction.h>
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

}  // namespace

ChatAdminHandler::ChatAdminHandler(HandlerContext& ctx) : ctx_(ctx) {}

bool ChatAdminHandler::handle(const telegram::Message& message, telegram::TelegramClient& client) {
    if (message.text.empty()) {
        return false;
    }
    auto command = normalize_command(message.text);
    if (command == "/gryagchatfacts" || command == "/chatfacts") {
        return handle_chat_facts(message, client);
    }
    if (command == "/gryagchatreset" || command == "/chatreset") {
        return handle_chat_reset(message, client);
    }
    if (command == "/gryagchatsettings" || command == "/chatsettings") {
        return handle_chat_settings(message, client);
    }
    return false;
}

bool ChatAdminHandler::handle_chat_facts(const telegram::Message& message,
                                         telegram::TelegramClient& client) {
    if (!ctx_.connection) {
        return false;
    }
    try {
        SQLite::Statement stmt(
            ctx_.connection->db(),
            "SELECT memory_text, COUNT(*) AS cnt, MAX(created_at) as last_seen "
            "FROM user_memories "
            "WHERE chat_id = ? "
            "GROUP BY memory_text "
            "ORDER BY cnt DESC, last_seen DESC "
            "LIMIT 12"
        );
        stmt.bind(1, message.chat.id);

        std::ostringstream oss;
        oss << "🏘️ Факти про чат:\n";

        int rank = 1;
        while (stmt.executeStep()) {
            const auto text = stmt.getColumn("memory_text").getString();
            const auto count = stmt.getColumn("cnt").getInt();
            oss << rank++ << ". " << text;
            if (count > 1) {
                oss << " (" << count << "×)";
            }
            oss << "\n";
        }

        if (rank == 1) {
            oss << "Ще нема збережених фактів. Поговори зі мною трохи довше 😉";
        }

        client.send_message(message.chat.id, oss.str(), message.message_id);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to fetch chat facts: {}", ex.what());
        client.send_message(message.chat.id,
                            "❌ Не можу витягти факти про чат. Перевір логи.",
                            message.message_id);
    }
    return true;
}

bool ChatAdminHandler::handle_chat_reset(const telegram::Message& message,
                                         telegram::TelegramClient& client) {
    if (!ctx_.connection) {
        return false;
    }
    if (!ensure_admin(message, client)) {
        return true;
    }

    auto argument = extract_argument(message.text);
    if (!argument || (*argument != "confirm" && *argument != "підтверджую")) {
        client.send_message(message.chat.id,
                            "⚠️ Це зітре всі профілі та факти цього чату.\n"
                            "Додай 'confirm' після команди, щоб підтвердити.\n"
                            "Приклад: /gryagchatreset confirm",
                            message.message_id);
        return true;
    }

    try {
        SQLite::Transaction txn(ctx_.connection->db());
        SQLite::Statement wipe_memories(
            ctx_.connection->db(),
            "DELETE FROM user_memories WHERE chat_id = ?"
        );
        wipe_memories.bind(1, message.chat.id);
        wipe_memories.exec();

        SQLite::Statement wipe_profiles(
            ctx_.connection->db(),
            "DELETE FROM user_profiles WHERE chat_id = ?"
        );
        wipe_profiles.bind(1, message.chat.id);
        wipe_profiles.exec();

        txn.commit();

        client.send_message(message.chat.id,
                            "🧹 Готово. Починаємо збирати факти з нуля.",
                            message.message_id);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to reset chat data: {}", ex.what());
        client.send_message(message.chat.id,
                            "❌ Не зміг очистити дані чату. Дивись логи.",
                            message.message_id);
    }
    return true;
}

bool ChatAdminHandler::handle_chat_settings(const telegram::Message& message,
                                            telegram::TelegramClient& client) {
    if (!ctx_.settings) {
        return false;
    }
    if (!ensure_admin(message, client)) {
        return true;
    }

    const auto& s = *ctx_.settings;
    std::ostringstream oss;
    oss << "⚙️ Налаштування бота:\n"
        << "• Ліміт повідомлень / год: " << s.per_user_per_hour << "\n"
        << "• Multilevel context: " << (s.enable_multi_level_context ? "вкл" : "викл") << "\n"
        << "• Hybrid search: " << (s.enable_hybrid_search ? "вкл" : "викл") << "\n"
        << "• Image tool: " << (s.enable_image_generation ? "вкл" : "викл") << "\n"
        << "• Web search: " << (s.enable_web_search ? "вкл" : "викл") << "\n"
        << "• Episodic memory: " << (s.enable_episodic_memory ? "вкл" : "викл") << "\n"
        << "• Командний кулдаун: " << s.command_cooldown_seconds << " с\n";

    client.send_message(message.chat.id, oss.str(), message.message_id);
    return true;
}

bool ChatAdminHandler::ensure_admin(const telegram::Message& message,
                                    telegram::TelegramClient& client) const {
    if (!ctx_.settings || !message.from) {
        return false;
    }
    const auto user_id = message.from->id;
    const auto& admins = ctx_.settings->admin_user_ids;
    const auto it = std::find(admins.begin(), admins.end(), user_id);
    if (it == admins.end()) {
        client.send_message(message.chat.id,
                            "🚫 Команда лише для адмінів.",
                            message.message_id);
        return false;
    }
    return true;
}

std::optional<std::string> ChatAdminHandler::extract_argument(std::string_view text) const {
    const auto space = text.find(' ');
    if (space == std::string_view::npos) {
        return std::nullopt;
    }
    auto argument = text.substr(space + 1);
    const auto start = argument.find_first_not_of(" \t\n\r");
    if (start == std::string_view::npos) {
        return std::nullopt;
    }
    const auto end = argument.find_last_not_of(" \t\n\r");
    return std::string(argument.substr(start, end - start + 1));
}

}  // namespace gryag::handlers
