#pragma once

#include "gryag/core/settings.hpp"
#include "gryag/services/context_store.hpp"

#include <string>
#include <vector>

namespace gryag::services::gemini {
class GeminiClient;
}

namespace gryag::services::context {

struct ContextSnippet {
    std::string role;
    std::string content;
};

class HybridSearchEngine;
class EpisodicMemoryStore;
class GeminiClient;

class MultiLevelContextManager {
public:
    MultiLevelContextManager(const core::Settings& settings,
                             services::ContextStore& store,
                             HybridSearchEngine* hybrid_search,
                             EpisodicMemoryStore* episodic_memory,
                             gryag::services::gemini::GeminiClient* gemini_client);

    std::vector<ContextSnippet> build_context(std::int64_t chat_id,
                                              std::size_t token_budget,
                                              const std::string& user_query);

private:
    const core::Settings& settings_;
    services::ContextStore& store_;
    HybridSearchEngine* hybrid_search_;
    EpisodicMemoryStore* episodic_memory_;
    gryag::services::gemini::GeminiClient* gemini_client_;
};

}  // namespace gryag::services::context
