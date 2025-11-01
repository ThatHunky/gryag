#pragma once

#include "gryag/handlers/handler_context.hpp"
#include "gryag/telegram/types.hpp"
#include "gryag/telegram/client.hpp"

#include <optional>
#include <string>

namespace gryag::handlers {

class AdminHandler {
public:
    explicit AdminHandler(HandlerContext& ctx);

    bool handle(const telegram::Message& message, telegram::TelegramClient& client);

private:
    bool is_admin(const telegram::Message& message) const;
    std::optional<std::int64_t> extract_target_id(const telegram::Message& message, std::string& label) const;

    bool handle_ban(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_unban(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_reset(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_chatinfo(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_donate(const telegram::Message& message, telegram::TelegramClient& client);

    HandlerContext& ctx_;
};

}  // namespace gryag::handlers
