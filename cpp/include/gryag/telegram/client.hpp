#pragma once

#include "gryag/telegram/types.hpp"

#include <chrono>
#include <optional>
#include <string>
#include <vector>

namespace gryag::telegram {

class TelegramClient {
public:
    explicit TelegramClient(std::string token);

    /**
     * Update structure containing both messages and callback queries
     */
    struct Update {
        std::vector<Message> messages;
        std::vector<CallbackQuery> callback_queries;
    };

    void set_commands(const std::vector<std::pair<std::string, std::string>>& commands);
    void send_message(std::int64_t chat_id,
                      const std::string& text,
                      std::optional<std::int64_t> reply_to_message_id = std::nullopt);

    /**
     * Poll for updates (messages and callback queries)
     */
    Update poll_updates(std::chrono::seconds timeout);

    /**
     * Legacy poll method - returns only messages for backward compatibility
     */
    std::vector<Message> poll(std::chrono::seconds timeout);

    /**
     * Answer a callback query (respond to button press)
     * @param callback_query_id Unique identifier for the query
     * @param text Optional text to show to user (notification or alert)
     * @param show_alert If true, shows alert instead of notification
     */
    void answer_callback_query(const std::string& callback_query_id,
                               const std::string& text = "",
                               bool show_alert = false);

    /**
     * Send a chat action (typing indicator, upload status, etc.)
     * @param chat_id Target chat
     * @param action Action type: "typing", "upload_photo", "record_video", etc.
     */
    void send_chat_action(std::int64_t chat_id, const std::string& action);

    /**
     * Get information about the bot itself.
     * Calls the /getMe endpoint to fetch bot's user ID and username.
     */
    User get_me();

private:
    std::string base_url_;
    std::int64_t last_update_id_ = 0;
};

}  // namespace gryag::telegram
