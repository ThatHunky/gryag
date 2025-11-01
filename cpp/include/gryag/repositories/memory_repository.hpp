#pragma once

#include "gryag/infrastructure/sqlite.hpp"

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace gryag::repositories {

/**
 * Repository for the simplified user memory system.
 *
 * Each user can have up to 15 memories per chat.
 * When adding the 16th memory, the oldest is automatically deleted (FIFO).
 */
class MemoryRepository {
public:
    /**
     * Represents a single memory for a user
     */
    struct UserMemory {
        int id = 0;
        std::int64_t user_id = 0;
        std::int64_t chat_id = 0;
        std::string memory_text;
        std::int64_t created_at = 0;
        std::int64_t updated_at = 0;
    };

    explicit MemoryRepository(std::shared_ptr<infrastructure::SQLiteConnection> connection);

    /**
     * Add a new memory for a user.
     *
     * If the user has 15 memories, the oldest one is automatically deleted (FIFO).
     *
     * @param user_id The user's ID
     * @param chat_id The chat's ID
     * @param memory_text The text of the memory to add
     * @return The newly created UserMemory object
     * @throws std::runtime_error if memory already exists (UNIQUE constraint)
     */
    UserMemory add_memory(std::int64_t user_id, std::int64_t chat_id, const std::string& memory_text);

    /**
     * Get all memories for a user in a specific chat.
     *
     * @param user_id The user's ID
     * @param chat_id The chat's ID
     * @return List of UserMemory objects, ordered by creation time (oldest first)
     */
    std::vector<UserMemory> get_memories_for_user(std::int64_t user_id, std::int64_t chat_id);

    /**
     * Get a single memory by its ID.
     *
     * @param memory_id The ID of the memory
     * @return UserMemory if found, nullopt otherwise
     */
    std::optional<UserMemory> get_memory_by_id(int memory_id);

    /**
     * Delete a single memory by its ID.
     *
     * @param memory_id The ID of the memory to delete
     * @return true if a memory was deleted, false otherwise
     */
    bool delete_memory(int memory_id);

    /**
     * Delete all memories for a user in a specific chat.
     *
     * @param user_id The user's ID
     * @param chat_id The chat's ID
     * @return The number of memories deleted
     */
    int delete_all_memories(std::int64_t user_id, std::int64_t chat_id);

    /**
     * Get the count of memories for a user in a chat.
     *
     * @param user_id The user's ID
     * @param chat_id The chat's ID
     * @return Number of memories
     */
    int get_memory_count(std::int64_t user_id, std::int64_t chat_id);

    /**
     * Update an existing memory's text.
     *
     * @param memory_id The ID of the memory to update
     * @param new_text The new text
     * @return true if updated, false if not found
     */
    bool update_memory(int memory_id, const std::string& new_text);

private:
    std::shared_ptr<infrastructure::SQLiteConnection> connection_;

    // Helper methods
    UserMemory row_to_memory(SQLite::Statement& stmt);
    std::int64_t get_current_timestamp();
};

}  // namespace gryag::repositories
