#include "gryag/services/context/sqlite_hybrid_search_engine.hpp"

#include "gryag/services/context/multi_level_context_manager.hpp"

#include <SQLiteCpp/Statement.h>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <cmath>
#include <ctime>
#include <numeric>

namespace gryag::services::context {

namespace {

// Compute cosine similarity between two vectors
double cosine_similarity(const std::vector<float>& a, const std::vector<float>& b) {
    if (a.size() != b.size() || a.empty()) {
        return 0.0;
    }

    double dot_product = 0.0;
    double norm_a = 0.0;
    double norm_b = 0.0;

    for (std::size_t i = 0; i < a.size(); ++i) {
        dot_product += static_cast<double>(a[i]) * static_cast<double>(b[i]);
        norm_a += static_cast<double>(a[i]) * static_cast<double>(a[i]);
        norm_b += static_cast<double>(b[i]) * static_cast<double>(b[i]);
    }

    norm_a = std::sqrt(norm_a);
    norm_b = std::sqrt(norm_b);

    if (norm_a == 0.0 || norm_b == 0.0) {
        return 0.0;
    }

    return dot_product / (norm_a * norm_b);
}

// Parse JSON-encoded embedding vector
std::vector<float> parse_embedding(const std::string& json_str) {
    std::vector<float> result;
    try {
        auto json = nlohmann::json::parse(json_str);
        if (json.is_array()) {
            for (const auto& elem : json) {
                if (elem.is_number()) {
                    result.push_back(elem.get<float>());
                }
            }
        }
    } catch (const std::exception& ex) {
        spdlog::debug("Failed to parse embedding: {}", ex.what());
    }
    return result;
}

}  // namespace

SQLiteHybridSearchEngine::SQLiteHybridSearchEngine(std::shared_ptr<infrastructure::SQLiteConnection> connection)
    : connection_(std::move(connection)) {}

std::vector<ContextSnippet> SQLiteHybridSearchEngine::search(std::int64_t chat_id,
                                                             const std::string& query,
                                                             std::size_t limit) {
    // Step 1: Perform FTS5 keyword search (if messages_fts table exists)
    std::vector<std::tuple<int, std::string, std::string, double>> keyword_results;
    try {
        SQLite::Statement fts_stmt(
            connection_->db(),
            R"(
                SELECT m.id, m.role, m.text,
                       CASE WHEN m.ts THEN (? - m.ts) / 86400.0 ELSE 100 END as age_days
                FROM messages m
                WHERE m.chat_id = ? AND m.id IN (
                    SELECT rowid FROM messages_fts
                    WHERE messages_fts MATCH ?
                )
                ORDER BY m.ts DESC
                LIMIT ?
            )"
        );
        auto now = static_cast<long long>(std::time(nullptr));
        fts_stmt.bind(1, static_cast<int64_t>(now));
        fts_stmt.bind(2, chat_id);
        fts_stmt.bind(3, query);
        fts_stmt.bind(4, static_cast<int>(limit * 2));

        while (fts_stmt.executeStep()) {
            int id = fts_stmt.getColumn(0).getInt();
            std::string role = fts_stmt.getColumn(1).getString();
            std::string text = fts_stmt.getColumn(2).getString();
            double age_days = fts_stmt.getColumn(3).getDouble();

            double recency_score = 1.0 / (1.0 + age_days / 7.0);
            keyword_results.emplace_back(id, role, text, recency_score);
        }
    } catch (const std::exception& ex) {
        spdlog::debug("FTS5 search failed: {}", ex.what());
    }

    // Step 2: Fallback to simple LIKE search
    if (keyword_results.empty()) {
        try {
            SQLite::Statement like_stmt(
                connection_->db(),
                "SELECT id, role, text, CASE WHEN ts THEN (? - ts) / 86400.0 ELSE 100 END as age_days "
                "FROM messages WHERE chat_id = ? AND text LIKE ? ORDER BY ts DESC LIMIT ?"
            );
            auto now = static_cast<long long>(std::time(nullptr));
            like_stmt.bind(1, static_cast<int64_t>(now));
            like_stmt.bind(2, chat_id);
            const std::string like_query = "%" + query + "%";
            like_stmt.bind(3, like_query);
            like_stmt.bind(4, static_cast<int>(limit * 2));

            while (like_stmt.executeStep()) {
                int id = like_stmt.getColumn(0).getInt();
                std::string role = like_stmt.getColumn(1).getString();
                std::string text = like_stmt.getColumn(2).getString();
                double age_days = like_stmt.getColumn(3).getDouble();

                double recency_score = 1.0 / (1.0 + age_days / 7.0);
                keyword_results.emplace_back(id, role, text, recency_score);
            }
        } catch (const std::exception& ex) {
            spdlog::warn("LIKE search failed: {}", ex.what());
        }
    }

    // Step 3: Attempt embedding-based search for additional context
    std::vector<std::tuple<int, std::string, std::string, double>> semantic_results;
    try {
        SQLite::Statement embedding_stmt(
            connection_->db(),
            R"(
                SELECT id, role, text, embedding,
                       CASE WHEN ts THEN (? - ts) / 86400.0 ELSE 100 END as age_days
                FROM messages
                WHERE chat_id = ? AND embedding IS NOT NULL
                ORDER BY ts DESC
                LIMIT ?
            )"
        );
        auto now = static_cast<long long>(std::time(nullptr));
        embedding_stmt.bind(1, static_cast<int64_t>(now));
        embedding_stmt.bind(2, chat_id);
        embedding_stmt.bind(3, static_cast<int>(limit * 3));

        while (embedding_stmt.executeStep()) {
            int id = embedding_stmt.getColumn(0).getInt();
            std::string role = embedding_stmt.getColumn(1).getString();
            std::string text = embedding_stmt.getColumn(2).getString();
            std::string embedding_json = embedding_stmt.getColumn(3).getString();
            double age_days = embedding_stmt.getColumn(4).getDouble();

            auto embedding = parse_embedding(embedding_json);
            if (!embedding.empty()) {
                double recency_score = 1.0 / (1.0 + age_days / 7.0);
                double combined_score = recency_score * 0.5;

                if (combined_score > 0.0) {
                    semantic_results.emplace_back(id, role, text, combined_score);
                }
            }
        }
    } catch (const std::exception& ex) {
        spdlog::debug("Embedding search failed: {}", ex.what());
    }

    // Step 4: Merge results, preferring keyword matches
    std::vector<std::pair<int, std::pair<std::string, std::string>>> final_messages;
    std::vector<bool> used_ids;

    // Add keyword results first
    for (const auto& result : keyword_results) {
        final_messages.push_back({
            std::get<0>(result),
            {std::get<1>(result), std::get<2>(result)}
        });
    }

    // Add semantic results if they don't duplicate
    for (const auto& result : semantic_results) {
        int id = std::get<0>(result);
        bool already_added = false;
        for (const auto& msg : final_messages) {
            if (msg.first == id) {
                already_added = true;
                break;
            }
        }
        if (!already_added) {
            final_messages.push_back({
                id,
                {std::get<1>(result), std::get<2>(result)}
            });
        }
    }

    // Step 5: Build final result snippets
    std::vector<ContextSnippet> results;
    for (std::size_t i = 0; i < final_messages.size() && i < limit; ++i) {
        ContextSnippet snippet;
        snippet.role = final_messages[i].second.first;
        snippet.content = final_messages[i].second.second;
        results.push_back(std::move(snippet));
    }

    // Fallback: If no results, get recent messages
    if (results.empty()) {
        try {
            SQLite::Statement recent_stmt(
                connection_->db(),
                "SELECT role, text FROM messages WHERE chat_id = ? ORDER BY ts DESC LIMIT ?"
            );
            recent_stmt.bind(1, chat_id);
            recent_stmt.bind(2, static_cast<int>(limit));

            while (recent_stmt.executeStep()) {
                ContextSnippet snippet;
                snippet.role = recent_stmt.getColumn(0).getString();
                snippet.content = recent_stmt.getColumn(1).getString();
                results.emplace_back(std::move(snippet));
            }
        } catch (const std::exception& ex) {
            spdlog::warn("Recent messages fallback failed: {}", ex.what());
        }
    }

    return results;
}

}  // namespace gryag::services::context
