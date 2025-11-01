#include "gryag/handlers/chat_handler.hpp"

#include "gryag/services/context/multi_level_context_manager.hpp"
#include "gryag/services/context_store.hpp"
#include "gryag/services/persona/persona_loader.hpp"
#include "gryag/services/background/episode_monitor.hpp"
#include "gryag/services/triggers.hpp"
#include "gryag/services/user_profile_store.hpp"

#include <spdlog/fmt/fmt.h>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <chrono>
#include <vector>

namespace gryag::handlers {

namespace {

constexpr const char* kRateLimitedMessage = "Занадто багато повідомлень. Спробуй трохи пізніше.";
constexpr const char* kProcessingBusyMessage = "Я ще обробляю твоє попереднє повідомлення. Повернися за мить.";
constexpr const char* kDefaultFallbackError = "Ґеміні знову тупить. Спробуй пізніше.";
constexpr const char* kDefaultEmptyReply = "Я не вкурив, що ти хочеш. Розпиши конкретніше.";

std::string to_role(const std::string& role) {
    if (role == "user") {
        return "user";
    }
    if (role == "model") {
        return "model";
    }
    if (role == "tool") {
        return "tool";
    }
    if (role == "system") {
        return "system";
    }
    // Default to model for any assistant-like roles
    return "model";
}

}  // namespace

namespace {

std::string escape_html(const std::string& input) {
    std::string output;
    output.reserve(input.size());
    for (char c : input) {
        switch (c) {
            case '&':
                output.append("&amp;");
                break;
            case '<':
                output.append("&lt;");
                break;
            case '>':
                output.append("&gt;");
                break;
            default:
                output.push_back(c);
                break;
        }
    }
    return output;
}

}  // namespace

ChatHandler::ChatHandler(HandlerContext& context) : ctx_(context) {}

void ChatHandler::handle_update(const telegram::Message& message, telegram::TelegramClient& client) {
    if (message.text.empty() || !message.from.has_value()) {
        return;
    }

    const auto chat_id = message.chat.id;
    const auto user_id = message.from->id;

    if (message.from->is_bot) {
        return;
    }

    if (is_banned(chat_id, user_id)) {
        return;
    }

    // Check if message is addressed to the bot
    if (ctx_.trigger_detector && !ctx_.trigger_detector->addressed_to_bot(
            message, ctx_.settings->bot_username, ctx_.settings->bot_id)) {
        // Message not addressed to bot - store for context only, don't respond
        services::MessageRecord record;
        record.chat_id = chat_id;
        record.user_id = user_id;
        record.role = "user";
        record.text = message.text;
        record.timestamp = std::chrono::system_clock::now();
        ctx_.context_store->insert_message(record);
        return;
    }

    if (!allow_rate(user_id)) {
        client.send_message(chat_id, kRateLimitedMessage, message.message_id);
        return;
    }

    // Process any attached media (photos, documents, audio, video)
    process_media_from_message(message, chat_id, user_id);

    const bool lock_acquired = acquire_processing_lock(chat_id, user_id);
    if (!lock_acquired) {
        client.send_message(chat_id, kProcessingBusyMessage, message.message_id);
        return;
    }

    struct LockGuard {
        ChatHandler& handler;
        std::int64_t chat_id;
        std::int64_t user_id;
        bool active;
        ~LockGuard() {
            if (active) {
                handler.release_processing_lock(chat_id, user_id);
            }
        }
    } guard{*this, chat_id, user_id, true};

    // Show typing indicator for better UX
    client.send_chat_action(chat_id, "typing");

    // Create or update user profile
    if (ctx_.profile_store && message.from.has_value()) {
        try {
            const auto& user = message.from.value();
            std::string display_name = user.first_name;
            ctx_.profile_store->get_or_create_profile(
                user_id, chat_id, display_name, user.username
            );
            // Increment interaction count
            ctx_.profile_store->update_interaction_count(user_id, chat_id);
        } catch (const std::exception& ex) {
            spdlog::warn("Failed to update profile for user {}: {}", user_id, ex.what());
        }
    }

    services::MessageRecord record;
    record.chat_id = chat_id;
    record.user_id = user_id;
    record.role = "user";
    record.text = message.text;
    record.timestamp = std::chrono::system_clock::now();
    if (message.thread_id) {
        record.thread_id = *message.thread_id;
    }

    try {
        record.id = ctx_.context_store->insert_message(record);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to persist message: {}", ex.what());
    }
    if (ctx_.episode_monitor) {
        ctx_.episode_monitor->track_message(record);
    }

    auto context_snippets = ctx_.multi_level_context->build_context(
        record.chat_id,
        4096,
        record.text
    );

    nlohmann::json conversation = nlohmann::json::array();
    for (const auto& snippet : context_snippets) {
        conversation.push_back({
            {"role", to_role(snippet.role)},
            {"parts", nlohmann::json::array({{{"text", snippet.content}}})}
        });
    }

    auto prompt = message.text;
    conversation.push_back({
        {"role", "user"},
        {"parts", nlohmann::json::array({{{"text", prompt}}})}
    });

    std::optional<std::string> system_prompt;
    if (ctx_.prompt_manager) {
        try {
            auto custom_prompt = ctx_.prompt_manager->active_prompt(message.chat.id);
            if (custom_prompt) {
                system_prompt = custom_prompt->prompt_text;
            }
        } catch (const std::exception& ex) {
            spdlog::warn("Failed to load custom prompt: {}", ex.what());
        }
    }
    if (!system_prompt && ctx_.persona_loader) {
        system_prompt = ctx_.persona_loader->persona().system_prompt;
    }

    const auto fallback_error = ctx_.persona_loader
        ? ctx_.persona_loader->persona().fallback_error
        : std::string{kDefaultFallbackError};
    const auto empty_reply = ctx_.persona_loader
        ? ctx_.persona_loader->persona().empty_reply
        : std::string{kDefaultEmptyReply};

    std::vector<nlohmann::json> tool_definitions;
    if (ctx_.tools) {
        tool_definitions = ctx_.tools->definition_payloads();
    }

    std::vector<services::MessageRecord> tool_records;
    nlohmann::json last_tool_output;
    std::string reply_text;

    try {
        constexpr int kMaxToolIterations = 3;
        for (int iteration = 0; iteration < kMaxToolIterations; ++iteration) {
            const auto response = ctx_.gemini->generate_text(
                conversation,
                system_prompt,
                tool_definitions
            );

            auto tool_call = next_tool_call(response);
            if (tool_call && ctx_.tools) {
                // Check feature-level rate limiting for this tool
                if (!allow_feature(user_id, tool_call->name)) {
                    spdlog::info("User {} throttled on tool '{}': feature rate limit exceeded",
                                user_id, tool_call->name);
                    // Record throttling in feature rate limiter
                    if (ctx_.feature_rate_limiter) {
                        // We don't record this as a successful usage since it was rejected
                    }
                    // Continue with next iteration instead of calling tool
                    continue;
                }

                services::tools::ToolContext tool_ctx;
                tool_ctx.state["chat_id"] = chat_id;
                if (record.thread_id) {
                    tool_ctx.state["thread_id"] = *record.thread_id;
                }
                tool_ctx.state["user_id"] = user_id;
                tool_ctx.state["message_text"] = record.text;

                nlohmann::json tool_output;
                try {
                    tool_output = ctx_.tools->call(tool_call->name, tool_call->args, tool_ctx);
                    // Record successful tool usage
                    if (ctx_.feature_rate_limiter) {
                        ctx_.feature_rate_limiter->record_usage(user_id, tool_call->name);
                    }
                } catch (const std::exception& tool_err) {
                    spdlog::error("Tool {} failed: {}", tool_call->name, tool_err.what());
                    tool_output = nlohmann::json{{"error", tool_err.what()}};
                }

                last_tool_output = tool_output;

                conversation.push_back(tool_call->assistant_content);

                nlohmann::json response_payload;
                if (tool_output.is_object()) {
                    response_payload = tool_output;
                } else if (tool_output.is_array()) {
                    response_payload["data"] = tool_output;
                } else if (tool_output.is_string()) {
                    response_payload["text"] = tool_output.get<std::string>();
                } else if (tool_output.is_null()) {
                    response_payload = nlohmann::json::object();
                } else {
                    response_payload["value"] = tool_output;
                }

                conversation.push_back({
                    {"role", "tool"},
                    {"parts", nlohmann::json::array({{
                        {"functionResponse", {
                            {"name", tool_call->name},
                            {"response", response_payload}
                        }}
                    }})}
                });

                services::MessageRecord tool_record = record;
                // Persist as 'model' to satisfy DB constraint; 'tool' is encoded in conversation only
                tool_record.role = "model";
                tool_record.user_id = 0;
                tool_record.timestamp = std::chrono::system_clock::now();
                if (tool_output.is_string()) {
                    tool_record.text = tool_output.get<std::string>();
                } else {
                    tool_record.text = tool_output.dump();
                }
                tool_records.push_back(tool_record);
                continue;
            }

            reply_text = response.text;
            if (reply_text.empty() && !last_tool_output.is_null()) {
                reply_text = last_tool_output.is_string()
                    ? last_tool_output.get<std::string>()
                    : last_tool_output.dump();
            }
            break;
        }

        if (reply_text.empty()) {
            reply_text = empty_reply;
        }
    } catch (const std::exception& ex) {
        spdlog::error("Gemini failed: {}", ex.what());
        reply_text = fallback_error;
    }

    reply_text = escape_html(reply_text);
    reply_text = format_response_text(reply_text);

    client.send_message(chat_id, reply_text, message.message_id);

    for (auto& tool_record : tool_records) {
        try {
            tool_record.id = ctx_.context_store->insert_message(tool_record);
            if (ctx_.episode_monitor) {
                ctx_.episode_monitor->track_message(tool_record);
            }
        } catch (const std::exception& ex) {
            spdlog::warn("Failed to persist tool message: {}", ex.what());
        }
    }

    services::MessageRecord assistant_record = record;
    // Persist assistant replies as 'model' per schema
    assistant_record.role = "model";
    assistant_record.user_id = 0;
    assistant_record.text = reply_text;

    try {
        assistant_record.id = ctx_.context_store->insert_message(assistant_record);
    } catch (const std::exception& ex) {
        spdlog::warn("Failed to persist assistant message: {}", ex.what());
    }
    if (ctx_.episode_monitor) {
        ctx_.episode_monitor->track_message(assistant_record);
    }
}

std::string ChatHandler::format_response_text(const std::string& text) {
    if (text.size() <= 4096) {
        return text;
    }
    std::string truncated = text.substr(0, 4093);
    const auto amp_pos = truncated.find_last_of('&');
    if (amp_pos != std::string::npos && amp_pos >= truncated.size() - 4) {
        if (truncated.find(';', amp_pos) == std::string::npos) {
            truncated.erase(amp_pos);
        }
    }
    truncated += "...";
    return truncated;
}

bool ChatHandler::acquire_processing_lock(std::int64_t chat_id, std::int64_t user_id) {
    if (!ctx_.redis || !ctx_.settings) {
        return true;
    }
    if (std::find(ctx_.settings->admin_user_ids.begin(),
                  ctx_.settings->admin_user_ids.end(),
                  static_cast<std::int64_t>(user_id)) != ctx_.settings->admin_user_ids.end()) {
        return true;
    }
    const auto key = fmt::format("gryag:lock:{}:{}", chat_id, user_id);
    return ctx_.redis->try_lock(key, std::chrono::seconds(10));
}

void ChatHandler::release_processing_lock(std::int64_t chat_id, std::int64_t user_id) {
    if (!ctx_.redis) {
        return;
    }
    const auto key = fmt::format("gryag:lock:{}:{}", chat_id, user_id);
    ctx_.redis->release_lock(key);
}

bool ChatHandler::is_banned(std::int64_t chat_id, std::int64_t user_id) {
    if (!ctx_.context_store) {
        return false;
    }
    try {
        return ctx_.context_store->is_banned(chat_id, user_id);
    } catch (const std::exception& ex) {
        spdlog::error("Failed to check ban status: {}", ex.what());
        return false;
    }
}

bool ChatHandler::allow_rate(std::int64_t user_id) {
    if (ctx_.redis) {
        const auto key = fmt::format("gryag:rate:{}", user_id);
        const auto ok = ctx_.redis->allow(
            key,
            static_cast<std::size_t>(ctx_.settings ? ctx_.settings->per_user_per_hour : 5),
            std::chrono::hours(1)
        );
        if (!ok) {
            return false;
        }
    }
    if (ctx_.rate_limiter) {
        return ctx_.rate_limiter->allow(user_id);
    }
    return true;
}

bool ChatHandler::allow_feature(std::int64_t user_id, const std::string& feature_name) {
    if (!ctx_.feature_rate_limiter) {
        return true;  // No rate limiting configured
    }

    std::vector<std::int64_t> admin_ids;
    if (ctx_.settings) {
        admin_ids = ctx_.settings->admin_user_ids;
    }

    return ctx_.feature_rate_limiter->allow_feature(user_id, feature_name, admin_ids);
}

std::optional<ToolInvocation> ChatHandler::next_tool_call(const services::gemini::GeminiResponse& response) const {
    try {
        if (!response.raw.contains("candidates")) {
            return std::nullopt;
        }
        const auto& candidates = response.raw.at("candidates");
        for (const auto& candidate : candidates) {
            if (!candidate.contains("content")) {
                continue;
            }
            const auto& parts = candidate["content"].value("parts", nlohmann::json::array());
            nlohmann::json assistant_content = {
                {"role", "assistant"},
                {"parts", parts}
            };
            for (const auto& part : parts) {
                if (!part.contains("functionCall")) {
                    continue;
                }
                const auto& call = part.at("functionCall");
                const auto name = call.value("name", std::string{});
                if (name.empty()) {
                    continue;
                }
                nlohmann::json args = nlohmann::json::object();
                if (call.contains("args")) {
                    args = call["args"];
                    if (args.is_string()) {
                        try {
                            args = nlohmann::json::parse(args.get<std::string>());
                        } catch (const std::exception& ex) {
                            spdlog::warn("Failed to parse tool args JSON: {}", ex.what());
                            args = nlohmann::json::object();
                        }
                    }
                }
                return ToolInvocation{.name = name, .args = args, .assistant_content = assistant_content};
            }
        }
    } catch (const std::exception& ex) {
        spdlog::error("Tool parsing failed: {}", ex.what());
    }
    return std::nullopt;
}

void ChatHandler::process_media_from_message(const telegram::Message& message,
                                             std::int64_t chat_id,
                                             std::int64_t user_id) {
    if (!ctx_.media_handler) {
        return;  // Media handling not configured
    }

    try {
        extract_and_store_media(message, chat_id, user_id);
    } catch (const std::exception& ex) {
        spdlog::warn("Failed to process media: {}", ex.what());
    }
}

void ChatHandler::extract_and_store_media(const telegram::Message& message,
                                          std::int64_t chat_id,
                                          std::int64_t user_id) {
    if (!ctx_.media_handler) {
        return;
    }

    const auto now = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();

    // Process photo (image)
    if (!message.photo.empty()) {
        const auto& photo = message.photo.back();  // Get highest resolution
        services::media::MediaHandler::MediaInfo media_info;
        media_info.file_id = photo.file_id;
        media_info.file_unique_id = photo.file_unique_id;
        media_info.type = services::media::MediaHandler::MediaType::Image;
        media_info.mime_type = "image/jpeg";
        media_info.filename = fmt::format("photo_{}.jpg", message.message_id);
        media_info.file_size_bytes = photo.file_size.value_or(0);
        media_info.message_id = message.message_id;
        media_info.user_id = user_id;
        media_info.chat_id = chat_id;
        media_info.timestamp = now;
        media_info.width = photo.width;
        media_info.height = photo.height;

        try {
            auto validation = ctx_.media_handler->validate_media(media_info);
            if (validation.is_valid) {
                ctx_.media_handler->store_media(media_info);
                spdlog::debug("Stored photo media: user_id={}, chat_id={}, file_id={}",
                             user_id, chat_id, photo.file_id);
            } else {
                spdlog::warn("Photo validation failed: {}", validation.error_message);
            }
        } catch (const std::exception& ex) {
            spdlog::error("Failed to store photo: {}", ex.what());
        }
    }

    // Process document
    if (message.document) {
        services::media::MediaHandler::MediaInfo media_info;
        media_info.file_id = message.document->file_id;
        media_info.file_unique_id = message.document->file_unique_id;
        media_info.type = services::media::MediaHandler::MediaType::Document;
        media_info.mime_type = message.document->mime_type.value_or("application/octet-stream");
        media_info.filename = message.document->file_name.value_or(
            fmt::format("document_{}", message.message_id));
        media_info.file_size_bytes = message.document->file_size.value_or(0);
        media_info.message_id = message.message_id;
        media_info.user_id = user_id;
        media_info.chat_id = chat_id;
        media_info.timestamp = now;

        try {
            auto validation = ctx_.media_handler->validate_media(media_info);
            if (validation.is_valid) {
                ctx_.media_handler->store_media(media_info);
                spdlog::debug("Stored document media: user_id={}, chat_id={}, filename={}",
                             user_id, chat_id, media_info.filename);
            } else {
                spdlog::warn("Document validation failed: {}", validation.error_message);
            }
        } catch (const std::exception& ex) {
            spdlog::error("Failed to store document: {}", ex.what());
        }
    }

    // Process audio
    if (message.audio) {
        services::media::MediaHandler::MediaInfo media_info;
        media_info.file_id = message.audio->file_id;
        media_info.file_unique_id = message.audio->file_unique_id;
        media_info.type = services::media::MediaHandler::MediaType::Audio;
        media_info.mime_type = message.audio->mime_type.value_or("audio/mpeg");
        media_info.filename = message.audio->file_name.value_or(
            fmt::format("audio_{}.mp3", message.message_id));
        media_info.file_size_bytes = message.audio->file_size.value_or(0);
        media_info.message_id = message.message_id;
        media_info.user_id = user_id;
        media_info.chat_id = chat_id;
        media_info.timestamp = now;
        media_info.duration_seconds = message.audio->duration;

        try {
            auto validation = ctx_.media_handler->validate_media(media_info);
            if (validation.is_valid) {
                ctx_.media_handler->store_media(media_info);
                spdlog::debug("Stored audio media: user_id={}, chat_id={}, duration={}",
                             user_id, chat_id, media_info.duration_seconds.value_or(0));
            } else {
                spdlog::warn("Audio validation failed: {}", validation.error_message);
            }
        } catch (const std::exception& ex) {
            spdlog::error("Failed to store audio: {}", ex.what());
        }
    }

    // Process video
    if (message.video) {
        services::media::MediaHandler::MediaInfo media_info;
        media_info.file_id = message.video->file_id;
        media_info.file_unique_id = message.video->file_unique_id;
        media_info.type = services::media::MediaHandler::MediaType::Video;
        media_info.mime_type = message.video->mime_type.value_or("video/mp4");
        media_info.filename = message.video->file_name.value_or(
            fmt::format("video_{}.mp4", message.message_id));
        media_info.file_size_bytes = message.video->file_size.value_or(0);
        media_info.message_id = message.message_id;
        media_info.user_id = user_id;
        media_info.chat_id = chat_id;
        media_info.timestamp = now;
        media_info.duration_seconds = message.video->duration;
        media_info.width = message.video->width;
        media_info.height = message.video->height;

        try {
            auto validation = ctx_.media_handler->validate_media(media_info);
            if (validation.is_valid) {
                ctx_.media_handler->store_media(media_info);
                spdlog::debug("Stored video media: user_id={}, chat_id={}, dimensions={}x{}",
                             user_id, chat_id,
                             media_info.width.value_or(0),
                             media_info.height.value_or(0));
            } else {
                spdlog::warn("Video validation failed: {}", validation.error_message);
            }
        } catch (const std::exception& ex) {
            spdlog::error("Failed to store video: {}", ex.what());
        }
    }
}

}  // namespace gryag::handlers
