#include "gryag/services/tools/image_generation_tool.hpp"

#include <SQLiteCpp/Statement.h>
#include <spdlog/fmt/fmt.h>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <chrono>
#include <ctime>
#include <cstdint>

namespace gryag::services::tools {

namespace {

std::string today_utc() {
    auto now = std::chrono::system_clock::now();
    std::time_t tt = std::chrono::system_clock::to_time_t(now);
    std::tm tm = *gmtime(&tt);
    char buffer[16];
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%d", &tm);
    return std::string(buffer);
}

bool is_admin(std::int64_t user_id, const std::vector<std::int64_t>& admins) {
    return std::find(admins.begin(), admins.end(), user_id) != admins.end();
}

std::string base64_encode(const std::vector<unsigned char>& data) {
    static const char* chars =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789+/";
    std::string output;
    output.reserve(((data.size() + 2) / 3) * 4);
    for (std::size_t i = 0; i < data.size(); i += 3) {
        unsigned int octet_a = data[i];
        unsigned int octet_b = (i + 1 < data.size()) ? data[i + 1] : 0;
        unsigned int octet_c = (i + 2 < data.size()) ? data[i + 2] : 0;

        unsigned int triple = (octet_a << 16) | (octet_b << 8) | octet_c;

        output.push_back(chars[(triple >> 18) & 0x3F]);
        output.push_back(chars[(triple >> 12) & 0x3F]);
        output.push_back((i + 1 < data.size()) ? chars[(triple >> 6) & 0x3F] : '=');
        output.push_back((i + 2 < data.size()) ? chars[triple & 0x3F] : '=');
    }
    return output;
}

}  // namespace

ImageGenerationService::ImageGenerationService(services::gemini::GeminiClient& gemini,
                                               std::shared_ptr<infrastructure::SQLiteConnection> connection,
                                               int daily_limit,
                                               std::vector<std::int64_t> admin_user_ids)
    : gemini_(gemini),
      connection_(std::move(connection)),
      daily_limit_(daily_limit),
      admin_user_ids_(std::move(admin_user_ids)) {}

bool ImageGenerationService::has_quota(std::int64_t user_id,
                                       std::int64_t chat_id,
                                       int& used) {
    if (is_admin(user_id, admin_user_ids_)) {
        used = 0;
        return true;
    }

    SQLite::Statement stmt(
        connection_->db(),
        "SELECT images_generated FROM image_quotas WHERE user_id = ? AND chat_id = ? AND generation_date = ?"
    );
    stmt.bind(1, user_id);
    stmt.bind(2, chat_id);
    stmt.bind(3, today_utc());
    if (stmt.executeStep()) {
        used = stmt.getColumn(0).getInt();
        return used < daily_limit_;
    }
    used = 0;
    return true;
}

void ImageGenerationService::increment(std::int64_t user_id, std::int64_t chat_id) {
    if (is_admin(user_id, admin_user_ids_)) {
        return;
    }
    auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
    SQLite::Statement stmt(
        connection_->db(),
        "INSERT INTO image_quotas (user_id, chat_id, generation_date, images_generated, last_generation_ts) "
        "VALUES (?, ?, ?, 1, ?) "
        "ON CONFLICT(user_id, chat_id, generation_date) DO UPDATE SET "
        "images_generated = images_generated + 1, last_generation_ts = excluded.last_generation_ts"
    );
    stmt.bind(1, user_id);
    stmt.bind(2, chat_id);
    stmt.bind(3, today_utc());
    stmt.bind(4, static_cast<std::int64_t>(now));
    stmt.exec();
}

nlohmann::json ImageGenerationService::generate(const nlohmann::json& args) {
    const auto prompt = args.value("prompt", std::string{});
    if (prompt.empty()) {
        throw std::runtime_error("Порожній промпт для зображення");
    }
    const auto aspect_ratio = args.value("aspect_ratio", std::string{"1:1"});
    const auto user_id = args.value("user_id", 0LL);
    const auto chat_id = args.value("chat_id", 0LL);

    int used = 0;
    {
        std::lock_guard lock(mutex_);
        if (user_id != 0 && chat_id != 0 && !has_quota(user_id, chat_id, used)) {
            throw std::runtime_error(fmt::format(
                "Перевищено денний ліміт генерації зображень ({}/{})", used, daily_limit_));
        }
    }

    auto bytes = gemini_.generate_image(prompt, aspect_ratio);

    if (user_id != 0 && chat_id != 0) {
        std::lock_guard lock(mutex_);
        increment(user_id, chat_id);
    }

    const auto encoded = base64_encode(bytes);
    return nlohmann::json{{"image_base64", encoded},
                          {"mime_type", "image/png"},
                          {"prompt", prompt}};
}

void register_image_tools(ToolRegistry& registry,
                          services::gemini::GeminiClient& gemini,
                          std::shared_ptr<infrastructure::SQLiteConnection> connection,
                          int daily_limit,
                          const std::vector<std::int64_t>& admin_user_ids,
                          bool enabled) {
    if (!enabled) {
        spdlog::info("Image generation disabled via settings");
        return;
    }

    auto service = std::make_shared<ImageGenerationService>(gemini, connection, daily_limit, admin_user_ids);

    registry.register_tool(
        ToolDefinition{
            .name = "generate_image",
            .description = "Генерація зображень через Gemini",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"prompt", {
                        {"type", "string"},
                        {"description", "Опис зображення"}
                    }},
                    {"aspect_ratio", {
                        {"type", "string"},
                        {"description", "Співвідношення сторін (наприклад, 1:1, 16:9)"}
                    }},
                    {"user_id", {
                        {"type", "integer"},
                        {"description", "ID користувача (для квоти)"}
                    }},
                    {"chat_id", {
                        {"type", "integer"},
                        {"description", "ID чату (для квоти)"}
                    }}
                }},
                {"required", {"prompt"}}
            }
        },
        [service](const nlohmann::json& args, ToolContext&) {
            return service->generate(args);
        }
    );
}

}  // namespace gryag::services::tools
