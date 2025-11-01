#include "gryag/handlers/admin_handler.hpp"

#include <spdlog/fmt/fmt.h>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <sstream>
#include <string_view>

namespace gryag::handlers {

namespace {
const std::string kAdminOnly = "Ця команда лише для своїх. І явно не для тебе.";
const std::string kMissingTarget = "Покажи, кого саме прибрати: зроби реплай або передай ID.";
const std::string kBanSuccess = "Готово: користувача кувалдіровано.";
const std::string kUnbanSuccess = "Ок, розбанив. Нехай знову пиздить.";
const std::string kAlreadyBanned = "Та він і так у бані сидів.";
const std::string kNotBanned = "Нема кого розбанювати — список чистий.";
const std::string kResetDone = "Все, обнулив ліміти. Можна знову розганяти балачки.";
const std::string kDonateMessage =
    "💸 Підтримай гряга! Монобанк: https://send.monobank.ua/jar/gryag";

std::string_view normalize_command(std::string_view text) {
    if (text.empty() || text.front() != '/') {
        return {};
    }
    auto end = text.find(' ');
    auto command = text.substr(0, end);
    auto at = command.find('@');
    if (at != std::string_view::npos) {
        command = command.substr(0, at);
    }
    return command;
}

}  // namespace

AdminHandler::AdminHandler(HandlerContext& ctx) : ctx_(ctx) {}

bool AdminHandler::handle(const telegram::Message& message, telegram::TelegramClient& client) {
    auto command = normalize_command(message.text);
    if (command.empty()) {
        return false;
    }

    if (command == "/gryagban" || command == "/ban") {
        return handle_ban(message, client);
    }
    if (command == "/gryagunban" || command == "/unban") {
        return handle_unban(message, client);
    }
    if (command == "/gryagreset" || command == "/reset") {
        return handle_reset(message, client);
    }
    if (command == "/gryagchatinfo" || command == "/chatinfo") {
        return handle_chatinfo(message, client);
    }
    if (command == "/gryagdonate" || command == "/donate") {
        return handle_donate(message, client);
    }
    return false;
}

bool AdminHandler::is_admin(const telegram::Message& message) const {
    if (!message.from.has_value() || !ctx_.settings) {
        return false;
    }
    const auto user_id = message.from->id;
    const auto& admins = ctx_.settings->admin_user_ids;
    return std::find(admins.begin(), admins.end(), static_cast<std::int64_t>(user_id)) != admins.end();
}

std::optional<std::int64_t> AdminHandler::extract_target_id(const telegram::Message& message,
                                                            std::string& label) const {
    if (message.reply_to_user) {
        label = !message.reply_to_user->first_name.empty()
            ? message.reply_to_user->first_name
            : message.reply_to_user->username;
        return message.reply_to_user->id;
    }

    std::istringstream iss(message.text);
    std::string command;
    iss >> command;
    std::string token;
    if (iss >> token) {
        if (!token.empty() && token.front() == '@') {
            return std::nullopt;
        }
        try {
            auto id = std::stoll(token);
            label = token;
            return id;
        } catch (...) {
            return std::nullopt;
        }
    }
    return std::nullopt;
}

bool AdminHandler::handle_ban(const telegram::Message& message, telegram::TelegramClient& client) {
    if (!is_admin(message)) {
        client.send_message(message.chat.id, kAdminOnly, message.message_id);
        return true;
    }
    std::string label;
    auto target = extract_target_id(message, label);
    if (!target) {
        client.send_message(message.chat.id, kMissingTarget, message.message_id);
        return true;
    }
    if (ctx_.context_store->is_banned(message.chat.id, *target)) {
        client.send_message(message.chat.id, kAlreadyBanned, message.message_id);
        return true;
    }
    ctx_.context_store->ban_user(message.chat.id, *target);
    client.send_message(message.chat.id, kBanSuccess, message.message_id);
    return true;
}

bool AdminHandler::handle_unban(const telegram::Message& message, telegram::TelegramClient& client) {
    if (!is_admin(message)) {
        client.send_message(message.chat.id, kAdminOnly, message.message_id);
        return true;
    }
    std::string label;
    auto target = extract_target_id(message, label);
    if (!target) {
        client.send_message(message.chat.id, kMissingTarget, message.message_id);
        return true;
    }
    if (!ctx_.context_store->is_banned(message.chat.id, *target)) {
        client.send_message(message.chat.id, kNotBanned, message.message_id);
        return true;
    }
    ctx_.context_store->unban_user(message.chat.id, *target);
    client.send_message(message.chat.id, kUnbanSuccess, message.message_id);
    return true;
}

bool AdminHandler::handle_reset(const telegram::Message& message, telegram::TelegramClient& client) {
    if (!is_admin(message)) {
        client.send_message(message.chat.id, kAdminOnly, message.message_id);
        return true;
    }
    ctx_.context_store->reset_rate_limits(message.chat.id);
    client.send_message(message.chat.id, kResetDone, message.message_id);
    return true;
}

bool AdminHandler::handle_chatinfo(const telegram::Message& message, telegram::TelegramClient& client) {
    if (!is_admin(message)) {
        client.send_message(message.chat.id, kAdminOnly, message.message_id);
        return true;
    }
    auto text = fmt::format("ID чату: {}", message.chat.id);
    client.send_message(message.chat.id, text, message.message_id);
    return true;
}

bool AdminHandler::handle_donate(const telegram::Message& message, telegram::TelegramClient& client) {
    if (!is_admin(message)) {
        client.send_message(message.chat.id, kAdminOnly, message.message_id);
        return true;
    }
    client.send_message(message.chat.id, kDonateMessage, message.message_id);
    return true;
}

}  // namespace gryag::handlers
