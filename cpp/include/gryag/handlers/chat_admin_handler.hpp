#pragma once

#include "gryag/handlers/handler_context.hpp"
#include "gryag/telegram/client.hpp"

#include <optional>
#include <unordered_map>
#include <utility>

namespace gryag::handlers {

class ChatAdminHandler {
public:
    explicit ChatAdminHandler(HandlerContext& ctx);

    bool handle(const telegram::Message& message, telegram::TelegramClient& client);

private:
    bool handle_chat_facts(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_chat_reset(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_chat_settings(const telegram::Message& message, telegram::TelegramClient& client);

    bool ensure_admin(const telegram::Message& message, telegram::TelegramClient& client) const;
    std::optional<std::string> extract_argument(std::string_view text) const;

    HandlerContext& ctx_;
};

}  // namespace gryag::handlers
