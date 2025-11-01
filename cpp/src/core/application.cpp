#include "gryag/core/application.hpp"

#include "gryag/core/logging.hpp"
#include "gryag/infrastructure/sqlite.hpp"
#include "gryag/services/context/multi_level_context_manager.hpp"
#include "gryag/services/context/sqlite_hybrid_search_engine.hpp"
#include "gryag/services/context/episodic_memory_store.hpp"
#include "gryag/services/context_store.hpp"
#include "gryag/services/gemini/gemini_client.hpp"
#include "gryag/services/persona/persona_loader.hpp"
#include "gryag/services/prompt/system_prompt_manager.hpp"
#include "gryag/services/background/donation_scheduler.hpp"
#include "gryag/services/background/episode_monitor.hpp"
#include "gryag/services/background/retention_pruner.hpp"
#include "gryag/services/background/resource_monitor.hpp"
#include "gryag/services/tools/default_tools.hpp"
#include "gryag/services/rate_limit/rate_limiter.hpp"
#include "gryag/services/rate_limit/feature_rate_limiter.hpp"
#include "gryag/services/media/media_handler.hpp"
#include "gryag/services/triggers.hpp"
#include "gryag/services/user_profile_store.hpp"
#include "gryag/repositories/memory_repository.hpp"
#include "gryag/handlers/chat_handler.hpp"
#include "gryag/handlers/admin_handler.hpp"
#include "gryag/handlers/chat_admin_handler.hpp"
#include "gryag/handlers/profile_handler.hpp"
#include "gryag/handlers/prompt_admin_handler.hpp"
#include "gryag/telegram/client.hpp"

#include <spdlog/spdlog.h>
#include <csignal>
#include <memory>
#include <string>
#include <vector>

namespace gryag::core {

int Application::run() {
    try {
        auto settings = Settings::from_env();
        settings.validate();
        setup_logging(settings);

        spdlog::info("Starting gryag C++ bot");

        auto connection = std::make_shared<infrastructure::SQLiteConnection>(settings.db_path);
        services::ContextStore context_store(connection);
        context_store.init();

        services::context::SQLiteHybridSearchEngine hybrid_search(connection);
        services::context::EpisodicMemoryStore episodic_memory(connection);
        episodic_memory.init();

        services::gemini::GeminiClient gemini(settings);
        services::persona::PersonaLoader persona_loader(
            settings.persona_config_path,
            settings.response_templates_path
        );
        services::prompt::SystemPromptManager prompt_manager(connection);

        // Create repositories and services needed for tools
        services::rate_limit::FeatureRateLimiter feature_rate_limiter(connection);
        services::media::MediaHandler media_handler(connection);
        services::UserProfileStore profile_store(connection);
        repositories::MemoryRepository memory_repository(connection);

        services::tools::ToolRegistry tool_registry;
        services::tools::register_default_tools(
            tool_registry,
            settings,
            gemini,
            connection,
            context_store,
            &memory_repository
        );
        services::rate_limit::RateLimiter rate_limiter(
            static_cast<std::size_t>(settings.per_user_per_hour),
            std::chrono::minutes{60}
        );

        std::unique_ptr<infrastructure::RedisClient> redis_client;
        if (settings.use_redis && !settings.redis_url.empty()) {
            redis_client = std::make_unique<infrastructure::RedisClient>();
            redis_client->connect(settings.redis_url);
        }

        services::context::MultiLevelContextManager context_manager(
            settings,
            context_store,
            &hybrid_search,
            &episodic_memory,
            &gemini
        );

        handlers::HandlerContext handler_ctx;
        handler_ctx.settings = &settings;
        handler_ctx.context_store = &context_store;
        handler_ctx.multi_level_context = &context_manager;
        handler_ctx.episodic_memory = &episodic_memory;
        handler_ctx.gemini = &gemini;
        handler_ctx.tools = &tool_registry;
        handler_ctx.persona_loader = &persona_loader;
        handler_ctx.prompt_manager = &prompt_manager;
        handler_ctx.rate_limiter = &rate_limiter;
        handler_ctx.feature_rate_limiter = &feature_rate_limiter;
        handler_ctx.media_handler = &media_handler;
        handler_ctx.profile_store = &profile_store;
        handler_ctx.memory_repository = &memory_repository;
        handler_ctx.connection = connection;
        if (redis_client) {
            handler_ctx.redis = redis_client.get();
        }

        services::background::EpisodeMonitor episode_monitor(settings, episodic_memory, &gemini);
        handler_ctx.episode_monitor = &episode_monitor;

        telegram::TelegramClient telegram_client(settings.telegram_token);

        // Fetch bot identity and initialize trigger detector
        spdlog::info("Fetching bot identity...");
        const auto bot_me = telegram_client.get_me();
        settings.bot_username = bot_me.username;
        settings.bot_id = bot_me.id;

        services::TriggerDetector trigger_detector(settings.trigger_patterns);
        handler_ctx.trigger_detector = &trigger_detector;
        handlers::ChatHandler chat_handler(handler_ctx);
        handlers::AdminHandler admin_handler(handler_ctx);
        handlers::ChatAdminHandler chat_admin_handler(handler_ctx);
        handlers::PromptAdminHandler prompt_admin_handler(handler_ctx);
        handlers::ProfileHandler profile_handler(handler_ctx);

        services::background::DonationScheduler donation_scheduler(connection, settings);
        services::background::RetentionPruner retention_pruner(context_store, settings);
        services::background::ResourceMonitor resource_monitor;

        try {
            telegram_client.set_commands({
                {"start", "Почати спілкування з ботом"},
                {"profile", "Показати мій профіль"},
                {"facts", "Показати факти про користувача"},
                {"donate", "Підтримати бота донатом"},
                {"chatinfo", "Показати ID чату"},
                {"prompt", "Показати активний системний промпт"},
                {"chatfacts", "Показати пам'ять про чат"}
            });
        } catch (const std::exception& ex) {
            spdlog::warn("Failed to set Telegram commands: {}", ex.what());
        }

        std::signal(SIGINT, [](int) {
            spdlog::info("Interrupt received, shutting down");
            std::exit(0);
        });
        std::signal(SIGTERM, [](int) {
            spdlog::info("Terminate signal received, shutting down");
            std::exit(0);
        });

        spdlog::info("Bot is polling Telegram updates");

        while (true) {
            donation_scheduler.tick(telegram_client);
            retention_pruner.tick();
            episode_monitor.tick();
            resource_monitor.tick();

            auto updates = telegram_client.poll_updates(std::chrono::seconds(25));

            // Handle regular messages
            for (const auto& message : updates.messages) {
                if (!message.from.has_value() || message.from->is_bot) {
                    continue;
                }
                if (admin_handler.handle(message, telegram_client)) {
                    continue;
                }
                if (chat_admin_handler.handle(message, telegram_client)) {
                    continue;
                }
                if (prompt_admin_handler.handle(message, telegram_client)) {
                    continue;
                }
                if (profile_handler.handle(message, telegram_client)) {
                    continue;
                }
                chat_handler.handle_update(message, telegram_client);
            }

            // Handle callback queries (button presses)
            for (const auto& callback_query : updates.callback_queries) {
                spdlog::info("Received callback query: data='{}' from user {}",
                           callback_query.data, callback_query.from.id);

                // Route callback queries to appropriate handler based on data prefix
                try {
                    if (callback_query.data.find("facts:") == 0) {
                        // Profile facts pagination
                        profile_handler.handle_callback_query(callback_query, telegram_client);
                    } else {
                        // Default: just acknowledge the callback
                        telegram_client.answer_callback_query(callback_query.id,
                                                             "Кнопка натиснута!", false);
                    }
                } catch (const std::exception& ex) {
                    spdlog::error("Error handling callback query: {}", ex.what());
                    telegram_client.answer_callback_query(callback_query.id,
                                                         "Помилка обробки запиту", true);
                }
            }
        }
    } catch (const std::exception& ex) {
        spdlog::critical("Fatal error: {}", ex.what());
        return 1;
    }

    return 0;
}

}  // namespace gryag::core
