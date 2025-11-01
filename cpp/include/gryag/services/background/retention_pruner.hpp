#pragma once

#include "gryag/core/settings.hpp"
#include "gryag/services/context_store.hpp"

#include <chrono>

namespace gryag::services::background {

class RetentionPruner {
public:
    RetentionPruner(services::ContextStore& store, const core::Settings& settings);

    void tick();

private:
    services::ContextStore& store_;
    const core::Settings& settings_;
    std::chrono::steady_clock::time_point next_run_;
};

}  // namespace gryag::services::background

