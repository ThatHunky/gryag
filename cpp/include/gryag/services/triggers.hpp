#pragma once

#include "gryag/telegram/types.hpp"

#include <regex>
#include <string>
#include <vector>

namespace gryag::services {

/**
 * Trigger detection service for determining when the bot should respond to messages.
 *
 * This service implements the logic to check if a message is addressed to the bot through:
 * - Direct replies to bot messages
 * - @mentions of the bot
 * - Keyword triggers (e.g., "гряг", "gryag")
 * - Private chat detection (always respond in private chats)
 */
class TriggerDetector {
public:
    /**
     * Initialize trigger patterns from configuration.
     * If no patterns provided, uses default Ukrainian/English patterns.
     */
    explicit TriggerDetector(const std::vector<std::string>& patterns = {});

    /**
     * Check if a message is addressed to the bot.
     *
     * @param message The incoming message
     * @param bot_username Bot's username (with or without @)
     * @param bot_id Bot's user ID
     * @return true if the bot should respond to this message
     */
    bool addressed_to_bot(
        const telegram::Message& message,
        const std::string& bot_username,
        std::int64_t bot_id
    ) const;

private:
    /**
     * Check if text contains any trigger keywords.
     */
    bool contains_keyword(const std::string& text) const;

    /**
     * Check if message entities contain a mention of the bot.
     */
    bool matches_mention(
        const std::string& text,
        const std::vector<telegram::MessageEntity>& entities,
        const std::string& username,
        std::int64_t bot_id
    ) const;

    /**
     * Normalize username by removing @ prefix and converting to lowercase.
     */
    static std::string normalize_username(const std::string& username);

    std::vector<std::regex> trigger_patterns_;
};

}  // namespace gryag::services
