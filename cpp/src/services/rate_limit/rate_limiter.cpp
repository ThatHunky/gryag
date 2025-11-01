#include "gryag/services/rate_limit/rate_limiter.hpp"

namespace gryag::services::rate_limit {

RateLimiter::RateLimiter(std::size_t max_requests_per_window,
                         std::chrono::minutes window)
    : max_requests_per_window_(max_requests_per_window), window_(window) {}

bool RateLimiter::allow(std::int64_t user_id) {
    const auto now = std::chrono::system_clock::now();
    auto& entry = entries_[user_id];
    if (entry.window_start + window_ < now) {
        entry.window_start = now;
        entry.count = 0;
    }

    if (entry.count >= max_requests_per_window_) {
        return false;
    }

    ++entry.count;
    return true;
}

}  // namespace gryag::services::rate_limit
