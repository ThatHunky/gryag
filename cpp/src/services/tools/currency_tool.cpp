#include "gryag/services/tools/currency_tool.hpp"

#include <cpr/cpr.h>
#include <spdlog/fmt/fmt.h>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <cctype>

namespace gryag::services::tools {

namespace {

std::string normalize_currency(std::string code) {
    std::transform(code.begin(), code.end(), code.begin(), [](unsigned char c) {
        return static_cast<char>(std::toupper(c));
    });
    return code;
}

}  // namespace

CurrencyService::CurrencyService(std::string api_key, std::string base_url)
    : api_key_(std::move(api_key)), base_url_(std::move(base_url)) {}

nlohmann::json CurrencyService::fetch_rates(const std::string& base_currency) {
    std::string url;
    if (api_key_.empty()) {
        url = fmt::format("{}/v6/latest/{}", base_url_, base_currency);
    } else {
        url = fmt::format("{}/v6/{}/latest/{}", base_url_, api_key_, base_currency);
    }

    auto response = cpr::Get(cpr::Url{url}, cpr::Timeout{10000});
    if (response.error.code != cpr::ErrorCode::OK) {
        throw std::runtime_error("Currency API request failed: " + response.error.message);
    }
    if (response.status_code == 404) {
        throw std::runtime_error("Валюта не підтримується");
    } else if (response.status_code == 401) {
        throw std::runtime_error("Невірний API ключ валют");
    } else if (response.status_code == 429) {
        throw std::runtime_error("Перевищено ліміт запитів валют");
    } else if (response.status_code != 200) {
        throw std::runtime_error("Помилка отримання курсу валют");
    }

    auto payload = nlohmann::json::parse(response.text);
    if (payload.value("result", "") == "error") {
        throw std::runtime_error(payload.value("error-type", "Помилка API курсу валют"));
    }

    return payload.value("conversion_rates", nlohmann::json::object());
}

nlohmann::json CurrencyService::latest_rates(const std::string& base_currency) {
    const auto normalized = normalize_currency(base_currency);
    const auto now = std::chrono::system_clock::now();

    {
        std::lock_guard lock(mutex_);
        auto it = cache_.find(normalized);
        if (it != cache_.end() && (now - it->second.timestamp) < cache_ttl_) {
            return it->second.rates;
        }
    }

    auto rates = fetch_rates(normalized);

    {
        std::lock_guard lock(mutex_);
        cache_[normalized] = CacheEntry{rates, now};
    }

    return rates;
}

nlohmann::json CurrencyService::convert(double amount,
                                        const std::string& from_currency,
                                        const std::string& to_currency) {
    if (amount <= 0) {
        throw std::runtime_error("Сума повинна бути більше нуля");
    }
    const auto from_norm = normalize_currency(from_currency);
    const auto to_norm = normalize_currency(to_currency);

    if (from_norm == to_norm) {
        return nlohmann::json{{"amount", amount},
                              {"from_currency", from_norm},
                              {"to_currency", to_norm},
                              {"exchange_rate", 1.0},
                              {"converted_amount", amount}};
    }

    auto rates = latest_rates(from_norm);
    if (!rates.contains(to_norm)) {
        throw std::runtime_error("Цільова валюта не підтримується");
    }
    const double rate = rates.value(to_norm, 0.0);
    return nlohmann::json{{"amount", amount},
                          {"from_currency", from_norm},
                          {"to_currency", to_norm},
                          {"exchange_rate", rate},
                          {"converted_amount", amount * rate}};
}

void register_currency_tool(ToolRegistry& registry,
                            const std::string& api_key,
                            const std::string& base_url) {
    auto service = std::make_shared<CurrencyService>(api_key, base_url);

    registry.register_tool(
        ToolDefinition{
            .name = "currency",
            .description = "Конвертація валют та перегляд актуальних курсів",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"action", {
                        {"type", "string"},
                        {"description", "Дія: 'convert' або 'rates'"},
                        {"enum", {"convert", "rates"}}
                    }},
                    {"amount", {
                        {"type", "number"},
                        {"description", "Сума для конвертації"}
                    }},
                    {"from_currency", {
                        {"type", "string"},
                        {"description", "Початкова валюта (наприклад, USD)"}
                    }},
                    {"to_currency", {
                        {"type", "string"},
                        {"description", "Цільова валюта (наприклад, UAH)"}
                    }},
                    {"base_currency", {
                        {"type", "string"},
                        {"description", "Базова валюта для списку курсів"}
                    }}
                }},
                {"required", {"action"}}
            }
        },
        [service](const nlohmann::json& args, ToolContext&) {
            const auto action = args.value("action", std::string{"convert"});
            if (action == "convert") {
                const double amount = args.value("amount", 0.0);
                const auto from_currency = args.value("from_currency", std::string{});
                const auto to_currency = args.value("to_currency", std::string{});
                if (from_currency.empty() || to_currency.empty()) {
                    throw std::runtime_error("Потрібно вказати коди валют");
                }
                return service->convert(amount, from_currency, to_currency);
            }
            const auto base_currency = args.value("base_currency", std::string{"USD"});
            auto rates = service->latest_rates(base_currency);
            return nlohmann::json{{"base_currency", normalize_currency(base_currency)},
                                  {"rates", rates}};
        }
    );
}

}  // namespace gryag::services::tools
