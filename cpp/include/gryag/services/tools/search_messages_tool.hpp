#pragma once

#include "gryag/services/tools/tool.hpp"
#include "gryag/infrastructure/sqlite.hpp"

#include <memory>

namespace gryag::services::tools {

void register_search_messages_tool(ToolRegistry& registry,
                                   std::shared_ptr<infrastructure::SQLiteConnection> connection);

}
