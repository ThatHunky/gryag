#pragma once

#include <chrono>

namespace gryag::services::background {

class ResourceMonitor {
public:
    ResourceMonitor();

    void tick();

private:
    std::chrono::steady_clock::time_point next_log_;
    std::chrono::steady_clock::duration interval_;

    double current_memory_mb() const;
};

}  // namespace gryag::services::background

