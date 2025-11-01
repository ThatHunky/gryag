#include "gryag/services/tools/search_tool.hpp"

#include <cpr/cpr.h>
#include <spdlog/fmt/fmt.h>
#include <spdlog/spdlog.h>

#include <regex>

namespace gryag::services::tools {

std::string DuckDuckGoSearch::fetch_vqd(const std::string& query) {
    auto response = cpr::Get(
        cpr::Url{"https://duckduckgo.com/"},
        cpr::Parameters{{"q", query}},
        cpr::Header{{"User-Agent", "gryag-bot/1.0"}}
    );

    if (response.error.code != cpr::ErrorCode::OK) {
        throw std::runtime_error("DuckDuckGo token request failed");
    }

    std::regex pattern("vqd=\\\"([0-9-]+)\\\"");
    std::smatch match;
    if (std::regex_search(response.text, match, pattern) && match.size() > 1) {
        return match[1].str();
    }

    throw std::runtime_error("Не вдалося отримати токен пошуку");
}

nlohmann::json DuckDuckGoSearch::search_text(const std::string& query, int max_results) {
    auto response = cpr::Get(
        cpr::Url{"https://duckduckgo.com/html/"},
        cpr::Parameters{{"q", query}, {"kl", "uk-ua"}},
        cpr::Header{{"User-Agent", "gryag-bot/1.0"}}
    );

    if (response.error.code != cpr::ErrorCode::OK) {
        throw std::runtime_error("Помилка пошуку DuckDuckGo");
    }

    std::regex link_regex("<a[^>]*class=\\\"result__a[^>]*href=\\\"([^\\\"]+)\\\"[^>]*>(.*?)</a>");
    std::sregex_iterator it(response.text.begin(), response.text.end(), link_regex);
    std::sregex_iterator end;

    nlohmann::json results = nlohmann::json::array();
    for (int count = 0; it != end && count < max_results; ++it, ++count) {
        const auto& match = *it;
        auto url = match[1].str();
        auto title = match[2].str();
        // remove HTML tags
        title = std::regex_replace(title, std::regex("<[^>]+>"), "");
        results.push_back({
            {"title", title},
            {"url", url}
        });
    }
    return results;
}

nlohmann::json DuckDuckGoSearch::search_collection(const std::string& endpoint,
                                                   const std::string& query,
                                                   const std::string& vqd,
                                                   int max_results) {
    auto response = cpr::Get(
        cpr::Url{fmt::format("https://duckduckgo.com/{}", endpoint)},
        cpr::Parameters{{"l", "uk-ua"}, {"o", "json"}, {"q", query}, {"vqd", vqd}},
        cpr::Header{{"User-Agent", "gryag-bot/1.0"}}
    );

    if (response.error.code != cpr::ErrorCode::OK) {
        throw std::runtime_error("DuckDuckGo search failed");
    }

    auto payload = nlohmann::json::parse(response.text);
    nlohmann::json results = nlohmann::json::array();
    if (!payload.contains("results")) {
        return results;
    }

    const auto& list = payload["results"];
    for (std::size_t i = 0; i < list.size() && static_cast<int>(i) < max_results; ++i) {
        results.push_back(list[i]);
    }
    return results;
}

nlohmann::json DuckDuckGoSearch::search(const std::string& query,
                                        const std::string& type,
                                        int max_results) {
    const int clamped = std::max(1, std::min(max_results, 10));
    if (type == "text") {
        return search_text(query, clamped);
    }

    const auto vqd = fetch_vqd(query);
    if (type == "images") {
        return search_collection("i.js", query, vqd, clamped);
    }
    if (type == "videos") {
        return search_collection("v.js", query, vqd, clamped);
    }
    if (type == "news") {
        return search_collection("news.js", query, vqd, clamped);
    }

    return nlohmann::json::array();
}

void register_search_tool(ToolRegistry& registry, bool enabled) {
    if (!enabled) {
        spdlog::info("Web search disabled via settings");
        return;
    }

    auto search = std::make_shared<DuckDuckGoSearch>();

    registry.register_tool(
        ToolDefinition{
            .name = "search_web",
            .description = "Пошук у вебі через DuckDuckGo (текст, зображення, відео, новини)",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"query", {
                        {"type", "string"},
                        {"description", "Пошуковий запит"}
                    }},
                    {"search_type", {
                        {"type", "string"},
                        {"description", "Тип пошуку"},
                        {"enum", {"text", "images", "videos", "news"}}
                    }},
                    {"max_results", {
                        {"type", "integer"},
                        {"description", "Кількість результатів (1-10)"}
                    }}
                }},
                {"required", {"query"}}
            }
        },
        [search](const nlohmann::json& args, ToolContext&) {
            const auto query = args.value("query", std::string{});
            if (query.empty()) {
                throw std::runtime_error("Порожній пошуковий запит");
            }
            const auto type = args.value("search_type", std::string{"text"});
            const int max_results = args.value("max_results", 5);
            auto results = search->search(query, type, max_results);
            return nlohmann::json{{"query", query},
                                  {"search_type", type},
                                  {"results", results},
                                  {"count", results.size()}};
        }
    );
}

}  // namespace gryag::services::tools
