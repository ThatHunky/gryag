#pragma once

#include "gryag/core/settings.hpp"
#include "gryag/services/context_store.hpp"
#include "gryag/services/context/episodic_memory_store.hpp"

#include <chrono>
#include <functional>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace gryag::services::gemini {
class GeminiClient;
}

namespace gryag::services::background {

class EpisodeMonitor {
public:
    EpisodeMonitor(const core::Settings& settings,
                   services::context::EpisodicMemoryStore& episode_store,
                   services::gemini::GeminiClient* gemini_client);

    void track_message(const services::MessageRecord& record);
    void tick();

private:
    struct WindowKey {
        std::int64_t chat_id;
        std::optional<std::int64_t> thread_id;
        bool operator==(const WindowKey& other) const noexcept {
            return chat_id == other.chat_id && thread_id == other.thread_id;
        }
    };

    struct WindowKeyHasher {
        std::size_t operator()(const WindowKey& key) const noexcept;
    };

    struct Window {
        std::vector<services::MessageRecord> messages;
        std::chrono::system_clock::time_point last_activity;
        std::unordered_set<std::int64_t> participants;
    };

    bool should_capture_role(const std::string& role) const;
    void finalize_window(const WindowKey& key, Window& window);
    std::string build_topic(const Window& window) const;
    std::string build_summary(const Window& window) const;

    const core::Settings& settings_;
    services::context::EpisodicMemoryStore& episode_store_;
    services::gemini::GeminiClient* gemini_client_;

    std::unordered_map<WindowKey, Window, WindowKeyHasher> windows_;
    std::chrono::steady_clock::time_point next_sweep_;
    std::chrono::seconds window_timeout_;
    std::size_t min_messages_;
    std::size_t max_messages_;
    std::chrono::steady_clock::duration sweep_interval_;
};

}  // namespace gryag::services::background
