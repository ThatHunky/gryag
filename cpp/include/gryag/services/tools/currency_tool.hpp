#pragma once

#include "gryag/services/tools/tool.hpp"

#include <nlohmann/json.hpp>

#include <chrono>
#include <mutex>
#include <string>
#include <unordered_map>

namespace gryag::services::tools {

class CurrencyService {
public:
    CurrencyService(std::string api_key, std::string base_url);

    nlohmann::json latest_rates(const std::string& base_currency);
    nlohmann::json convert(double amount,
                           const std::string& from_currency,
                           const std::string& to_currency);

private:
    struct CacheEntry {
        nlohmann::json rates;
        std::chrono::system_clock::time_point timestamp;
    };

    nlohmann::json fetch_rates(const std::string& base_currency);

    std::string api_key_;
    std::string base_url_;
    std::mutex mutex_;
    std::unordered_map<std::string, CacheEntry> cache_;
    std::chrono::seconds cache_ttl_{3600};
};

void register_currency_tool(ToolRegistry& registry,
                            const std::string& api_key,
                            const std::string& base_url);

}  // namespace gryag::services::tools
