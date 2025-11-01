#pragma once

#include "gryag/handlers/handler_context.hpp"
#include "gryag/telegram/types.hpp"
#include "gryag/telegram/client.hpp"

namespace gryag::handlers {

class ProfileHandler {
public:
    explicit ProfileHandler(HandlerContext& ctx);

    bool handle(const telegram::Message& message, telegram::TelegramClient& client);
    void handle_callback_query(const telegram::CallbackQuery& callback, telegram::TelegramClient& client);

private:
    bool handle_profile(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_users(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_facts(const telegram::Message& message, telegram::TelegramClient& client);

    HandlerContext& ctx_;
};

}  // namespace gryag::handlers
