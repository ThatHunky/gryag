#include "gryag/services/tools/polls_tool.hpp"

#include <spdlog/fmt/fmt.h>
#include <spdlog/spdlog.h>

namespace gryag::services::tools {

namespace {

constexpr int kMaxOptions = 10;
constexpr int kMinOptions = 2;

std::vector<std::string> normalize_options(const nlohmann::json& options_json) {
    std::vector<std::string> options;
    for (const auto& opt : options_json) {
        if (!opt.is_string()) {
            continue;
        }
        auto text = opt.get<std::string>();
        if (text.empty()) {
            continue;
        }
        if (text.size() > 100) {
            text = text.substr(0, 100);
        }
        options.push_back(text);
    }
    return options;
}

}  // namespace

PollState& PollsManager::require_poll(const std::string& poll_id) {
    auto it = polls_.find(poll_id);
    if (it == polls_.end()) {
        throw std::runtime_error("Опитування не знайдено");
    }
    return it->second;
}

std::string PollsManager::make_poll_id(std::int64_t chat_id,
                                       std::optional<std::int64_t> thread_id) {
    return fmt::format("poll_{}_{}", chat_id, thread_id.value_or(0));
}

nlohmann::json PollsManager::create_poll(const nlohmann::json& args) {
    const auto chat_id = args.value("chat_id", 0LL);
    const auto creator_id = args.value("creator_id", 0LL);
    const auto thread_id = args.contains("thread_id") && !args["thread_id"].is_null()
        ? std::optional<std::int64_t>(args["thread_id"].get<std::int64_t>())
        : std::optional<std::int64_t>{};
    const auto question = args.value("question", std::string{});
    const auto poll_type = args.value("poll_type", std::string{"regular"});

    if (chat_id == 0 || creator_id == 0 || question.empty()) {
        throw std::runtime_error("Відсутні обов'язкові параметри опитування");
    }

    const auto options = normalize_options(args.value("options", nlohmann::json::array()));
    if (options.size() < kMinOptions) {
        throw std::runtime_error("Опитування повинно мати принаймні 2 варіанти");
    }
    if (options.size() > kMaxOptions) {
        throw std::runtime_error("Опитування може мати максимум 10 варіантів");
    }
    if (question.size() > 200) {
        throw std::runtime_error("Питання занадто довге (макс 200 символів)");
    }

    PollState state;
    state.id = make_poll_id(chat_id, thread_id);
    state.chat_id = chat_id;
    state.thread_id = thread_id;
    state.creator_id = creator_id;
    state.question = question;
    state.allow_multiple = (poll_type == "multiple");
    state.is_anonymous = (poll_type == "anonymous");

    for (const auto& option_text : options) {
        state.options.push_back(PollOption{option_text, 0});
    }

    if (args.contains("duration_hours") && args["duration_hours"].is_number_integer()) {
        const int hours = args["duration_hours"].get<int>();
        if (hours > 0) {
            state.expires_at = std::chrono::system_clock::now() + std::chrono::hours(hours);
        }
    }

    std::lock_guard lock(mutex_);
    polls_[state.id] = state;

    return nlohmann::json{{"success", true}, {"poll_id", state.id}};
}

nlohmann::json PollsManager::vote(const nlohmann::json& args) {
    const auto poll_id = args.value("poll_id", std::string{});
    const auto voter = args.value("user_id", 0LL);
    if (poll_id.empty() || voter == 0) {
        throw std::runtime_error("Відсутні параметри голосування");
    }

    std::vector<int> selected;
    const std::vector<std::string> array_keys{"selected_options", "options"};
    for (const auto& key : array_keys) {
        if (!args.contains(key) || !args[key].is_array()) {
            continue;
        }
        for (const auto& opt : args[key]) {
            if (opt.is_number_integer()) {
                selected.push_back(opt.get<int>());
            }
        }
    }
    if (selected.empty() && args.contains("option") && args["option"].is_number_integer()) {
        selected.push_back(args["option"].get<int>());
    }

    if (selected.empty()) {
        throw std::runtime_error("Не обрано варіант для голосування");
    }

    std::lock_guard lock(mutex_);
    auto& poll = require_poll(poll_id);
    if (poll.is_closed) {
        throw std::runtime_error("Опитування вже закрите");
    }
    if (poll.expires_at && std::chrono::system_clock::now() > *poll.expires_at) {
        poll.is_closed = true;
        throw std::runtime_error("Опитування завершено");
    }

    if (!poll.allow_multiple && selected.size() > 1) {
        throw std::runtime_error("Опитування дозволяє лише один варіант");
    }

    for (auto index : selected) {
        if (index < 0 || index >= static_cast<int>(poll.options.size())) {
            throw std::runtime_error("Невірний номер варіанту");
        }
    }

    // reset previous votes if necessary
    if (!poll.allow_multiple) {
        for (auto& option : poll.options) {
            // remove previous vote counts for this user
            // simple approach: recount from scratch
            option.votes = 0;
        }
        poll.votes_by_user.clear();
    }

    poll.votes_by_user[voter] = selected;
    for (auto& option : poll.options) {
        option.votes = 0;
    }
    for (const auto& [user, votes] : poll.votes_by_user) {
        (void)user;
        for (auto idx : votes) {
            if (idx >= 0 && idx < static_cast<int>(poll.options.size())) {
                poll.options[idx].votes += 1;
            }
        }
    }

    return nlohmann::json{{"success", true}, {"poll_id", poll_id}};
}

nlohmann::json PollsManager::results(const nlohmann::json& args) {
    const auto poll_id = args.value("poll_id", std::string{});
    if (poll_id.empty()) {
        throw std::runtime_error("Потрібно вказати poll_id");
    }
    std::lock_guard lock(mutex_);
    auto& poll = require_poll(poll_id);

    nlohmann::json options = nlohmann::json::array();
    int total_votes = 0;
    for (const auto& option : poll.options) {
        total_votes += option.votes;
    }

    for (std::size_t i = 0; i < poll.options.size(); ++i) {
        const auto& option = poll.options[i];
        double percentage = total_votes == 0 ? 0.0 : (static_cast<double>(option.votes) / total_votes) * 100.0;
        options.push_back({
            {"index", static_cast<int>(i)},
            {"text", option.text},
            {"votes", option.votes},
            {"percentage", percentage}
        });
    }

    return nlohmann::json{{"success", true},
                          {"poll_id", poll.id},
                          {"question", poll.question},
                          {"options", options},
                          {"total_votes", total_votes},
                          {"allow_multiple", poll.allow_multiple}};
}

void register_polls_tool(ToolRegistry& registry) {
    auto manager = std::make_shared<PollsManager>();

    registry.register_tool(
        ToolDefinition{
            .name = "polls",
            .description = "Створення опитувань, голосування та перегляд результатів",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"action", {
                        {"type", "string"},
                        {"enum", {"create", "vote", "results"}},
                        {"description", "Дія: create, vote або results"}
                    }},
                    {"chat_id", {
                        {"type", "integer"},
                        {"description", "ID чату, де створюється опитування"}
                    }},
                    {"thread_id", {
                        {"type", "integer"},
                        {"description", "ID треду (опційно)"}
                    }},
                    {"creator_id", {
                        {"type", "integer"},
                        {"description", "ID користувача, який створює опитування"}
                    }},
                    {"question", {
                        {"type", "string"},
                        {"description", "Текст питання"}
                    }},
                    {"options", {
                        {"type", "array"},
                        {"items", {{"type", "string"}}},
                        {"description", "Варіанти відповіді (для створення опитування)"}
                    }},
                    {"poll_type", {
                        {"type", "string"},
                        {"enum", {"regular", "multiple", "anonymous"}},
                        {"description", "Тип опитування"}
                    }},
                    {"duration_hours", {
                        {"type", "integer"},
                        {"description", "Тривалість опитування в годинах"}
                    }},
                    {"poll_id", {
                        {"type", "string"},
                        {"description", "Ідентифікатор опитування для голосування/результатів"}
                    }},
                    {"user_id", {
                        {"type", "integer"},
                        {"description", "ID користувача, який голосує"}
                    }},
                    {"option", {
                        {"type", "integer"},
                        {"description", "Обраний варіант (для одиночного голосу)"}
                    }},
                    {"selected_options", {
                        {"type", "array"},
                        {"items", {{"type", "integer"}}},
                        {"description", "Обрані варіанти (для мультивибору)"}
                    }}
                }},
                {"required", {"action"}}
            }
        },
        [manager](const nlohmann::json& args, ToolContext&) {
            const auto action = args.value("action", std::string{"create"});
            if (action == "create") {
                return manager->create_poll(args);
            }
            if (action == "vote") {
                return manager->vote(args);
            }
            if (action == "results") {
                return manager->results(args);
            }
            throw std::runtime_error("Невідома дія опитування");
        }
    );
}

}  // namespace gryag::services::tools
