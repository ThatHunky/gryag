#include "gryag/services/background/resource_monitor.hpp"

#include <spdlog/spdlog.h>

#ifdef __linux__
#include <unistd.h>
#endif

#include <fstream>

namespace gryag::services::background {

ResourceMonitor::ResourceMonitor()
    : next_log_(std::chrono::steady_clock::now()),
      interval_(std::chrono::minutes(5)) {}

void ResourceMonitor::tick() {
    const auto now = std::chrono::steady_clock::now();
    if (now < next_log_) {
        return;
    }
    next_log_ = now + interval_;

    const auto memory_mb = current_memory_mb();
    if (memory_mb >= 0.0) {
        spdlog::info("ResourceMonitor: RSS {:.2f} MiB", memory_mb);
    } else {
        spdlog::debug("ResourceMonitor: memory metrics unavailable on this platform");
    }
}

double ResourceMonitor::current_memory_mb() const {
#ifdef __linux__
    std::ifstream statm("/proc/self/statm");
    if (!statm.is_open()) {
        return -1.0;
    }
    long pages = 0;
    statm >> pages;
    const long page_size = sysconf(_SC_PAGESIZE);
    if (pages <= 0 || page_size <= 0) {
        return -1.0;
    }
    const double bytes = static_cast<double>(pages) * static_cast<double>(page_size);
    return bytes / (1024.0 * 1024.0);
#else
    return -1.0;
#endif
}

}  // namespace gryag::services::background

