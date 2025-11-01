#include "gryag/services/background/retention_pruner.hpp"

#include <spdlog/spdlog.h>

namespace gryag::services::background {

RetentionPruner::RetentionPruner(services::ContextStore& store, const core::Settings& settings)
    : store_(store),
      settings_(settings),
      next_run_(std::chrono::steady_clock::now()) {}

void RetentionPruner::tick() {
    if (!settings_.retention_enabled) {
        return;
    }
    const auto now = std::chrono::steady_clock::now();
    const auto interval = std::chrono::seconds(settings_.retention_prune_interval_seconds);
    if (now < next_run_) {
        return;
    }
    try {
        store_.prune_expired(settings_);
    } catch (const std::exception& ex) {
        spdlog::error("Retention pruning failed: {}", ex.what());
    }
    next_run_ = now + interval;
}

}  // namespace gryag::services::background

