#include "gryag/handlers/profile_handler.hpp"
#include "gryag/services/user_profile_store.hpp"

#include <SQLiteCpp/Statement.h>
#include <spdlog/fmt/fmt.h>
#include <spdlog/spdlog.h>

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
    auto at = command.find('@');
    if (at != std::string_view::npos) {
        command = command.substr(0, at);
    }
    return command;
}

std::string format_profile_row(const SQLite::Statement& stmt) {
    const auto first = stmt.getColumn("first_name").isNull() ? std::string{} : stmt.getColumn("first_name").getString();
    const auto last = stmt.getColumn("last_name").isNull() ? std::string{} : stmt.getColumn("last_name").getString();
    const auto display = stmt.getColumn("display_name").isNull() ? std::string{} : stmt.getColumn("display_name").getString();
    const auto username = stmt.getColumn("username").isNull() ? std::string{} : stmt.getColumn("username").getString();
    const auto pronouns = stmt.getColumn("pronouns").isNull() ? std::string{} : stmt.getColumn("pronouns").getString();
    const auto summary = stmt.getColumn("summary").isNull() ? std::string{} : stmt.getColumn("summary").getString();

    std::ostringstream oss;
    if (!display.empty()) {
        oss << "Ім'я: " << display << "\n";
    } else if (!first.empty() || !last.empty()) {
        oss << "Ім'я: " << first << ' ' << last << "\n";
    }
    if (!username.empty()) {
        oss << "Нік: @" << username << "\n";
    }
    if (!pronouns.empty()) {
        oss << "Займенники: " << pronouns << "\n";
    }
    if (!summary.empty()) {
        oss << "Резюме: " << summary << "\n";
    }
    return oss.str();
}

}  // namespace

ProfileHandler::ProfileHandler(HandlerContext& ctx) : ctx_(ctx) {}

bool ProfileHandler::handle(const telegram::Message& message, telegram::TelegramClient& client) {
    auto command = normalize_command(message.text);
    if (command.empty()) {
        return false;
    }
    if (command == "/gryagprofile" || command == "/profile") {
        return handle_profile(message, client);
    }
    if (command == "/gryagusers" || command == "/users") {
        return handle_users(message, client);
    }
    if (command == "/gryagfacts" || command == "/facts") {
        return handle_facts(message, client);
    }
    return false;
}

bool ProfileHandler::handle_profile(const telegram::Message& message, telegram::TelegramClient& client) {
    if (!ctx_.profile_store) {
        return false;
    }

    std::int64_t target_id = message.from ? message.from->id : 0;
    if (message.reply_to_user) {
        target_id = message.reply_to_user->id;
    }

    auto profile_opt = ctx_.profile_store->get_profile(target_id, message.chat.id);
    if (!profile_opt.has_value()) {
        client.send_message(message.chat.id,
                            "Профіль ще порожній. Спробуй поговорити зі мною довше.",
                            message.message_id);
        return true;
    }

    const auto& profile = profile_opt.value();

    std::ostringstream oss;
    if (!profile.display_name.empty()) {
        oss << "Ім'я: " << profile.display_name << "\n";
    } else if (!profile.first_name.empty() || !profile.last_name.empty()) {
        oss << "Ім'я: " << profile.first_name << " " << profile.last_name << "\n";
    }
    if (!profile.username.empty()) {
        oss << "Нік: @" << profile.username << "\n";
    }
    if (!profile.pronouns.empty()) {
        oss << "Займенники: " << profile.pronouns << "\n";
    }
    if (!profile.summary.empty()) {
        oss << "Резюме: " << profile.summary << "\n";
    }

    // Add interaction count and membership status
    oss << "Взаємодій: " << profile.interaction_count << "\n";
    if (!profile.membership_status.empty() && profile.membership_status != "unknown") {
        oss << "Статус: " << profile.membership_status << "\n";
    }

    client.send_message(message.chat.id, oss.str(), message.message_id);
    return true;
}

bool ProfileHandler::handle_users(const telegram::Message& message, telegram::TelegramClient& client) {
    if (!ctx_.profile_store) {
        return false;
    }

    auto profiles = ctx_.profile_store->list_chat_users(message.chat.id, true, 20);

    std::ostringstream oss;
    oss << "👥 Користувачі чату:" << '\n';

    if (profiles.empty()) {
        oss << "Поки що нема жодного користувача.";
    } else {
        int index = 1;
        for (const auto& profile : profiles) {
            std::string name;
            if (!profile.display_name.empty()) {
                name = profile.display_name;
            } else if (!profile.username.empty()) {
                name = profile.username;
            } else {
                name = std::to_string(profile.user_id);
            }
            oss << index++ << ". " << name << "\n";
        }
    }

    client.send_message(message.chat.id, oss.str(), message.message_id);
    return true;
}

bool ProfileHandler::handle_facts(const telegram::Message& message, telegram::TelegramClient& client) {
    if (!ctx_.profile_store) {
        return false;
    }

    std::int64_t target_id = message.from ? message.from->id : 0;
    if (message.reply_to_user) {
        target_id = message.reply_to_user->id;
    }

    auto facts = ctx_.profile_store->get_facts(target_id, message.chat.id, true, 0.7);

    std::ostringstream oss;
    oss << "🧠 Факти:" << '\n';

    if (facts.empty()) {
        oss << "Поки що нема жодного факту.";
    } else {
        int index = 1;
        for (const auto& fact : facts) {
            // Format: "key: value (confidence%)"
            oss << index++ << ". " << fact.fact_key << ": " << fact.fact_value;
            if (fact.confidence < 1.0) {
                oss << " (" << static_cast<int>(fact.confidence * 100) << "%)";
            }
            oss << "\n";
        }
    }

    client.send_message(message.chat.id, oss.str(), message.message_id);
    return true;
}

void ProfileHandler::handle_callback_query(const telegram::CallbackQuery& callback,
                                           telegram::TelegramClient& client) {
    // Parse callback data format: "facts:user_id:page"
    const auto& data = callback.data;

    if (data.find("facts:") != 0) {
        client.answer_callback_query(callback.id, "Невідомий тип запиту", true);
        return;
    }

    // Extract user_id and page from callback data
    size_t first_colon = data.find(':');
    size_t second_colon = data.find(':', first_colon + 1);

    if (first_colon == std::string::npos || second_colon == std::string::npos) {
        client.answer_callback_query(callback.id, "Помилка формату даних", true);
        return;
    }

    try {
        std::int64_t user_id = std::stoll(data.substr(first_colon + 1, second_colon - first_colon - 1));
        int page = std::stoi(data.substr(second_colon + 1));

        // TODO: Implement proper pagination when user profile system is complete
        // For now, just acknowledge the callback
        client.answer_callback_query(callback.id,
                                     fmt::format("Сторінка {} для користувача {}", page, user_id),
                                     false);

        spdlog::info("Facts pagination: user_id={}, page={}", user_id, page);

    } catch (const std::exception& ex) {
        spdlog::error("Error parsing callback data '{}': {}", data, ex.what());
        client.answer_callback_query(callback.id, "Помилка обробки даних", true);
    }
}

}  // namespace gryag::handlers
