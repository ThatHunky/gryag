#include "gryag/infrastructure/sqlite.hpp"

#include <SQLiteCpp/Statement.h>
#include <spdlog/spdlog.h>

#include <fstream>
#include <sstream>

namespace gryag::infrastructure {

SQLiteConnection::SQLiteConnection(std::string path)
    : path_(std::move(path)),
      database_(std::make_shared<SQLite::Database>(path_, SQLite::OPEN_READWRITE | SQLite::OPEN_CREATE)) {
    enable_wal();
}

SQLite::Database& SQLiteConnection::db() {
    return *database_;
}

void SQLiteConnection::enable_wal() {
    SQLite::Statement pragma(*database_, "PRAGMA journal_mode=WAL;");
    while (pragma.executeStep()) {
        // no-op; ensures statement is evaluated
    }
    SQLite::Statement fk(*database_, "PRAGMA foreign_keys=ON;");
    while (fk.executeStep()) {}
}

void SQLiteConnection::execute_script(const std::string& script) {
    database_->exec(script.c_str());
}

}  // namespace gryag::infrastructure
