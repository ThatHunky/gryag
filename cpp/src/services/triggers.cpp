#include "gryag/services/triggers.hpp"

#include <algorithm>
#include <cctype>

namespace gryag::services {

namespace {

// Default trigger pattern for Ukrainian and English variations
// Matches: гряг, грiг, gryag, griag, etc. with various endings
constexpr const char* kDefaultPattern = R"(\b(?:гр[яи]г[аоуеєіїюяьґ]*|gr[yi]ag\w*)\b)";

}  // namespace

TriggerDetector::TriggerDetector(const std::vector<std::string>& patterns) {
    if (patterns.empty()) {
        // Use default pattern
        trigger_patterns_.emplace_back(
            kDefaultPattern,
            std::regex::icase | std::regex::ECMAScript
        );
    } else {
        // Compile user-provided patterns
        for (const auto& pattern : patterns) {
            trigger_patterns_.emplace_back(
                pattern,
                std::regex::icase | std::regex::ECMAScript
            );
        }
    }
}

bool TriggerDetector::addressed_to_bot(
    const telegram::Message& message,
    const std::string& bot_username,
    std::int64_t bot_id
) const {
    const auto username = normalize_username(bot_username);

    // Check if message is a reply to the bot
    if (!username.empty() && message.reply_to_user.has_value()) {
        const auto& reply_user = message.reply_to_user.value();
        const auto reply_username = normalize_username(reply_user.username);

        if (reply_username == username || reply_user.id == bot_id) {
            return true;
        }
    }

    // Check for @mentions in message text
    if (!message.text.empty() && !message.entities.empty()) {
        if (matches_mention(message.text, message.entities, username, bot_id)) {
            return true;
        }
    }

    // Check for @mentions in media caption
    if (!message.caption.empty() && !message.caption_entities.empty()) {
        if (matches_mention(message.caption, message.caption_entities, username, bot_id)) {
            return true;
        }
    }

    // Check for keyword triggers in text
    if (!message.text.empty() && contains_keyword(message.text)) {
        return true;
    }

    // Check for keyword triggers in caption
    if (!message.caption.empty() && contains_keyword(message.caption)) {
        return true;
    }

    // In private chats (chat_id > 0), always respond
    if (message.chat.id > 0) {
        return true;
    }

    return false;
}

bool TriggerDetector::contains_keyword(const std::string& text) const {
    if (text.empty()) {
        return false;
    }

    // Check if any trigger pattern matches
    for (const auto& pattern : trigger_patterns_) {
        if (std::regex_search(text, pattern)) {
            return true;
        }
    }

    return false;
}

bool TriggerDetector::matches_mention(
    const std::string& text,
    const std::vector<telegram::MessageEntity>& entities,
    const std::string& username,
    std::int64_t bot_id
) const {
    if (text.empty() || entities.empty() || username.empty()) {
        return false;
    }

    for (const auto& entity : entities) {
        // Check text @mention (e.g., "@botname")
        if (entity.type == "mention") {
            // Extract the mentioned username from text
            if (entity.offset + entity.length <= text.size()) {
                const auto mention = text.substr(entity.offset, entity.length);
                const auto normalized_mention = normalize_username(mention);

                if (normalized_mention == username) {
                    return true;
                }
            }
        }

        // Check text_mention (clickable mention with user object)
        if (entity.type == "text_mention" && entity.user.has_value()) {
            const auto& mentioned_user = entity.user.value();

            // Check by user ID
            if (mentioned_user.id == bot_id) {
                return true;
            }

            // Check by username
            const auto mentioned_username = normalize_username(mentioned_user.username);
            if (!mentioned_username.empty() && mentioned_username == username) {
                return true;
            }
        }
    }

    return false;
}

std::string TriggerDetector::normalize_username(const std::string& username) {
    if (username.empty()) {
        return "";
    }

    // Remove @ prefix if present
    auto result = username;
    if (result[0] == '@') {
        result = result.substr(1);
    }

    // Convert to lowercase
    std::transform(result.begin(), result.end(), result.begin(),
                   [](unsigned char c) { return std::tolower(c); });

    return result;
}

}  // namespace gryag::services
