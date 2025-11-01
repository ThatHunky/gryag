cmake_minimum_required(VERSION 3.25)

project(gryag_cpp
    VERSION 0.1.0
    DESCRIPTION "C++ implementation of the gryag Telegram bot"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(GRYAG_ENABLE_TESTS "Build gryag C++ tests" ON)
option(GRYAG_USE_CONAN "Use Conan dependency manager" OFF)
option(GRYAG_USE_VCPKG "Use vcpkg dependency manager" OFF)

include(GNUInstallDirs)
include(FetchContent)

# --- Dependencies ------------------------------------------------------------
# The project can use system packages (Conan/vcpkg). When not provided, we fetch
# minimal upstream sources to get started quickly. These targets can be swapped
# out later without touching business logic files.

if (NOT GRYAG_USE_CONAN AND NOT GRYAG_USE_VCPKG)
    message(STATUS "Using FetchContent to provide third-party dependencies")

    # Build all fetched third-party libraries as static to avoid
    # runtime .so dependencies in the final container image.
    set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)

    # spdlog
    FetchContent_Declare(spdlog
        GIT_REPOSITORY https://github.com/gabime/spdlog.git
        GIT_TAG        v1.13.0
    )
    FetchContent_MakeAvailable(spdlog)

    # nlohmann json
    FetchContent_Declare(nlohmann_json
        GIT_REPOSITORY https://github.com/nlohmann/json.git
        GIT_TAG        v3.11.3
    )
    FetchContent_MakeAvailable(nlohmann_json)

    # cpr (HTTP client built on libcurl)
    FetchContent_Declare(cpr
        GIT_REPOSITORY https://github.com/libcpr/cpr.git
        GIT_TAG        1.10.5
    )
    set(CPR_USE_SYSTEM_CURL OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(cpr)

    # SQLiteCpp wrapper around sqlite3
    FetchContent_Declare(SQLiteCpp
        GIT_REPOSITORY https://github.com/SRombauts/SQLiteCpp.git
        GIT_TAG        3.3.3
    )
    FetchContent_MakeAvailable(SQLiteCpp)

    # Ensure the internally provided sqlite3 (from SQLiteCpp) has FTS5 enabled.
    # SQLiteCpp builds an internal sqlite3 target named `sqlite3` when
    # SQLITECPP_INTERNAL_SQLITE is ON (default). Add compile definitions there.
    if (TARGET sqlite3)
        message(STATUS "Enabling SQLITE_ENABLE_FTS5 on internal sqlite3")
        target_compile_definitions(sqlite3 PUBLIC SQLITE_ENABLE_FTS5)
    endif()

endif()

add_subdirectory(src)

if (GRYAG_ENABLE_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
