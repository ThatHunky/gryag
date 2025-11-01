#include "gryag/services/tools/default_tools.hpp"

#include "gryag/services/tools/calculator_tool.hpp"
#include "gryag/services/tools/weather_tool.hpp"
#include "gryag/services/tools/currency_tool.hpp"
#include "gryag/services/tools/polls_tool.hpp"
#include "gryag/services/tools/search_tool.hpp"
#include "gryag/services/tools/search_messages_tool.hpp"
#include "gryag/services/tools/image_generation_tool.hpp"
#include "gryag/services/tools/memory_tools.hpp"

#include <spdlog/spdlog.h>

namespace gryag::services::tools {

void register_default_tools(ToolRegistry& registry,
                            const core::Settings& settings,
                            services::gemini::GeminiClient& gemini,
                            std::shared_ptr<infrastructure::SQLiteConnection> connection,
                            services::ContextStore& /*context_store*/,
                            repositories::MemoryRepository* memory_repository) {
    register_calculator_tool(registry);
    register_weather_tool(registry, settings.openweather_api_key, settings.openweather_base_url);
    register_currency_tool(registry, settings.exchange_rate_api_key, settings.exchange_rate_base_url);
    register_polls_tool(registry);
    register_search_messages_tool(registry, connection);
    register_search_tool(registry, settings.enable_web_search);
    register_image_tools(registry,
                         gemini,
                         connection,
                         settings.image_generation_daily_limit,
                         settings.admin_user_ids,
                         settings.enable_image_generation);
    register_memory_tools(registry, memory_repository, settings.enable_tool_based_memory);
}

}  // namespace gryag::services::tools
