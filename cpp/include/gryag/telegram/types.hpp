#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace gryag::telegram {

struct User {
    std::int64_t id = 0;
    bool is_bot = false;
    std::string first_name;
    std::string username;
};

struct Chat {
    std::int64_t id = 0;
    std::string type;
};

// Media types for storing file information
struct PhotoSize {
    std::string file_id;
    std::string file_unique_id;
    std::int32_t width = 0;
    std::int32_t height = 0;
    std::optional<std::int32_t> file_size;
};

struct Document {
    std::string file_id;
    std::string file_unique_id;
    std::optional<std::string> mime_type;
    std::optional<std::int32_t> file_size;
    std::optional<std::string> file_name;
};

struct Audio {
    std::string file_id;
    std::string file_unique_id;
    std::int32_t duration = 0;
    std::optional<std::string> mime_type;
    std::optional<std::int32_t> file_size;
    std::optional<std::string> file_name;
};

struct Video {
    std::string file_id;
    std::string file_unique_id;
    std::int32_t width = 0;
    std::int32_t height = 0;
    std::int32_t duration = 0;
    std::optional<std::string> mime_type;
    std::optional<std::int32_t> file_size;
    std::optional<std::string> file_name;
};

// Forward declaration for MessageEntity (needs User)
struct MessageEntity {
    std::string type;  // "mention", "text_mention", "hashtag", "url", etc.
    std::int32_t offset = 0;
    std::int32_t length = 0;
    std::optional<User> user;  // For text_mention type
};

struct Message {
    std::int64_t update_id = 0;
    std::int64_t message_id = 0;
    Chat chat;
    std::optional<User> from;
    std::optional<std::int64_t> thread_id;
    std::optional<std::int64_t> reply_to_message_id;
    std::optional<User> reply_to_user;
    std::string text;
    std::string caption;  // Caption for media messages
    std::vector<MessageEntity> entities;  // Entities in text (mentions, links, etc.)
    std::vector<MessageEntity> caption_entities;  // Entities in caption

    // Media fields
    std::vector<PhotoSize> photo;  // Can have multiple resolutions
    std::optional<Document> document;
    std::optional<Audio> audio;
    std::optional<Video> video;
};

/**
 * CallbackQuery - Represents an incoming callback query from an inline button
 */
struct CallbackQuery {
    std::int64_t update_id = 0;
    std::string id;  // Unique identifier for this query
    User from;  // User who pressed the button
    std::optional<Message> message;  // Message with the button (if available)
    std::optional<std::string> inline_message_id;  // For inline messages
    std::string chat_instance;
    std::string data;  // Data associated with the callback button (the important part!)
};

}  // namespace gryag::telegram
