#include "gryag/services/context/episodic_memory_store.hpp"

#include <SQLiteCpp/Statement.h>
#include <nlohmann/json.hpp>

#include <chrono>

namespace gryag::services::context {

EpisodicMemoryStore::EpisodicMemoryStore(std::shared_ptr<infrastructure::SQLiteConnection> connection)
    : connection_(std::move(connection)) {}

void EpisodicMemoryStore::init() {
    // Schema already enforced by ContextStore::init (shared database schema)
}

std::vector<Episode> EpisodicMemoryStore::recent(std::int64_t chat_id, std::size_t limit) {
    SQLite::Statement stmt(
        connection_->db(),
        "SELECT id, chat_id, summary FROM episodes WHERE chat_id = ? "
        "ORDER BY last_accessed DESC NULLS LAST, created_at DESC LIMIT ?"
    );
    stmt.bind(1, chat_id);
    stmt.bind(2, static_cast<int>(limit));

    std::vector<Episode> episodes;
    while (stmt.executeStep()) {
        Episode episode;
        episode.id = stmt.getColumn(0).getInt64();
        episode.chat_id = stmt.getColumn(1).getInt64();
        episode.summary = stmt.getColumn(2).getString();
        episodes.emplace_back(std::move(episode));
    }

    return episodes;
}

std::int64_t EpisodicMemoryStore::create_episode(std::int64_t chat_id,
                                                 std::optional<std::int64_t> thread_id,
                                                 const std::string& topic,
                                                 const std::string& summary,
                                                 const std::vector<std::int64_t>& message_ids,
                                                 const std::vector<std::int64_t>& participant_ids,
                                                 double importance,
                                                 const std::string& emotional_valence,
                                                 const std::vector<std::string>& tags) {
    const auto now = std::chrono::system_clock::now();
    const auto ts = std::chrono::duration_cast<std::chrono::seconds>(now.time_since_epoch()).count();

    nlohmann::json message_ids_json = message_ids;
    nlohmann::json participant_ids_json = participant_ids;
    nlohmann::json tags_json = tags;

    SQLite::Statement stmt(
        connection_->db(),
        "INSERT INTO episodes (chat_id, thread_id, topic, summary, summary_embedding, importance, "
        "emotional_valence, message_ids, participant_ids, tags, created_at, last_accessed, access_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)"
    );

    stmt.bind(1, chat_id);
    if (thread_id) {
        stmt.bind(2, *thread_id);
    } else {
        stmt.bind(2);
    }
    stmt.bind(3, topic);
    stmt.bind(4, summary);
    stmt.bind(5);  // summary_embedding NULL
    stmt.bind(6, importance);
    stmt.bind(7, emotional_valence);
    stmt.bind(8, message_ids_json.dump());
    stmt.bind(9, participant_ids_json.dump());
    stmt.bind(10, tags_json.dump());
    stmt.bind(11, static_cast<std::int64_t>(ts));
    stmt.bind(12, static_cast<std::int64_t>(ts));

    stmt.exec();
    return connection_->db().getLastInsertRowid();
}

}  // namespace gryag::services::context
