#pragma once

#include "gryag/handlers/handler_context.hpp"
#include "gryag/telegram/client.hpp"

namespace gryag::handlers {

class PromptAdminHandler {
public:
    explicit PromptAdminHandler(HandlerContext& ctx);

    bool handle(const telegram::Message& message, telegram::TelegramClient& client);

private:
    bool handle_show_prompt(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_set_prompt(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_reset_prompt(const telegram::Message& message, telegram::TelegramClient& client);
    bool handle_list_prompts(const telegram::Message& message, telegram::TelegramClient& client);

    bool ensure_admin(const telegram::Message& message, telegram::TelegramClient& client) const;
    std::string trim_argument(std::string_view argument) const;

    HandlerContext& ctx_;
};

}  // namespace gryag::handlers
