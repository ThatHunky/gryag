#pragma once

#include "gryag/core/settings.hpp"
#include "gryag/services/context_store.hpp"
#include "gryag/infrastructure/sqlite.hpp"
#include "gryag/services/gemini/gemini_client.hpp"
#include "gryag/services/persona/persona_loader.hpp"
#include "gryag/services/prompt/system_prompt_manager.hpp"
#include "gryag/services/tools/tool.hpp"
#include "gryag/services/rate_limit/rate_limiter.hpp"
#include "gryag/services/rate_limit/feature_rate_limiter.hpp"
#include "gryag/services/media/media_handler.hpp"
#include "gryag/infrastructure/redis.hpp"

#include <memory>

namespace gryag::services {
class TriggerDetector;
class UserProfileStore;
}

namespace gryag::services::context {
class MultiLevelContextManager;
class EpisodicMemoryStore;
}

namespace gryag::services::background {
class EpisodeMonitor;
}

namespace gryag::repositories {
class MemoryRepository;
}

namespace gryag::handlers {

struct HandlerContext {
    core::Settings* settings = nullptr;
    services::ContextStore* context_store = nullptr;
    services::context::MultiLevelContextManager* multi_level_context = nullptr;
    services::context::EpisodicMemoryStore* episodic_memory = nullptr;
    services::gemini::GeminiClient* gemini = nullptr;
    services::tools::ToolRegistry* tools = nullptr;
    services::persona::PersonaLoader* persona_loader = nullptr;
    services::prompt::SystemPromptManager* prompt_manager = nullptr;
    services::background::EpisodeMonitor* episode_monitor = nullptr;
    services::rate_limit::RateLimiter* rate_limiter = nullptr;
    services::rate_limit::FeatureRateLimiter* feature_rate_limiter = nullptr;
    services::media::MediaHandler* media_handler = nullptr;
    services::TriggerDetector* trigger_detector = nullptr;
    services::UserProfileStore* profile_store = nullptr;
    repositories::MemoryRepository* memory_repository = nullptr;
    std::shared_ptr<gryag::infrastructure::SQLiteConnection> connection;
    gryag::infrastructure::RedisClient* redis = nullptr;
};

}  // namespace gryag::handlers
