#include "gryag/services/background/episode_monitor.hpp"

#include "gryag/services/gemini/gemini_client.hpp"

#include <spdlog/spdlog.h>

#include <algorithm>
#include <array>
#include <numeric>
#include <sstream>
#include <string_view>

namespace gryag::services::background {

namespace {

std::chrono::steady_clock::time_point now_steady() {
    return std::chrono::steady_clock::now();
}

}  // namespace

std::size_t EpisodeMonitor::WindowKeyHasher::operator()(const WindowKey& key) const noexcept {
    std::size_t h = std::hash<std::int64_t>{}(key.chat_id);
    if (key.thread_id) {
        std::size_t thread_hash = std::hash<std::int64_t>{}(*key.thread_id);
        h ^= thread_hash + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2);
    }
    return h;
}

EpisodeMonitor::EpisodeMonitor(const core::Settings& settings,
                               services::context::EpisodicMemoryStore& episode_store,
                               services::gemini::GeminiClient* gemini_client)
    : settings_(settings),
      episode_store_(episode_store),
      gemini_client_(gemini_client),
      next_sweep_(now_steady()),
      window_timeout_(std::chrono::seconds(std::max(120, settings.episode_window_timeout))),
      min_messages_(static_cast<std::size_t>(std::max(1, settings.episode_min_messages))),
      max_messages_(static_cast<std::size_t>(std::max({settings.episode_min_messages,
                                                       settings.episode_window_max_messages,
                                                       5}))),
      sweep_interval_(std::chrono::seconds(std::max(60, settings.episode_monitor_interval_seconds))) {}

void EpisodeMonitor::track_message(const services::MessageRecord& record) {
    if (!settings_.auto_create_episodes) {
        return;
    }
    if (!should_capture_role(record.role)) {
        return;
    }

    WindowKey key{record.chat_id, record.thread_id};
    auto& window = windows_[key];
    window.last_activity = record.timestamp;
    if (window.messages.empty()) {
        window.messages.reserve(max_messages_);
    }
    window.messages.push_back(record);
    if (record.user_id > 0) {
        window.participants.insert(record.user_id);
    }

    if (window.messages.size() >= max_messages_) {
        finalize_window(key, window);
        windows_.erase(key);
    }
}

void EpisodeMonitor::tick() {
    if (!settings_.auto_create_episodes) {
        return;
    }
    const auto now = now_steady();
    if (now < next_sweep_) {
        return;
    }
    next_sweep_ = now + sweep_interval_;

    std::vector<WindowKey> to_remove;
    to_remove.reserve(windows_.size());

    for (auto& [key, window] : windows_) {
        if (window.messages.empty()) {
            to_remove.push_back(key);
            continue;
        }
        const auto last_activity = window.last_activity;
        const auto inactive_for = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now() - last_activity
        );
        if (inactive_for >= window_timeout_) {
            finalize_window(key, window);
            to_remove.push_back(key);
        }
    }

    for (const auto& key : to_remove) {
        windows_.erase(key);
    }
}

bool EpisodeMonitor::should_capture_role(const std::string& role) const {
    static const std::array<std::string_view, 3> allowed = {"user", "assistant", "model"};
    return std::any_of(allowed.begin(), allowed.end(), [&](std::string_view token) {
        return role == token;
    });
}

void EpisodeMonitor::finalize_window(const WindowKey& key, Window& window) {
    if (window.messages.size() < min_messages_) {
        return;
    }

    const auto summary = build_summary(window);
    if (summary.empty()) {
        return;
    }
    const auto topic = build_topic(window);

    std::vector<std::int64_t> message_ids;
    message_ids.reserve(window.messages.size());
    for (const auto& message : window.messages) {
        if (message.id > 0) {
            message_ids.push_back(message.id);
        }
    }

    if (message_ids.empty()) {
        return;
    }

    std::vector<std::int64_t> participants(window.participants.begin(), window.participants.end());
    std::sort(participants.begin(), participants.end());

    try {
        const auto episode_id = episode_store_.create_episode(
            key.chat_id,
            key.thread_id,
            topic,
            summary,
            message_ids,
            participants,
            settings_.episode_min_importance
        );
        spdlog::info("EpisodeMonitor created episode {} for chat {}", episode_id, key.chat_id);
    } catch (const std::exception& ex) {
        spdlog::warn("Failed to store episode for chat {}: {}", key.chat_id, ex.what());
    }
}

std::string EpisodeMonitor::build_topic(const Window& window) const {
    for (const auto& message : window.messages) {
        if (message.role == "user" && !message.text.empty()) {
            auto topic = message.text.substr(0, std::min<std::size_t>(80, message.text.size()));
            return topic;
        }
    }
    if (!window.messages.empty()) {
        return window.messages.front().text.substr(
            0, std::min<std::size_t>(80, window.messages.front().text.size())
        );
    }
    return "Розмова";
}

std::string EpisodeMonitor::build_summary(const Window& window) const {
    std::ostringstream oss;
    std::size_t included = 0;
    for (const auto& message : window.messages) {
        if (message.text.empty()) {
            continue;
        }
        std::string speaker;
        if (message.role == "assistant" || message.role == "model") {
            speaker = "Гряґ";
        } else {
            speaker = "Користувач";
        }
        oss << speaker << ": " << message.text << "\n";
        if (++included >= 6) {
            break;
        }
    }
    auto text = oss.str();
    if (text.size() > 900) {
        text.resize(900);
        text.append("…");
    }
    return text;
}

}  // namespace gryag::services::background
