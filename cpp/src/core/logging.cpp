#include "gryag/core/logging.hpp"

#include <filesystem>
#include <memory>
#include <spdlog/async.h>
#include <spdlog/sinks/daily_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

namespace fs = std::filesystem;

namespace gryag::core {

namespace {

void ensure_log_directory() {
    const auto log_dir = fs::path{"logs"};
    std::error_code ec;
    fs::create_directories(log_dir, ec);
}

}  // namespace

void setup_logging(const Settings&) {
    ensure_log_directory();

    spdlog::init_thread_pool(8192, 1);

    auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
    console_sink->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] %v");

    auto daily_sink = std::make_shared<spdlog::sinks::daily_file_sink_mt>(
        "logs/gryag_cpp.log", 0, 0
    );
    daily_sink->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%l] %v");

    std::vector<spdlog::sink_ptr> sinks{console_sink, daily_sink};

    auto logger = std::make_shared<spdlog::async_logger>(
        "gryag",
        sinks.begin(),
        sinks.end(),
        spdlog::thread_pool(),
        spdlog::async_overflow_policy::block
    );

    spdlog::set_default_logger(logger);
    spdlog::set_level(spdlog::level::info);
    spdlog::flush_on(spdlog::level::info);
}

}  // namespace gryag::core
