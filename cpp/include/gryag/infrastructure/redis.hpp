#pragma once

#include <chrono>
#include <mutex>
#include <string>
#include <unordered_map>

namespace gryag::infrastructure {

class RedisClient {
public:
    RedisClient() = default;

    void connect(const std::string& url);
    bool is_enabled() const { return enabled_; }

    bool try_lock(const std::string& key, std::chrono::seconds ttl);
    void release_lock(const std::string& key);
    bool allow(const std::string& key, std::size_t max_requests, std::chrono::seconds window);

private:
    struct LockEntry {
        std::chrono::steady_clock::time_point expires_at;
    };

    struct CounterEntry {
        std::size_t count = 0;
        std::chrono::steady_clock::time_point window_end;
    };

    void purge_expired();

    bool enabled_ = false;
    std::mutex mutex_;
    std::unordered_map<std::string, LockEntry> locks_;
    std::unordered_map<std::string, CounterEntry> counters_;
};

}  // namespace gryag::infrastructure
