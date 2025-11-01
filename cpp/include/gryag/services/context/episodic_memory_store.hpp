#pragma once

#include "gryag/infrastructure/sqlite.hpp"

#include <optional>
#include <string>
#include <vector>

namespace gryag::services::context {

struct Episode {
    std::int64_t id;
    std::int64_t chat_id;
    std::string summary;
};

class EpisodicMemoryStore {
public:
    explicit EpisodicMemoryStore(std::shared_ptr<infrastructure::SQLiteConnection> connection);

    void init();
    std::vector<Episode> recent(std::int64_t chat_id, std::size_t limit);
    std::int64_t create_episode(std::int64_t chat_id,
                                std::optional<std::int64_t> thread_id,
                                const std::string& topic,
                                const std::string& summary,
                                const std::vector<std::int64_t>& message_ids,
                                const std::vector<std::int64_t>& participant_ids,
                                double importance = 0.6,
                                const std::string& emotional_valence = "neutral",
                                const std::vector<std::string>& tags = {});

private:
    std::shared_ptr<infrastructure::SQLiteConnection> connection_;
};

}  // namespace gryag::services::context
