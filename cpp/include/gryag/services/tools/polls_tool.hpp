#pragma once

#include "gryag/services/tools/tool.hpp"

#include <chrono>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace gryag::services::tools {

struct PollOption {
    std::string text;
    int votes = 0;
};

struct PollState {
    std::string id;
    std::int64_t chat_id = 0;
    std::optional<std::int64_t> thread_id;
    std::int64_t creator_id = 0;
    std::string question;
    std::vector<PollOption> options;
    bool allow_multiple = false;
    bool is_anonymous = false;
    bool is_closed = false;
    std::optional<std::chrono::system_clock::time_point> expires_at;
    std::unordered_map<std::int64_t, std::vector<int>> votes_by_user;
};

class PollsManager {
public:
    PollsManager() = default;

    nlohmann::json create_poll(const nlohmann::json& args);
    nlohmann::json vote(const nlohmann::json& args);
    nlohmann::json results(const nlohmann::json& args);

private:
    PollState& require_poll(const std::string& poll_id);
    static std::string make_poll_id(std::int64_t chat_id, std::optional<std::int64_t> thread_id);

    std::mutex mutex_;
    std::unordered_map<std::string, PollState> polls_;
};

void register_polls_tool(ToolRegistry& registry);

}  // namespace gryag::services::tools
