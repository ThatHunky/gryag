#pragma once

#include "gryag/core/settings.hpp"

#include <cpr/cpr.h>
#include <nlohmann/json.hpp>

#include <chrono>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace gryag::services::gemini {

struct GeminiResponse {
    std::string text;
    nlohmann::json raw;
};

class GeminiClient {
public:
    explicit GeminiClient(const core::Settings& settings);

    virtual GeminiResponse generate_text(const nlohmann::json& contents,
                                         const std::optional<std::string>& system_prompt = std::nullopt,
                                         const std::vector<nlohmann::json>& tools = {});

    virtual std::vector<float> embed_text(const std::string& text);
    virtual std::vector<unsigned char> generate_image(const std::string& prompt,
                                                      const std::string& aspect_ratio = "1:1");

private:
    std::string pick_api_key();

    core::Settings settings_;
    mutable std::mutex key_mutex_;
    std::size_t next_key_index_ = 0;
    std::chrono::system_clock::time_point quota_block_until_{};
};

}  // namespace gryag::services::gemini
