#pragma once

#include <nlohmann/json.hpp>

#include <optional>
#include <string>

namespace gryag::services::persona {

struct PersonaConfig {
    std::string system_prompt;
    std::string fallback_error = "Ґеміні знову тупить. Спробуй пізніше.";
    std::string empty_reply = "Я не вкурив, що ти хочеш. Розпиши конкретніше — і я вже кручусь.";
};

class PersonaLoader {
public:
    PersonaLoader(std::string persona_path, std::string templates_path);

    const PersonaConfig& persona() const { return persona_; }

private:
    PersonaConfig persona_;
};

}  // namespace gryag::services::persona
