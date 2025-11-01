#pragma once

#include "gryag/core/settings.hpp"

#include <memory>

namespace gryag::core {

class Application {
public:
    Application() = default;

    int run();
};

}  // namespace gryag::core
