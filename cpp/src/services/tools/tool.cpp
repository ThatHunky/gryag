#include "gryag/services/tools/tool.hpp"

#include <algorithm>
#include <stdexcept>

namespace gryag::services::tools {

void ToolRegistry::register_tool(ToolDefinition definition, ToolCallback callback) {
    const auto name = definition.name;
    callbacks_[name] = std::move(callback);
    definitions_[name] = std::move(definition);
    if (std::find(registration_order_.begin(), registration_order_.end(), name) == registration_order_.end()) {
        registration_order_.push_back(name);
    }
}

bool ToolRegistry::has_tool(const std::string& name) const {
    return callbacks_.find(name) != callbacks_.end();
}

nlohmann::json ToolRegistry::call(const std::string& name,
                                  const nlohmann::json& args,
                                  ToolContext& ctx) const {
    auto it = callbacks_.find(name);
    if (it == callbacks_.end()) {
        throw std::runtime_error("Tool not registered: " + name);
    }
    return it->second(args, ctx);
}

std::vector<nlohmann::json> ToolRegistry::definition_payloads() const {
    std::vector<nlohmann::json> defs;
    defs.reserve(registration_order_.size());
    for (const auto& name : registration_order_) {
        const auto& def = definitions_.at(name);
        nlohmann::json function = {
            {"name", def.name},
            {"description", def.description},
        };
        if (!def.parameters.is_null() && !def.parameters.empty()) {
            function["parameters"] = def.parameters;
        }
        defs.push_back({
            {"functionDeclarations", nlohmann::json::array({function})}
        });
    }
    return defs;
}

}  // namespace gryag::services::tools
