#pragma once

#include "gryag/services/tools/tool.hpp"

#include <nlohmann/json.hpp>

#include <string>

namespace gryag::services::tools {

class WeatherService {
public:
    WeatherService(std::string api_key, std::string base_url);

    nlohmann::json current_weather(const std::string& location);
    nlohmann::json forecast(const std::string& location, int days);

private:
    nlohmann::json perform_request(const std::string& endpoint,
                                   const nlohmann::json& params) const;
    static nlohmann::json format_current_weather(const nlohmann::json& payload);
    static nlohmann::json format_forecast(const nlohmann::json& payload, int days);

    std::string api_key_;
    std::string base_url_;
};

void register_weather_tool(ToolRegistry& registry,
                           const std::string& api_key,
                           const std::string& base_url);

}  // namespace gryag::services::tools
