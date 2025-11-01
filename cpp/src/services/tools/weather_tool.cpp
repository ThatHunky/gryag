#include "gryag/services/tools/weather_tool.hpp"

#include <cpr/cpr.h>
#include <spdlog/fmt/fmt.h>
#include <spdlog/spdlog.h>

#include <chrono>
#include <cmath>

namespace gryag::services::tools {

WeatherService::WeatherService(std::string api_key, std::string base_url)
    : api_key_(std::move(api_key)), base_url_(std::move(base_url)) {}

nlohmann::json WeatherService::perform_request(const std::string& endpoint,
                                               const nlohmann::json& params) const {
    cpr::Parameters query;
    query.Add({"appid", api_key_});
    query.Add({"units", "metric"});
    query.Add({"lang", "uk"});

    for (auto it = params.begin(); it != params.end(); ++it) {
        std::string value;
        if (it->is_string()) {
            value = it->get<std::string>();
        } else if (it->is_number_integer()) {
            value = std::to_string(it->get<long long>());
        } else if (it->is_number_float()) {
            value = fmt::format("{}", it->get<double>());
        } else if (it->is_boolean()) {
            value = it->get<bool>() ? "true" : "false";
        } else {
            value = it->dump();
        }
        query.Add({it.key(), value});
    }

    auto response = cpr::Get(
        cpr::Url{fmt::format("{}/{}", base_url_, endpoint)},
        query,
        cpr::Timeout{10000}
    );

    if (response.error.code != cpr::ErrorCode::OK) {
        throw std::runtime_error("Weather API request failed: " + response.error.message);
    }

    if (response.status_code == 404) {
        throw std::runtime_error("Не вдалося знайти місто");
    } else if (response.status_code == 401) {
        throw std::runtime_error("Невірний ключ API погоди");
    } else if (response.status_code == 429) {
        throw std::runtime_error("Перевищено ліміт запитів погоди");
    } else if (response.status_code != 200) {
        throw std::runtime_error("Помилка отримання даних погоди");
    }

    return nlohmann::json::parse(response.text);
}

nlohmann::json WeatherService::format_current_weather(const nlohmann::json& data) {
    nlohmann::json result;
    result["location"] = fmt::format(
        "{}, {}",
        data.value("name", "Unknown"),
        data.value("sys", nlohmann::json{}).value("country", "XX")
    );
    const auto& main = data.value("main", nlohmann::json::object());
    const auto& wind = data.value("wind", nlohmann::json::object());
    const auto& weather_list = data.value("weather", nlohmann::json::array());
    if (!weather_list.empty()) {
        result["description"] = weather_list.front().value("description", "");
    }
    result["temperature"] = std::round(main.value("temp", 0.0));
    result["feels_like"] = std::round(main.value("feels_like", 0.0));
    result["humidity"] = main.value("humidity", 0);
    result["pressure"] = main.value("pressure", 0);
    result["wind_speed"] = static_cast<double>(wind.value("speed", 0.0));
    result["wind_direction"] = wind.value("deg", 0);
    result["type"] = "current";
    return result;
}

nlohmann::json WeatherService::format_forecast(const nlohmann::json& data, int days) {
    nlohmann::json result;
    result["location"] = data.value("city", nlohmann::json::object()).value("name", "");
    result["type"] = "forecast";
    result["days"] = days;
    nlohmann::json entries = nlohmann::json::array();

    const auto& list = data.value("list", nlohmann::json::array());
    for (const auto& entry : list) {
        nlohmann::json item;
        item["timestamp"] = entry.value("dt", 0);
        const auto& main = entry.value("main", nlohmann::json::object());
        const auto& weather = entry.value("weather", nlohmann::json::array());
        item["temperature"] = main.value("temp", 0.0);
        if (!weather.empty()) {
            item["description"] = weather.front().value("description", "");
        }
        entries.push_back(item);
    }

    result["entries"] = entries;
    return result;
}

nlohmann::json WeatherService::current_weather(const std::string& location) {
    auto payload = perform_request("weather", {{"q", location}});
    return format_current_weather(payload);
}

nlohmann::json WeatherService::forecast(const std::string& location, int days) {
    nlohmann::json params = {
        {"q", location},
        {"cnt", days * 8}
    };
    auto payload = perform_request("forecast", params);
    return format_forecast(payload, days);
}

void register_weather_tool(ToolRegistry& registry,
                           const std::string& api_key,
                           const std::string& base_url) {
    if (api_key.empty()) {
        spdlog::warn("Weather tool disabled: missing OPENWEATHER_API_KEY");
        return;
    }

    auto service = std::make_shared<WeatherService>(api_key, base_url);

    registry.register_tool(
        ToolDefinition{
            .name = "weather",
            .description = "Отримати поточну погоду або прогноз для міста",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"location", {
                        {"type", "string"},
                        {"description", "Назва міста або населеного пункту"}
                    }},
                    {"forecast_days", {
                        {"type", "integer"},
                        {"description", "Кількість днів прогнозу (1-5)"}
                    }}
                }},
                {"required", {"location"}}
            }
        },
        [service](const nlohmann::json& args, ToolContext&) {
            const auto location = args.value("location", "");
            if (location.empty()) {
                throw std::runtime_error("Потрібно вказати місто");
            }
            const int days = args.value("forecast_days", 0);
            if (days <= 0) {
                return service->current_weather(location);
            }
            const int clamped = std::max(1, std::min(days, 5));
            return service->forecast(location, clamped);
        }
    );
}

}  // namespace gryag::services::tools
