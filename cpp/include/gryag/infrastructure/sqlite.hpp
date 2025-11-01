#pragma once

#include <SQLiteCpp/Database.h>
#include <memory>
#include <string>

namespace gryag::infrastructure {

class SQLiteConnection {
public:
    explicit SQLiteConnection(std::string path);

    SQLite::Database& db();
    const std::string& path() const { return path_; }

    void enable_wal();
    void execute_script(const std::string& script);

private:
    std::string path_;
    std::shared_ptr<SQLite::Database> database_;
};

}  // namespace gryag::infrastructure
