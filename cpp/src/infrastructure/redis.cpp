#include "gryag/infrastructure/redis.hpp"

#include <spdlog/spdlog.h>

#include <chrono>

namespace gryag::infrastructure {

void RedisClient::connect(const std::string& url) {
    if (url.empty()) {
        spdlog::info("Redis not configured; falling back to in-process locks");
        enabled_ = false;
        return;
    }
    enabled_ = true;
    spdlog::info("Redis emulation enabled (url={})", url);
}

void RedisClient::purge_expired() {
    const auto now = std::chrono::steady_clock::now();
    for (auto it = locks_.begin(); it != locks_.end();) {
        if (it->second.expires_at <= now) {
            it = locks_.erase(it);
        } else {
            ++it;
        }
    }
    for (auto it = counters_.begin(); it != counters_.end();) {
        if (it->second.window_end <= now) {
            it = counters_.erase(it);
        } else {
            ++it;
        }
    }
}

bool RedisClient::try_lock(const std::string& key, std::chrono::seconds ttl) {
    std::lock_guard lock(mutex_);
    purge_expired();
    const auto now = std::chrono::steady_clock::now();
    if (locks_.contains(key)) {
        return false;
    }
    locks_[key] = LockEntry{.expires_at = now + ttl};
    return true;
}

void RedisClient::release_lock(const std::string& key) {
    std::lock_guard lock(mutex_);
    locks_.erase(key);
}

bool RedisClient::allow(const std::string& key, std::size_t max_requests, std::chrono::seconds window) {
    std::lock_guard lock(mutex_);
    purge_expired();
    const auto now = std::chrono::steady_clock::now();
    auto& entry = counters_[key];
    if (entry.count == 0 || entry.window_end <= now) {
        entry.count = 0;
        entry.window_end = now + window;
    }
    if (entry.count >= max_requests) {
        return false;
    }
    ++entry.count;
    return true;
}

}  // namespace gryag::infrastructure
