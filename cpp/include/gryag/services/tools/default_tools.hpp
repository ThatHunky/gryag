#pragma once

#include "gryag/core/settings.hpp"
#include "gryag/services/context_store.hpp"
#include "gryag/services/gemini/gemini_client.hpp"
#include "gryag/services/tools/tool.hpp"
#include "gryag/infrastructure/sqlite.hpp"

#include <memory>

namespace gryag::repositories {
class MemoryRepository;
}

namespace gryag::services::tools {

void register_default_tools(ToolRegistry& registry,
                            const core::Settings& settings,
                            services::gemini::GeminiClient& gemini,
                            std::shared_ptr<infrastructure::SQLiteConnection> connection,
                            services::ContextStore& context_store,
                            repositories::MemoryRepository* memory_repository);

}  // namespace gryag::services::tools
