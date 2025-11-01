#include "gryag/telegram/client.hpp"

#include <cpr/cpr.h>
#include <spdlog/fmt/fmt.h>
#include <spdlog/spdlog.h>
#include <nlohmann/json.hpp>

#include <chrono>

namespace gryag::telegram {

namespace {

std::optional<User> parse_user(const nlohmann::json& json) {
    if (!json.is_object() || !json.contains("id")) {
        return std::nullopt;
    }
    User user;
    user.id = json.value("id", 0LL);
    user.is_bot = json.value("is_bot", false);
    user.first_name = json.value("first_name", std::string{});
    user.username = json.value("username", std::string{});
    return user;
}

std::optional<std::int64_t> parse_optional_int(const nlohmann::json& json, const char* key) {
    if (!json.contains(key)) {
        return std::nullopt;
    }
    const auto& value = json.at(key);
    if (value.is_number_integer()) {
        return value.get<std::int64_t>();
    }
    return std::nullopt;
}

void parse_photo(const nlohmann::json& message_json, std::vector<PhotoSize>& photo) {
    if (!message_json.contains("photo") || !message_json.at("photo").is_array()) {
        return;
    }
    for (const auto& photo_size : message_json.at("photo")) {
        PhotoSize ps;
        ps.file_id = photo_size.value("file_id", std::string{});
        ps.file_unique_id = photo_size.value("file_unique_id", std::string{});
        ps.width = photo_size.value("width", 0);
        ps.height = photo_size.value("height", 0);
        if (photo_size.contains("file_size") && photo_size.at("file_size").is_number_integer()) {
            ps.file_size = photo_size.value("file_size", 0);
        }
        if (!ps.file_id.empty()) {
            photo.push_back(ps);
        }
    }
}

void parse_document(const nlohmann::json& message_json, std::optional<Document>& document) {
    if (!message_json.contains("document") || !message_json.at("document").is_object()) {
        return;
    }
    const auto& doc_json = message_json.at("document");
    Document doc;
    doc.file_id = doc_json.value("file_id", std::string{});
    doc.file_unique_id = doc_json.value("file_unique_id", std::string{});
    if (doc_json.contains("mime_type")) {
        doc.mime_type = doc_json.value("mime_type", std::string{});
    }
    if (doc_json.contains("file_name")) {
        doc.file_name = doc_json.value("file_name", std::string{});
    }
    if (doc_json.contains("file_size") && doc_json.at("file_size").is_number_integer()) {
        doc.file_size = doc_json.value("file_size", 0);
    }
    if (!doc.file_id.empty()) {
        document = doc;
    }
}

void parse_audio(const nlohmann::json& message_json, std::optional<Audio>& audio) {
    if (!message_json.contains("audio") || !message_json.at("audio").is_object()) {
        return;
    }
    const auto& audio_json = message_json.at("audio");
    Audio aud;
    aud.file_id = audio_json.value("file_id", std::string{});
    aud.file_unique_id = audio_json.value("file_unique_id", std::string{});
    aud.duration = audio_json.value("duration", 0);
    if (audio_json.contains("mime_type")) {
        aud.mime_type = audio_json.value("mime_type", std::string{});
    }
    if (audio_json.contains("file_name")) {
        aud.file_name = audio_json.value("file_name", std::string{});
    }
    if (audio_json.contains("file_size") && audio_json.at("file_size").is_number_integer()) {
        aud.file_size = audio_json.value("file_size", 0);
    }
    if (!aud.file_id.empty()) {
        audio = aud;
    }
}

void parse_entities(const nlohmann::json& entities_json, std::vector<MessageEntity>& entities) {
    if (!entities_json.is_array()) {
        return;
    }
    for (const auto& entity_json : entities_json) {
        MessageEntity entity;
        entity.type = entity_json.value("type", std::string{});
        entity.offset = entity_json.value("offset", 0);
        entity.length = entity_json.value("length", 0);

        // Parse user for text_mention type
        if (entity_json.contains("user")) {
            entity.user = parse_user(entity_json.at("user"));
        }

        entities.push_back(entity);
    }
}

void parse_video(const nlohmann::json& message_json, std::optional<Video>& video) {
    if (!message_json.contains("video") || !message_json.at("video").is_object()) {
        return;
    }
    const auto& video_json = message_json.at("video");
    Video vid;
    vid.file_id = video_json.value("file_id", std::string{});
    vid.file_unique_id = video_json.value("file_unique_id", std::string{});
    vid.width = video_json.value("width", 0);
    vid.height = video_json.value("height", 0);
    vid.duration = video_json.value("duration", 0);
    if (video_json.contains("mime_type")) {
        vid.mime_type = video_json.value("mime_type", std::string{});
    }
    if (video_json.contains("file_name")) {
        vid.file_name = video_json.value("file_name", std::string{});
    }
    if (video_json.contains("file_size") && video_json.at("file_size").is_number_integer()) {
        vid.file_size = video_json.value("file_size", 0);
    }
    if (!vid.file_id.empty()) {
        video = vid;
    }
}

}  // namespace

TelegramClient::TelegramClient(std::string token)
    : base_url_(fmt::format("https://api.telegram.org/bot{}", std::move(token))) {}

void TelegramClient::set_commands(const std::vector<std::pair<std::string, std::string>>& commands) {
    nlohmann::json payload = nlohmann::json::array();
    for (const auto& [command, description] : commands) {
        payload.push_back({{"command", command}, {"description", description}});
    }

    auto response = cpr::Post(
        cpr::Url{base_url_ + "/setMyCommands"},
        cpr::Body{nlohmann::json{{"commands", payload}}.dump()},
        cpr::Header{{"Content-Type", "application/json"}}
    );

    if (response.error) {
        spdlog::warn("Failed to set commands: {}", response.error.message);
    }
}

void TelegramClient::send_message(std::int64_t chat_id,
                                  const std::string& text,
                                  std::optional<std::int64_t> reply_to_message_id) {
    cpr::Payload payload{{"chat_id", std::to_string(chat_id)},
                         {"text", text},
                         {"parse_mode", "HTML"}};
    if (reply_to_message_id) {
        payload.Add({"reply_to_message_id", std::to_string(*reply_to_message_id)});
    }

    auto response = cpr::Post(cpr::Url{base_url_ + "/sendMessage"}, payload);
    if (response.error || response.status_code >= 400) {
        spdlog::warn("Failed to send message: status={} error={}", response.status_code, response.error.message);
    }
}

std::vector<Message> TelegramClient::poll(std::chrono::seconds timeout) {
    auto response = cpr::Get(
        cpr::Url{base_url_ + "/getUpdates"},
        cpr::Parameters{{"timeout", std::to_string(timeout.count())},
                        {"offset", std::to_string(last_update_id_ + 1)},
                        {"allowed_updates", "[\"message\",\"channel_post\"]"}}
    );

    std::vector<Message> messages;

    if (response.error) {
        spdlog::error("Telegram getUpdates error: {}", response.error.message);
        return messages;
    }

    try {
        const auto payload = nlohmann::json::parse(response.text);
        if (!payload.value("ok", false)) {
            spdlog::warn("Telegram getUpdates returned ok=false");
            return messages;
        }
        for (const auto& update : payload.value("result", nlohmann::json::array())) {
            const auto update_id = update.value("update_id", 0LL);
            if (update.contains("message")) {
                const auto& message_json = update.at("message");
                if (!message_json.contains("chat")) {
                    continue;
                }

                Message message;
                message.update_id = update_id;
                message.message_id = message_json.value("message_id", 0LL);
                message.chat.id = message_json.at("chat").value("id", 0LL);
                message.chat.type = message_json.at("chat").value("type", std::string{});
                message.thread_id = parse_optional_int(message_json, "message_thread_id");
                message.from = parse_user(message_json.value("from", nlohmann::json::object()));
                message.reply_to_message_id = std::nullopt;
                message.reply_to_user = std::nullopt;
                if (message_json.contains("reply_to_message")) {
                    const auto& reply_json = message_json.at("reply_to_message");
                    message.reply_to_message_id = reply_json.value("message_id", 0LL);
                    message.reply_to_user = parse_user(reply_json.value("from", nlohmann::json::object()));
                }
                message.text = message_json.value("text", std::string{});
                message.caption = message_json.value("caption", std::string{});

                // Parse entities
                if (message_json.contains("entities")) {
                    parse_entities(message_json.at("entities"), message.entities);
                }
                if (message_json.contains("caption_entities")) {
                    parse_entities(message_json.at("caption_entities"), message.caption_entities);
                }

                // Parse media
                parse_photo(message_json, message.photo);
                parse_document(message_json, message.document);
                parse_audio(message_json, message.audio);
                parse_video(message_json, message.video);

                // Include message if it has text or media
                if (!message.text.empty() || !message.photo.empty() ||
                    message.document.has_value() || message.audio.has_value() ||
                    message.video.has_value()) {
                    messages.push_back(std::move(message));
                }
            }

            if (update_id > last_update_id_) {
                last_update_id_ = update_id;
            }
        }
    } catch (const std::exception& ex) {
        spdlog::error("Failed to parse Telegram update: {}", ex.what());
    }

    return messages;
}

User TelegramClient::get_me() {
    const auto url = base_url_ + "/getMe";
    const auto response = cpr::Get(cpr::Url{url});

    if (response.status_code != 200) {
        throw std::runtime_error(fmt::format(
            "Failed to get bot info: HTTP {}", response.status_code
        ));
    }

    try {
        const auto payload = nlohmann::json::parse(response.text);
        if (!payload.value("ok", false)) {
            throw std::runtime_error("Telegram getMe returned ok=false");
        }

        const auto& result = payload.at("result");
        User bot;
        bot.id = result.value("id", 0LL);
        bot.is_bot = result.value("is_bot", false);
        bot.first_name = result.value("first_name", std::string{});
        bot.username = result.value("username", std::string{});

        spdlog::info("Bot identity fetched: @{} (ID: {})", bot.username, bot.id);
        return bot;
    } catch (const std::exception& ex) {
        throw std::runtime_error(fmt::format(
            "Failed to parse getMe response: {}", ex.what()
        ));
    }
}

void TelegramClient::answer_callback_query(const std::string& callback_query_id,
                                           const std::string& text,
                                           bool show_alert) {
    nlohmann::json payload = {
        {"callback_query_id", callback_query_id}
    };

    if (!text.empty()) {
        payload["text"] = text;
    }

    if (show_alert) {
        payload["show_alert"] = true;
    }

    auto response = cpr::Post(
        cpr::Url{base_url_ + "/answerCallbackQuery"},
        cpr::Body{payload.dump()},
        cpr::Header{{"Content-Type", "application/json"}}
    );

    if (response.error || response.status_code >= 400) {
        spdlog::warn("Failed to answer callback query: status={} error={}",
                    response.status_code, response.error.message);
    }
}

void TelegramClient::send_chat_action(std::int64_t chat_id, const std::string& action) {
    auto response = cpr::Post(
        cpr::Url{base_url_ + "/sendChatAction"},
        cpr::Payload{
            {"chat_id", std::to_string(chat_id)},
            {"action", action}
        }
    );

    if (response.error || response.status_code >= 400) {
        spdlog::debug("Failed to send chat action: status={} error={}",
                     response.status_code, response.error.message);
    }
}

TelegramClient::Update TelegramClient::poll_updates(std::chrono::seconds timeout) {
    auto response = cpr::Get(
        cpr::Url{base_url_ + "/getUpdates"},
        cpr::Parameters{{"timeout", std::to_string(timeout.count())},
                        {"offset", std::to_string(last_update_id_ + 1)},
                        {"allowed_updates", "[\"message\",\"channel_post\",\"callback_query\"]"}}
    );

    Update update;

    if (response.error) {
        spdlog::error("Telegram getUpdates error: {}", response.error.message);
        return update;
    }

    try {
        const auto payload = nlohmann::json::parse(response.text);
        if (!payload.value("ok", false)) {
            spdlog::warn("Telegram getUpdates returned ok=false");
            return update;
        }

        for (const auto& update_json : payload.value("result", nlohmann::json::array())) {
            const auto update_id = update_json.value("update_id", 0LL);

            // Parse message updates
            if (update_json.contains("message")) {
                const auto& message_json = update_json.at("message");
                if (!message_json.contains("chat")) {
                    continue;
                }

                Message message;
                message.update_id = update_id;
                message.message_id = message_json.value("message_id", 0LL);
                message.chat.id = message_json.at("chat").value("id", 0LL);
                message.chat.type = message_json.at("chat").value("type", std::string{});
                message.thread_id = parse_optional_int(message_json, "message_thread_id");
                message.from = parse_user(message_json.value("from", nlohmann::json::object()));
                message.reply_to_message_id = std::nullopt;
                message.reply_to_user = std::nullopt;
                if (message_json.contains("reply_to_message")) {
                    const auto& reply_json = message_json.at("reply_to_message");
                    message.reply_to_message_id = reply_json.value("message_id", 0LL);
                    message.reply_to_user = parse_user(reply_json.value("from", nlohmann::json::object()));
                }
                message.text = message_json.value("text", std::string{});
                message.caption = message_json.value("caption", std::string{});

                // Parse entities
                if (message_json.contains("entities")) {
                    parse_entities(message_json.at("entities"), message.entities);
                }
                if (message_json.contains("caption_entities")) {
                    parse_entities(message_json.at("caption_entities"), message.caption_entities);
                }

                // Parse media
                parse_photo(message_json, message.photo);
                parse_document(message_json, message.document);
                parse_audio(message_json, message.audio);
                parse_video(message_json, message.video);

                // Include message if it has text or media
                if (!message.text.empty() || !message.photo.empty() ||
                    message.document.has_value() || message.audio.has_value() ||
                    message.video.has_value()) {
                    update.messages.push_back(std::move(message));
                }
            }

            // Parse callback query updates
            if (update_json.contains("callback_query")) {
                const auto& cq_json = update_json.at("callback_query");

                CallbackQuery cq;
                cq.update_id = update_id;
                cq.id = cq_json.value("id", std::string{});
                cq.chat_instance = cq_json.value("chat_instance", std::string{});
                cq.data = cq_json.value("data", std::string{});

                // Parse from user
                if (cq_json.contains("from")) {
                    auto from_user = parse_user(cq_json.at("from"));
                    if (from_user.has_value()) {
                        cq.from = from_user.value();
                    }
                }

                // Parse message (if present)
                if (cq_json.contains("message")) {
                    const auto& msg_json = cq_json.at("message");
                    Message msg;
                    msg.message_id = msg_json.value("message_id", 0LL);
                    if (msg_json.contains("chat")) {
                        msg.chat.id = msg_json.at("chat").value("id", 0LL);
                        msg.chat.type = msg_json.at("chat").value("type", std::string{});
                    }
                    msg.from = parse_user(msg_json.value("from", nlohmann::json::object()));
                    msg.text = msg_json.value("text", std::string{});
                    cq.message = msg;
                }

                if (cq_json.contains("inline_message_id")) {
                    cq.inline_message_id = cq_json.value("inline_message_id", std::string{});
                }

                update.callback_queries.push_back(std::move(cq));
            }

            if (update_id > last_update_id_) {
                last_update_id_ = update_id;
            }
        }
    } catch (const std::exception& ex) {
        spdlog::error("Failed to parse Telegram update: {}", ex.what());
    }

    return update;
}

}  // namespace gryag::telegram
