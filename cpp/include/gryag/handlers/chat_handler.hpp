#pragma once

#include "gryag/handlers/handler_context.hpp"
#include "gryag/telegram/types.hpp"
#include "gryag/telegram/client.hpp"

#include <nlohmann/json.hpp>

#include <optional>
#include <string>
#include <vector>

namespace gryag::handlers {

struct ToolInvocation {
    std::string name;
    nlohmann::json args;
    nlohmann::json assistant_content;
};

class ChatHandler {
public:
    explicit ChatHandler(HandlerContext& context);

    void handle_update(const telegram::Message& message, telegram::TelegramClient& client);

private:
    std::string format_response_text(const std::string& text);
    bool acquire_processing_lock(std::int64_t chat_id, std::int64_t user_id);
    void release_processing_lock(std::int64_t chat_id, std::int64_t user_id);
    bool is_banned(std::int64_t chat_id, std::int64_t user_id);
    bool allow_rate(std::int64_t user_id);
    bool allow_feature(std::int64_t user_id, const std::string& feature_name);
    std::optional<ToolInvocation> next_tool_call(const services::gemini::GeminiResponse& response) const;

    // Media handling
    void process_media_from_message(const telegram::Message& message, std::int64_t chat_id, std::int64_t user_id);
    void extract_and_store_media(const telegram::Message& message, std::int64_t chat_id, std::int64_t user_id);

    HandlerContext& ctx_;
};

}  // namespace gryag::handlers
