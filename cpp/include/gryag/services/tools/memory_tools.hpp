#pragma once

#include "gryag/services/tools/tool.hpp"

namespace gryag::repositories {
class MemoryRepository;
}

namespace gryag::services::tools {

void register_memory_tools(ToolRegistry& registry,
                           repositories::MemoryRepository* memory_repository,
                           bool enabled);

}
