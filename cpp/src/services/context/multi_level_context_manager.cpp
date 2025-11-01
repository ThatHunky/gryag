#include "gryag/services/context/multi_level_context_manager.hpp"

#include "gryag/services/context/hybrid_search_engine.hpp"
#include "gryag/services/context/episodic_memory_store.hpp"
#include "gryag/services/gemini/gemini_client.hpp"

#include <spdlog/spdlog.h>

namespace gryag::services::context {

MultiLevelContextManager::MultiLevelContextManager(const core::Settings& settings,
                                                   services::ContextStore& store,
                                                   HybridSearchEngine* hybrid_search,
                                                   EpisodicMemoryStore* episodic_memory,
                                                   gryag::services::gemini::GeminiClient* gemini_client)
    : settings_(settings),
      store_(store),
      hybrid_search_(hybrid_search),
      episodic_memory_(episodic_memory),
      gemini_client_(gemini_client) {}

std::vector<ContextSnippet> MultiLevelContextManager::build_context(std::int64_t chat_id,
                                                                    std::size_t token_budget,
                                                                    const std::string& user_query) {
    // Helper lambda to estimate tokens
    auto estimate_tokens = [](const std::string& text) -> std::size_t {
        return (text.length() + 3) / 4;  // Rough approximation for Gemini
    };

    std::vector<ContextSnippet> snippets;
    std::size_t tokens_used = 0;

    // TIER 1: Episodic memory (high priority, max 33% of budget)
    // =========================================================
    const std::size_t episodic_budget = token_budget / 3;
    std::size_t episodic_tokens = 0;

    if (episodic_memory_) {
        try {
            auto episodes = episodic_memory_->recent(chat_id, 5);
            for (const auto& episode : episodes) {
                std::size_t episode_tokens = estimate_tokens(episode.summary);

                if (episodic_tokens + episode_tokens <= episodic_budget) {
                    snippets.push_back(ContextSnippet{
                        .role = "system",
                        .content = "Previous conversation: " + episode.summary
                    });
                    episodic_tokens += episode_tokens;
                    tokens_used += episode_tokens;
                } else {
                    spdlog::debug("Episodic budget exhausted at {} tokens", episodic_tokens);
                    break;
                }
            }
        } catch (const std::exception& ex) {
            spdlog::debug("Episodic memory fetch failed: {}", ex.what());
        }
    }

    // TIER 2: Retrieved context via hybrid search (33% of budget)
    // ===========================================================
    const std::size_t retrieval_budget = token_budget / 3;
    std::size_t retrieval_tokens = 0;

    if (hybrid_search_ && !user_query.empty()) {
        try {
            std::size_t search_limit = std::max(5ul, retrieval_budget / 100);
            auto retrieved = hybrid_search_->search(chat_id, user_query, search_limit);

            for (const auto& snippet : retrieved) {
                std::size_t snippet_tokens = estimate_tokens(snippet.content);

                if (retrieval_tokens + snippet_tokens <= retrieval_budget) {
                    snippets.push_back(snippet);
                    retrieval_tokens += snippet_tokens;
                    tokens_used += snippet_tokens;
                } else {
                    spdlog::debug("Retrieval budget exhausted at {} tokens", retrieval_tokens);
                    break;
                }
            }
        } catch (const std::exception& ex) {
            spdlog::debug("Hybrid search failed: {}", ex.what());
        }
    }

    // TIER 3: Recent conversation messages (remaining budget)
    // =======================================================
    const std::size_t recent_budget = token_budget - tokens_used;
    std::size_t recent_tokens = 0;

    try {
        auto recent_messages = store_.recent_messages(chat_id, 40);

        // Add in reverse order to get chronological (oldest first)
        std::reverse(recent_messages.begin(), recent_messages.end());

        for (const auto& record : recent_messages) {
            ContextSnippet snippet;
            snippet.role = record.role;
            snippet.content = record.text;

            std::size_t snippet_tokens = estimate_tokens(snippet.content);

            if (recent_tokens + snippet_tokens <= recent_budget) {
                snippets.push_back(std::move(snippet));
                recent_tokens += snippet_tokens;
                tokens_used += snippet_tokens;
            } else {
                spdlog::debug("Recent message budget exhausted at {} tokens", recent_tokens);
                break;
            }
        }
    } catch (const std::exception& ex) {
        spdlog::debug("Recent messages fetch failed: {}", ex.what());
    }

    // Emergency fallback: ensure we have at least some context
    if (snippets.empty()) {
        spdlog::warn("Context assembly produced no snippets, using fallback");
        try {
            auto fallback = store_.recent_messages(chat_id, 10);
            for (const auto& record : fallback) {
                ContextSnippet snippet;
                snippet.role = record.role;
                snippet.content = record.text;
                snippets.push_back(std::move(snippet));
            }
        } catch (const std::exception& ex) {
            spdlog::warn("Emergency fallback failed: {}", ex.what());
        }
    }

    spdlog::debug(
        "Context assembled for chat {}: {} snippets, {} tokens used (budget: {})",
        chat_id, snippets.size(), tokens_used, token_budget
    );

    return snippets;
}

}  // namespace gryag::services::context
