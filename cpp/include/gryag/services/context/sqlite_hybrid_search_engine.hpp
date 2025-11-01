#pragma once

#include "gryag/infrastructure/sqlite.hpp"
#include "gryag/services/context/hybrid_search_engine.hpp"

namespace gryag::services::context {

class SQLiteHybridSearchEngine : public HybridSearchEngine {
public:
    explicit SQLiteHybridSearchEngine(std::shared_ptr<infrastructure::SQLiteConnection> connection);

    std::vector<ContextSnippet> search(std::int64_t chat_id,
                                       const std::string& query,
                                       std::size_t limit) override;

private:
    std::shared_ptr<infrastructure::SQLiteConnection> connection_;
};

}  // namespace gryag::services::context
