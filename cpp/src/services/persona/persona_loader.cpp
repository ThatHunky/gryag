#include "gryag/services/persona/persona_loader.hpp"

#include <fstream>

namespace gryag::services::persona {

namespace {

std::string read_all(const std::string& path) {
    if (path.empty()) {
        return {};
    }
    std::ifstream file(path);
    if (!file.good()) {
        return {};
    }
    return std::string((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
}

}  // namespace

PersonaLoader::PersonaLoader(std::string persona_path, std::string templates_path) {
    const auto persona_json = read_all(persona_path);
    if (!persona_json.empty()) {
        try {
            auto payload = nlohmann::json::parse(persona_json);
            persona_.system_prompt = payload.value("system_prompt", persona_.system_prompt);
            persona_.fallback_error = payload.value("error_fallback", persona_.fallback_error);
            persona_.empty_reply = payload.value("empty_reply", persona_.empty_reply);
        } catch (...) {
            // keep defaults
        }
    }

    const auto templates_json = read_all(templates_path);
    if (!templates_json.empty()) {
        try {
            auto payload = nlohmann::json::parse(templates_json);
            persona_.system_prompt = payload.value("system_prompt", persona_.system_prompt);
        } catch (...) {
        }
    }
}

}  // namespace gryag::services::persona
