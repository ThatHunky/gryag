#pragma once

#include <chrono>
#include <cstdint>
#include <unordered_map>

namespace gryag::services::rate_limit {

class RateLimiter {
public:
    explicit RateLimiter(std::size_t max_requests_per_window = 20,
                         std::chrono::minutes window = std::chrono::minutes{60});

    bool allow(std::int64_t user_id);

private:
    struct Entry {
        std::size_t count = 0;
        std::chrono::system_clock::time_point window_start;
    };

    std::size_t max_requests_per_window_;
    std::chrono::minutes window_;
    std::unordered_map<std::int64_t, Entry> entries_;
};

}  // namespace gryag::services::rate_limit
