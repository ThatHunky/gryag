#pragma once

#include "gryag/services/gemini/gemini_client.hpp"
#include "gryag/services/tools/tool.hpp"
#include "gryag/infrastructure/sqlite.hpp"

#include <mutex>
#include <vector>
#include <optional>

namespace gryag::services::tools {

class ImageGenerationService {
public:
    ImageGenerationService(services::gemini::GeminiClient& gemini,
                           std::shared_ptr<infrastructure::SQLiteConnection> connection,
                           int daily_limit,
                           std::vector<std::int64_t> admin_user_ids);

    nlohmann::json generate(const nlohmann::json& args);

private:
    bool has_quota(std::int64_t user_id, std::int64_t chat_id, int& used);
    void increment(std::int64_t user_id, std::int64_t chat_id);

    services::gemini::GeminiClient& gemini_;
    std::shared_ptr<infrastructure::SQLiteConnection> connection_;
    int daily_limit_;
    std::vector<std::int64_t> admin_user_ids_;
    std::mutex mutex_;
};

void register_image_tools(ToolRegistry& registry,
                          services::gemini::GeminiClient& gemini,
                          std::shared_ptr<infrastructure::SQLiteConnection> connection,
                          int daily_limit,
                          const std::vector<std::int64_t>& admin_user_ids,
                          bool enabled);

}  // namespace gryag::services::tools
