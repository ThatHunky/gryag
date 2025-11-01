#include "gryag/repositories/memory_repository.hpp"

#include <SQLiteCpp/Statement.h>
#include <spdlog/spdlog.h>

#include <chrono>

namespace gryag::repositories {

MemoryRepository::MemoryRepository(std::shared_ptr<infrastructure::SQLiteConnection> connection)
    : connection_(std::move(connection)) {}

std::int64_t MemoryRepository::get_current_timestamp() {
    return std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();
}

MemoryRepository::UserMemory MemoryRepository::row_to_memory(SQLite::Statement& stmt) {
    UserMemory memory;
    memory.id = stmt.getColumn("id").getInt();
    memory.user_id = stmt.getColumn("user_id").getInt64();
    memory.chat_id = stmt.getColumn("chat_id").getInt64();
    memory.memory_text = stmt.getColumn("memory_text").getString();
    memory.created_at = stmt.getColumn("created_at").getInt64();
    memory.updated_at = stmt.getColumn("updated_at").getInt64();
    return memory;
}

MemoryRepository::UserMemory MemoryRepository::add_memory(
    std::int64_t user_id,
    std::int64_t chat_id,
    const std::string& memory_text
) {
    const auto now = get_current_timestamp();

    try {
        // Check if user is at memory limit (15)
        SQLite::Statement count_stmt(
            connection_->db(),
            "SELECT COUNT(*) as count FROM user_memories WHERE user_id = ? AND chat_id = ?"
        );
        count_stmt.bind(1, user_id);
        count_stmt.bind(2, chat_id);

        if (count_stmt.executeStep()) {
            const int count = count_stmt.getColumn("count").getInt();
            if (count >= 15) {
                // Auto-delete oldest memory (FIFO) to make room
                SQLite::Statement delete_stmt(
                    connection_->db(),
                    R"(DELETE FROM user_memories
                       WHERE id = (
                           SELECT id FROM user_memories
                           WHERE user_id = ? AND chat_id = ?
                           ORDER BY created_at ASC
                           LIMIT 1
                       ))"
                );
                delete_stmt.bind(1, user_id);
                delete_stmt.bind(2, chat_id);
                delete_stmt.exec();

                spdlog::debug("Deleted oldest memory for user {} in chat {} (FIFO limit)", user_id, chat_id);
            }
        }

        // Insert the new memory
        SQLite::Statement insert_stmt(
            connection_->db(),
            R"(INSERT INTO user_memories (user_id, chat_id, memory_text, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?))"
        );
        insert_stmt.bind(1, user_id);
        insert_stmt.bind(2, chat_id);
        insert_stmt.bind(3, memory_text);
        insert_stmt.bind(4, now);
        insert_stmt.bind(5, now);
        insert_stmt.exec();

        const int memory_id = static_cast<int>(connection_->db().getLastInsertRowid());

        spdlog::info("Added memory {} for user {} in chat {}", memory_id, user_id, chat_id);

        UserMemory memory;
        memory.id = memory_id;
        memory.user_id = user_id;
        memory.chat_id = chat_id;
        memory.memory_text = memory_text;
        memory.created_at = now;
        memory.updated_at = now;

        return memory;

    } catch (const SQLite::Exception& ex) {
        // Check for UNIQUE constraint failure
        if (std::string(ex.what()).find("UNIQUE constraint") != std::string::npos) {
            throw std::runtime_error("This memory already exists for the user");
        }
        spdlog::error("Failed to add memory: {}", ex.what());
        throw std::runtime_error(std::string("Failed to add memory: ") + ex.what());
    }
}

std::vector<MemoryRepository::UserMemory> MemoryRepository::get_memories_for_user(
    std::int64_t user_id,
    std::int64_t chat_id
) {
    std::vector<UserMemory> memories;

    try {
        SQLite::Statement stmt(
            connection_->db(),
            "SELECT * FROM user_memories WHERE user_id = ? AND chat_id = ? ORDER BY created_at ASC"
        );
        stmt.bind(1, user_id);
        stmt.bind(2, chat_id);

        while (stmt.executeStep()) {
            memories.push_back(row_to_memory(stmt));
        }
    } catch (const std::exception& ex) {
        spdlog::error("Error getting memories for user: {}", ex.what());
    }

    return memories;
}

std::optional<MemoryRepository::UserMemory> MemoryRepository::get_memory_by_id(int memory_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "SELECT * FROM user_memories WHERE id = ?"
        );
        stmt.bind(1, memory_id);

        if (stmt.executeStep()) {
            return row_to_memory(stmt);
        }

        return std::nullopt;
    } catch (const std::exception& ex) {
        spdlog::error("Error getting memory by id: {}", ex.what());
        return std::nullopt;
    }
}

bool MemoryRepository::delete_memory(int memory_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "DELETE FROM user_memories WHERE id = ?"
        );
        stmt.bind(1, memory_id);
        const int rows = stmt.exec();

        if (rows > 0) {
            spdlog::info("Deleted memory {}", memory_id);
            return true;
        }
        return false;
    } catch (const std::exception& ex) {
        spdlog::error("Error deleting memory: {}", ex.what());
        return false;
    }
}

int MemoryRepository::delete_all_memories(std::int64_t user_id, std::int64_t chat_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "DELETE FROM user_memories WHERE user_id = ? AND chat_id = ?"
        );
        stmt.bind(1, user_id);
        stmt.bind(2, chat_id);
        const int rows = stmt.exec();

        spdlog::info("Deleted {} memories for user {} in chat {}", rows, user_id, chat_id);
        return rows;
    } catch (const std::exception& ex) {
        spdlog::error("Error deleting all memories: {}", ex.what());
        return 0;
    }
}

int MemoryRepository::get_memory_count(std::int64_t user_id, std::int64_t chat_id) {
    try {
        SQLite::Statement stmt(
            connection_->db(),
            "SELECT COUNT(*) as count FROM user_memories WHERE user_id = ? AND chat_id = ?"
        );
        stmt.bind(1, user_id);
        stmt.bind(2, chat_id);

        if (stmt.executeStep()) {
            return stmt.getColumn("count").getInt();
        }
        return 0;
    } catch (const std::exception& ex) {
        spdlog::error("Error getting memory count: {}", ex.what());
        return 0;
    }
}

bool MemoryRepository::update_memory(int memory_id, const std::string& new_text) {
    const auto now = get_current_timestamp();

    try {
        SQLite::Statement stmt(
            connection_->db(),
            "UPDATE user_memories SET memory_text = ?, updated_at = ? WHERE id = ?"
        );
        stmt.bind(1, new_text);
        stmt.bind(2, now);
        stmt.bind(3, memory_id);
        const int rows = stmt.exec();

        if (rows > 0) {
            spdlog::info("Updated memory {}", memory_id);
            return true;
        }
        return false;
    } catch (const std::exception& ex) {
        spdlog::error("Error updating memory: {}", ex.what());
        return false;
    }
}

}  // namespace gryag::repositories
