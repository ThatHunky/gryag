#pragma once

#include <nlohmann/json.hpp>

#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

namespace gryag::services::tools {

struct ToolContext {
    nlohmann::json state = nlohmann::json::object();
};

struct ToolDefinition {
    std::string name;
    std::string description;
    nlohmann::json parameters = nlohmann::json::object();
};

using ToolCallback = std::function<nlohmann::json(const nlohmann::json& args, ToolContext& ctx)>;

class ToolRegistry {
public:
    void register_tool(ToolDefinition definition, ToolCallback callback);
    bool has_tool(const std::string& name) const;
    nlohmann::json call(const std::string& name, const nlohmann::json& args, ToolContext& ctx) const;
    std::vector<nlohmann::json> definition_payloads() const;

private:
    std::unordered_map<std::string, ToolDefinition> definitions_;
    std::unordered_map<std::string, ToolCallback> callbacks_;
    std::vector<std::string> registration_order_;
};

}  // namespace gryag::services::tools
