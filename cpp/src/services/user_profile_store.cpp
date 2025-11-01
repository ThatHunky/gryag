#include "gryag/services/user_profile_store.hpp"

#include <SQLiteCpp/Statement.h>
#include <spdlog/spdlog.h>

#include <chrono>

namespace gryag::services {

UserProfileStore::UserProfileStore(std::shared_ptr<infrastructure::SQLiteConnection> connection)
    : connection_(std::move(connection)) {}

std::int64_t UserProfileStore::get_current_timestamp() {
    return std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();
}

UserProfileStore::Profile UserProfileStore::row_to_profile(SQLite::Statement& stmt) {
    Profile profile;
    profile.user_id = stmt.getColumn("user_id").getInt64();
    profile.chat_id = stmt.getColumn("chat_id").getInt64();

    if (!stmt.getColumn("display_name").isNull()) {
        profile.display_name = stmt.getColumn("display_name").getString();
    }
    if (!stmt.getColumn("username").isNull()) {
        profile.username = stmt.getColumn("username").getString();
    }
    if (!stmt.getColumn("first_name").isNull()) {
        profile.first_name = stmt.getColumn("first_name").getString();
    }
    if (!stmt.getColumn("last_name").isNull()) {
        profile.last_name = stmt.getColumn("last_name").getString();
    }
    if (!stmt.getColumn("pronouns").isNull()) {
        profile.pronouns = stmt.getColumn("pronouns").getString();
    }
    if (!stmt.getColumn("summary").isNull()) {
        profile.summary = stmt.getColumn("summary").getString();
    }
    if (!stmt.getColumn("membership_status").isNull()) {
        profile.membership_status = stmt.getColumn("membership_status").getString();
    }

    profile.created_at = stmt.getColumn("created_at").getInt64();
    profile.last_seen = stmt.getColumn("last_seen").getInt64();
    profile.updated_at = stmt.getColumn("updated_at").getInt64();
    profile.interaction_count = stmt.getColumn("interaction_count").getInt();

    if (!stmt.getColumn("summary_updated_at").isNull()) {
        profile.summary_updated_at = stmt.getColumn("summary_updated_at").getInt64();
    }

    return profile;
}

UserProfileStore::Fact UserProfileStore::row_to_fact(SQLite::Statement& stmt) {
    Fact fact;
    fact.id = stmt.getColumn("id").getInt();
    fact.user_id = stmt.getColumn("user_id").getInt64();
    fact.chat_id = stmt.getColumn("chat_id").getInt64();
    fact.fact_type = stmt.getColumn("fact_type").getString();
    fact.fact_key = stmt.getColumn("fact_key").getString();
    fact.fact_value = stmt.getColumn("fact_value").getString();
    fact.confidence = stmt.getColumn("confidence").getDouble();

    if (!stmt.getColumn("evidence").isNull()) {
        fact.evidence = stmt.getColumn("evidence").getString();
    }

    fact.extracted_at = stmt.getColumn("extracted_at").getInt64();
    fact.active = stmt.getColumn("active").getInt() != 0;

    return fact;
}

UserProfileStore::Profile UserProfileStore::get_or_create_profile(
    std::int64_t user_id,
    std::int64_t chat_id,
    const std::string& display_name,
    const std::string& username
) {
    const auto now = get_current_timestamp();

    try {
        // Try to get existing profile
        SQLite::Statement select_stmt(
            connection_->db(),
            "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?"
        );
        select_stmt.bind(1, user_id);
        select_stmt.bind(2, chat_id);

        if (select_stmt.executeStep()) {
            // Profile exists - update last_seen and optional fields
            std::vector<std::string> updates = {"last_seen = ?", "updated_at = ?", "membership_status = 'member'"};
            std::vector<std::string> params;
            params.push_back(std::to_string(now));
            params.push_back(std::to_string(now));

            std::string update_sql = "UPDATE user_profiles SET " + updates[0] + ", " + updates[1] + ", " + updates[2];

            int param_index = 3;
            if (!display_name.empty()) {
                update_sql += ", display_name = ?";
                params.push_back(display_name);
                param_index++;
            }
            if (!username.empty()) {
                update_sql += ", username = ?";
                params.push_back(username);
                param_index++;
            }

            update_sql += " WHERE user_id = ? AND chat_id = ?";

            SQLite::Statement update_stmt(connection_->db(), update_sql);
            update_stmt.bind(1, now);
            update_stmt.bind(2, now);

            int bind_idx = 3;
            if (!display_name.empty()) {
                update_stmt.bind(bind_idx++, display_name);
            }
            if (!username.empty()) {
                update_stmt.bind(bind_idx++, username);
            }
            update_stmt.bind(bind_idx++, user_id);
            update_stmt.bind(bind_idx++, chat_id);

            update_stmt.exec();

            // Fetch updated profile
            SQLite::Statement fetch_stmt(
                connection_->db(),
                "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?"
            );
            fetch_stmt.bind(1, user_id);
            fetch_stmt.bind(2, chat_id);
            fetch_stmt.executeStep();

            return row_to_profile(fetch_stmt);
        }

        // Profile doesn't exist - create new one
        SQLite::Statement insert_stmt(
            connection_->db(),
            R"(INSERT INTO user_profiles
               (user_id, chat_id, display_name, username, created_at, last_seen,
                updated_at, membership_status, interaction_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'member', 0))"
        );
        insert_stmt.bind(1, user_id);
        insert_stmt.bind(2, chat_id);
        insert_stmt.bind(3, display_name);
        insert_stmt.bind(4, username);
        insert_stmt.bind(5, now);
        insert_stmt.bind(6, now);
        insert_stmt.bind(7, now);
        insert_stmt.exec();

        // Fetch newly created profile
        SQLite::Statement fetch_stmt(
            connection_->db(),
            "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?"
        );
        fetch_stmt.bind(1, user_id);
        fetch_stmt.bind(2, chat_id);
        fetch_stmt.executeStep();

        spdlog::info("Created new profile for user {} in chat {}", user_id, chat_id);
        return row_to_profile(fetch_stmt);

    } catch (const std::exception& ex) {
        spdlog::error("Error in get_or_create_profile: {}", ex.what());
        throw;
    }
}

std::optional<UserProfileStore::Profile> UserProfileStore::get_profile(
    std::int64_t user_id,
    std::int64_t chat_id
) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "SELECT * FROM user_profiles WHERE user_id = ? AND chat_id = ?"
        );
        stmt.bind(1, user_id);
        stmt.bind(2, chat_id);

        if (stmt.executeStep()) {
            return row_to_profile(stmt);
        }

        return std::nullopt;
    } catch (const std::exception& ex) {
        spdlog::error("Error in get_profile: {}", ex.what());
        return std::nullopt;
    }
}

void UserProfileStore::update_profile(
    std::int64_t user_id,
    std::int64_t chat_id,
    const std::string& field,
    const std::string& value
) {
    const auto now = get_current_timestamp();

    try {
        const std::string sql = "UPDATE user_profiles SET " + field + " = ?, updated_at = ? WHERE user_id = ? AND chat_id = ?";
        SQLite::Statement stmt(connection_->db(), sql);
        stmt.bind(1, value);
        stmt.bind(2, now);
        stmt.bind(3, user_id);
        stmt.bind(4, chat_id);
        stmt.exec();
    } catch (const std::exception& ex) {
        spdlog::error("Error in update_profile: {}", ex.what());
    }
}

void UserProfileStore::update_summary(std::int64_t user_id, const std::string& summary) {
    const auto now = get_current_timestamp();

    try {
        SQLite::Statement stmt(
            connection_->db(),
            "UPDATE user_profiles SET summary = ?, summary_updated_at = ?, updated_at = ? WHERE user_id = ?"
        );
        stmt.bind(1, summary);
        stmt.bind(2, now);
        stmt.bind(3, now);
        stmt.bind(4, user_id);
        stmt.exec();

        spdlog::info("Updated summary for user {}", user_id);
    } catch (const std::exception& ex) {
        spdlog::error("Error in update_summary: {}", ex.what());
    }
}

void UserProfileStore::update_pronouns(
    std::int64_t user_id,
    std::int64_t chat_id,
    const std::string& pronouns
) {
    const auto now = get_current_timestamp();

    try {
        SQLite::Statement stmt(
            connection_->db(),
            "UPDATE user_profiles SET pronouns = ?, updated_at = ? WHERE user_id = ? AND chat_id = ?"
        );
        stmt.bind(1, pronouns);
        stmt.bind(2, now);
        stmt.bind(3, user_id);
        stmt.bind(4, chat_id);
        stmt.exec();
    } catch (const std::exception& ex) {
        spdlog::error("Error in update_pronouns: {}", ex.what());
    }
}

void UserProfileStore::update_interaction_count(std::int64_t user_id, std::int64_t chat_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "UPDATE user_profiles SET interaction_count = interaction_count + 1 WHERE user_id = ? AND chat_id = ?"
        );
        stmt.bind(1, user_id);
        stmt.bind(2, chat_id);
        stmt.exec();
    } catch (const std::exception& ex) {
        spdlog::error("Error in update_interaction_count: {}", ex.what());
    }
}

void UserProfileStore::update_membership_status(
    std::int64_t user_id,
    std::int64_t chat_id,
    const std::string& status
) {
    const auto now = get_current_timestamp();

    try {
        SQLite::Statement stmt(
            connection_->db(),
            "UPDATE user_profiles SET membership_status = ?, updated_at = ? WHERE user_id = ? AND chat_id = ?"
        );
        stmt.bind(1, status);
        stmt.bind(2, now);
        stmt.bind(3, user_id);
        stmt.bind(4, chat_id);
        stmt.exec();

        spdlog::info("Updated membership status for user {} in chat {}: {}", user_id, chat_id, status);
    } catch (const std::exception& ex) {
        spdlog::error("Error in update_membership_status: {}", ex.what());
    }
}

std::vector<UserProfileStore::Profile> UserProfileStore::list_chat_users(
    std::int64_t chat_id,
    bool active_only,
    int limit
) {
    std::vector<Profile> profiles;

    try {
        std::string sql = "SELECT * FROM user_profiles WHERE chat_id = ?";
        if (active_only) {
            sql += " AND membership_status = 'member'";
        }
        sql += " ORDER BY last_seen DESC LIMIT ?";

        SQLite::Statement stmt(connection_->db(), sql);
        stmt.bind(1, chat_id);
        stmt.bind(2, limit);

        while (stmt.executeStep()) {
            profiles.push_back(row_to_profile(stmt));
        }
    } catch (const std::exception& ex) {
        spdlog::error("Error in list_chat_users: {}", ex.what());
    }

    return profiles;
}

int UserProfileStore::add_fact(
    std::int64_t user_id,
    std::int64_t chat_id,
    const std::string& fact_type,
    const std::string& fact_key,
    const std::string& fact_value,
    double confidence,
    const std::string& evidence
) {
    const auto now = get_current_timestamp();

    try {
        SQLite::Statement stmt(
            connection_->db(),
            R"(INSERT INTO user_facts
               (user_id, chat_id, fact_type, fact_key, fact_value, confidence, evidence, extracted_at, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1))"
        );
        stmt.bind(1, user_id);
        stmt.bind(2, chat_id);
        stmt.bind(3, fact_type);
        stmt.bind(4, fact_key);
        stmt.bind(5, fact_value);
        stmt.bind(6, confidence);
        stmt.bind(7, evidence);
        stmt.bind(8, now);
        stmt.exec();

        const int fact_id = static_cast<int>(connection_->db().getLastInsertRowid());
        spdlog::info("Added fact {} for user {} in chat {}: {} = {}",
                    fact_id, user_id, chat_id, fact_key, fact_value);

        return fact_id;
    } catch (const std::exception& ex) {
        spdlog::error("Error in add_fact: {}", ex.what());
        return -1;
    }
}

std::vector<UserProfileStore::Fact> UserProfileStore::get_facts(
    std::int64_t user_id,
    std::int64_t chat_id,
    bool active_only,
    double min_confidence
) {
    std::vector<Fact> facts;

    try {
        std::string sql = "SELECT * FROM user_facts WHERE user_id = ? AND chat_id = ?";
        if (active_only) {
            sql += " AND active = 1";
        }
        sql += " AND confidence >= ? ORDER BY extracted_at DESC";

        SQLite::Statement stmt(connection_->db(), sql);
        stmt.bind(1, user_id);
        stmt.bind(2, chat_id);
        stmt.bind(3, min_confidence);

        while (stmt.executeStep()) {
            facts.push_back(row_to_fact(stmt));
        }
    } catch (const std::exception& ex) {
        spdlog::error("Error in get_facts: {}", ex.what());
    }

    return facts;
}

void UserProfileStore::deactivate_fact(int fact_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "UPDATE user_facts SET active = 0 WHERE id = ?"
        );
        stmt.bind(1, fact_id);
        stmt.exec();

        spdlog::info("Deactivated fact {}", fact_id);
    } catch (const std::exception& ex) {
        spdlog::error("Error in deactivate_fact: {}", ex.what());
    }
}

bool UserProfileStore::delete_fact(int fact_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "DELETE FROM user_facts WHERE id = ?"
        );
        stmt.bind(1, fact_id);
        const int rows = stmt.exec();

        if (rows > 0) {
            spdlog::info("Deleted fact {}", fact_id);
            return true;
        }
        return false;
    } catch (const std::exception& ex) {
        spdlog::error("Error in delete_fact: {}", ex.what());
        return false;
    }
}

int UserProfileStore::get_fact_count(std::int64_t user_id, std::int64_t chat_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "SELECT COUNT(*) as count FROM user_facts WHERE user_id = ? AND chat_id = ? AND active = 1"
        );
        stmt.bind(1, user_id);
        stmt.bind(2, chat_id);

        if (stmt.executeStep()) {
            return stmt.getColumn("count").getInt();
        }
        return 0;
    } catch (const std::exception& ex) {
        spdlog::error("Error in get_fact_count: {}", ex.what());
        return 0;
    }
}

int UserProfileStore::clear_user_facts(std::int64_t user_id, std::int64_t chat_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "DELETE FROM user_facts WHERE user_id = ? AND chat_id = ?"
        );
        stmt.bind(1, user_id);
        stmt.bind(2, chat_id);
        const int rows = stmt.exec();

        spdlog::info("Cleared {} facts for user {} in chat {}", rows, user_id, chat_id);
        return rows;
    } catch (const std::exception& ex) {
        spdlog::error("Error in clear_user_facts: {}", ex.what());
        return 0;
    }
}

void UserProfileStore::delete_profile(std::int64_t user_id, std::int64_t chat_id) {
    try {
        // Delete facts first
        SQLite::Statement delete_facts(
            connection_->db(),
            "DELETE FROM user_facts WHERE user_id = ? AND chat_id = ?"
        );
        delete_facts.bind(1, user_id);
        delete_facts.bind(2, chat_id);
        delete_facts.exec();

        // Delete profile
        SQLite::Statement delete_profile(
            connection_->db(),
            "DELETE FROM user_profiles WHERE user_id = ? AND chat_id = ?"
        );
        delete_profile.bind(1, user_id);
        delete_profile.bind(2, chat_id);
        delete_profile.exec();

        spdlog::info("Deleted profile for user {} in chat {}", user_id, chat_id);
    } catch (const std::exception& ex) {
        spdlog::error("Error in delete_profile: {}", ex.what());
    }
}

int UserProfileStore::prune_old_facts(int retention_days) {
    const auto cutoff = get_current_timestamp() - (retention_days * 24 * 60 * 60);

    try {
        SQLite::Statement stmt(
            connection_->db(),
            "DELETE FROM user_facts WHERE extracted_at < ?"
        );
        stmt.bind(1, cutoff);
        const int rows = stmt.exec();

        spdlog::info("Pruned {} old facts (older than {} days)", rows, retention_days);
        return rows;
    } catch (const std::exception& ex) {
        spdlog::error("Error in prune_old_facts: {}", ex.what());
        return 0;
    }
}

std::vector<std::int64_t> UserProfileStore::get_profiles_needing_summarization(int limit) {
    std::vector<std::int64_t> user_ids;

    try {
        SQLite::Statement stmt(
            connection_->db(),
            R"(SELECT user_id FROM user_profiles
               WHERE summary_updated_at IS NULL OR summary_updated_at < updated_at
               ORDER BY updated_at DESC LIMIT ?)"
        );
        stmt.bind(1, limit);

        while (stmt.executeStep()) {
            user_ids.push_back(stmt.getColumn("user_id").getInt64());
        }
    } catch (const std::exception& ex) {
        spdlog::error("Error in get_profiles_needing_summarization: {}", ex.what());
    }

    return user_ids;
}

}  // namespace gryag::services
