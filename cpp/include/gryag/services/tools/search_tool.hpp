#pragma once

#include "gryag/services/tools/tool.hpp"

#include <nlohmann/json.hpp>

#include <string>

namespace gryag::services::tools {

class DuckDuckGoSearch {
public:
    DuckDuckGoSearch() = default;

    nlohmann::json search(const std::string& query,
                          const std::string& type,
                          int max_results);

private:
    static std::string fetch_vqd(const std::string& query);
    static nlohmann::json search_text(const std::string& query, int max_results);
    static nlohmann::json search_collection(const std::string& endpoint,
                                            const std::string& query,
                                            const std::string& vqd,
                                            int max_results);
};

void register_search_tool(ToolRegistry& registry, bool enabled);

}  // namespace gryag::services::tools
