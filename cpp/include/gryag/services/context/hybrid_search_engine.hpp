#pragma once

#include <string>
#include <vector>

namespace gryag::services::context {

struct ContextSnippet;

class HybridSearchEngine {
public:
    virtual ~HybridSearchEngine() = default;

    virtual std::vector<ContextSnippet> search(
        std::int64_t chat_id,
        const std::string& query,
        std::size_t limit
    ) = 0;
};

}  // namespace gryag::services::context
