#include "gryag/services/gemini/gemini_client.hpp"

#include <spdlog/spdlog.h>

#include <random>
#include <array>
#include <cctype>

namespace gryag::services::gemini {

namespace {
const std::string kGeminiBase = "https://generativelanguage.googleapis.com/v1beta";
const std::string kImageMime = "image/png";

std::string build_generate_url(const std::string& model) {
    return kGeminiBase + "/models/" + model + ":generateContent";
}

std::string build_embed_url(const std::string& model) {
    return kGeminiBase + "/models/" + model + ":embedContent";
}

std::vector<unsigned char> base64_decode(const std::string& input) {
    static const std::string chars =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789+/";

    std::vector<unsigned char> output;
    std::array<int, 256> table{};
    table.fill(-1);
    for (std::size_t i = 0; i < chars.size(); ++i) {
        table[static_cast<unsigned char>(chars[i])] = static_cast<int>(i);
    }

    std::size_t padding = 0;
    for (auto it = input.rbegin(); it != input.rend() && *it == '='; ++it) {
        ++padding;
    }

    output.reserve((input.size() * 3) / 4 - padding);
    std::uint32_t buffer = 0;
    int bits_collected = 0;
    for (unsigned char c : input) {
        if (std::isspace(c)) {
            continue;
        }
        if (c == '=') {
            break;
        }
        int value = table[c];
        if (value == -1) {
            continue;
        }
        buffer = (buffer << 6) | static_cast<std::uint32_t>(value);
        bits_collected += 6;
        if (bits_collected >= 8) {
            bits_collected -= 8;
            output.push_back(static_cast<unsigned char>((buffer >> bits_collected) & 0xFF));
        }
    }
    return output;
}

}  // namespace

GeminiClient::GeminiClient(const core::Settings& settings) : settings_(settings) {}

GeminiResponse GeminiClient::generate_text(const nlohmann::json& contents,
                                           const std::optional<std::string>& system_prompt,
                                           const std::vector<nlohmann::json>& tools) {
    const auto api_key = pick_api_key();

    nlohmann::json request;
    request["contents"] = contents;
    if (system_prompt && !system_prompt->empty()) {
        request["system_instruction"] = {
            {"parts", nlohmann::json::array({{{"text", *system_prompt}}})}
        };
    }

    if (!tools.empty()) {
        nlohmann::json tool_array = nlohmann::json::array();
        for (const auto& tool : tools) {
            tool_array.push_back(tool);
        }
        request["tools"] = std::move(tool_array);
    }

    const auto url = build_generate_url(settings_.gemini_model);
    auto response = cpr::Post(
        cpr::Url{url},
        cpr::Parameters{{"key", api_key}},
        cpr::Header{{"Content-Type", "application/json"}},
        cpr::Body{request.dump()}
    );

    if (response.error) {
        throw std::runtime_error("Gemini request failed: " + response.error.message);
    }

    if (response.status_code >= 400) {
        if (response.text.empty()) {
            throw std::runtime_error("Gemini HTTP error " + std::to_string(response.status_code) + ": empty body");
        }
        // Try to extract error message from JSON body
        try {
            auto err = nlohmann::json::parse(response.text);
            if (err.contains("error")) {
                const auto& e = err["error"];
                auto msg = e.value("message", std::string{"unknown error"});
                throw std::runtime_error("Gemini HTTP error " + std::to_string(response.status_code) + ": " + msg);
            }
        } catch (...) {
            // Fallthrough and throw generic error below
        }
        throw std::runtime_error("Gemini HTTP error " + std::to_string(response.status_code));
    }

    if (response.text.empty()) {
        throw std::runtime_error("Gemini returned empty response body");
    }

    auto payload = nlohmann::json::parse(response.text);
    GeminiResponse result;
    if (payload.contains("candidates") && !payload["candidates"].empty()) {
        const auto& content = payload["candidates"][0]["content"]["parts"][0];
        result.text = content.value("text", "");
    }
    result.raw = std::move(payload);

    spdlog::debug("Gemini respond with {} chars", result.text.size());
    return result;
}

std::vector<float> GeminiClient::embed_text(const std::string& text) {
    const auto api_key = pick_api_key();

    nlohmann::json request = {
        {"model", settings_.gemini_embed_model},
        {"content", {{"parts", {{{"text", text}}}}}}
    };

    const auto url = build_embed_url(settings_.gemini_embed_model);
    auto response = cpr::Post(
        cpr::Url{url},
        cpr::Parameters{{"key", api_key}},
        cpr::Header{{"Content-Type", "application/json"}},
        cpr::Body{request.dump()}
    );

    if (response.error) {
        throw std::runtime_error("Gemini embedding request failed: " + response.error.message);
    }
    if (response.status_code >= 400) {
        if (response.text.empty()) {
            throw std::runtime_error("Gemini embedding HTTP error " + std::to_string(response.status_code) + ": empty body");
        }
        try {
            auto err = nlohmann::json::parse(response.text);
            if (err.contains("error")) {
                const auto& e = err["error"];
                auto msg = e.value("message", std::string{"unknown error"});
                throw std::runtime_error("Gemini embedding HTTP error " + std::to_string(response.status_code) + ": " + msg);
            }
        } catch (...) {
            // ignore parse errors here and throw generic error
        }
        throw std::runtime_error("Gemini embedding HTTP error " + std::to_string(response.status_code));
    }
    if (response.text.empty()) {
        throw std::runtime_error("Gemini embedding returned empty response body");
    }

    const auto payload = nlohmann::json::parse(response.text);
    std::vector<float> embedding;
    if (payload.contains("embedding")) {
        for (const auto& value : payload["embedding"]["values"]) {
            embedding.push_back(value.get<float>());
        }
    }
    return embedding;
}

std::string GeminiClient::pick_api_key() {
    std::lock_guard lock(key_mutex_);
    if (!settings_.gemini_api_keys.empty()) {
        const auto key = settings_.gemini_api_keys[next_key_index_ % settings_.gemini_api_keys.size()];
        next_key_index_ = (next_key_index_ + 1) % settings_.gemini_api_keys.size();
        return key;
    }
    return settings_.gemini_api_key;
}

std::vector<unsigned char> GeminiClient::generate_image(const std::string& prompt,
                                                        const std::string& aspect_ratio) {
    std::string api_key = settings_.image_generation_api_key.empty()
        ? pick_api_key()
        : settings_.image_generation_api_key;

    nlohmann::json request = {
        {"contents", {{
             {"role", "user"},
             {"parts", {{{"text", prompt}}}}
         }}},
        {"generationConfig", {
             {"responseMimeType", kImageMime},
             {"aspectRatio", aspect_ratio}
         }}
    };

    const auto url = build_generate_url(settings_.gemini_model);
    auto response = cpr::Post(
        cpr::Url{url},
        cpr::Parameters{{"key", api_key}},
        cpr::Header{{"Content-Type", "application/json"}},
        cpr::Body{request.dump()}
    );

    if (response.error.code != cpr::ErrorCode::OK) {
        throw std::runtime_error("Gemini image request failed: " + response.error.message);
    }

    if (response.status_code >= 400) {
        throw std::runtime_error("Gemini image error: " + std::to_string(response.status_code));
    }

    auto payload = nlohmann::json::parse(response.text);
    if (!payload.contains("candidates") || payload["candidates"].empty()) {
        throw std::runtime_error("Gemini image response missing candidates");
    }

    const auto& parts = payload["candidates"][0]["content"]["parts"];
    if (parts.empty() || !parts[0].contains("inline_data")) {
        throw std::runtime_error("Gemini image response missing inline data");
    }
    const auto& inline_data = parts[0]["inline_data"];
    const auto data = inline_data.value("data", std::string{});
    if (data.empty()) {
        throw std::runtime_error("Gemini image response empty data");
    }
    return base64_decode(data);
}

}  // namespace gryag::services::gemini
