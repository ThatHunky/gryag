set(GRYAG_CPP_SOURCES
    main.cpp
    core/application.cpp
    core/logging.cpp
    core/settings.cpp
    infrastructure/sqlite.cpp
    infrastructure/redis.cpp
    services/context_store.cpp
    services/context/multi_level_context_manager.cpp
    services/context/sqlite_hybrid_search_engine.cpp
    services/context/episodic_memory_store.cpp
    services/gemini/gemini_client.cpp
    services/persona/persona_loader.cpp
    services/background/donation_scheduler.cpp
    services/background/retention_pruner.cpp
    services/background/episode_monitor.cpp
    services/background/resource_monitor.cpp
    services/prompt/system_prompt_manager.cpp
    services/tools/tool.cpp
    services/tools/calculator_tool.cpp
    services/tools/weather_tool.cpp
    services/tools/currency_tool.cpp
    services/tools/polls_tool.cpp
    services/tools/search_tool.cpp
    services/tools/search_messages_tool.cpp
    services/tools/image_generation_tool.cpp
    services/tools/memory_tools.cpp
    services/tools/default_tools.cpp
    services/rate_limit/rate_limiter.cpp
    services/rate_limit/feature_rate_limiter.cpp
    services/media/media_handler.cpp
    services/triggers.cpp
    services/user_profile_store.cpp
    repositories/memory_repository.cpp
    handlers/chat_handler.cpp
    handlers/admin_handler.cpp
    handlers/chat_admin_handler.cpp
    handlers/profile_handler.cpp
    handlers/prompt_admin_handler.cpp
    telegram/client.cpp
)

add_executable(gryag-bot ${GRYAG_CPP_SOURCES})

target_include_directories(gryag-bot
    PRIVATE
        ${CMAKE_CURRENT_LIST_DIR}/../include
)

find_package(Threads REQUIRED)

# Link third-party libraries provided either by FetchContent or external package manager.
target_link_libraries(gryag-bot
    PRIVATE
        spdlog::spdlog
        nlohmann_json::nlohmann_json
        cpr::cpr
        SQLiteCpp
        sqlite3
        Threads::Threads
)

if (UNIX)
    target_link_libraries(gryag-bot PRIVATE pthread)
endif()

set_target_properties(gryag-bot PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
)
