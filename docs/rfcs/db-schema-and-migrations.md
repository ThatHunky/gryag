# RFC: DB Schema and Migrations Alignment

Status: Proposed

Problem
- Code initializes and queries PostgreSQL (`app/main.py` uses `app.infrastructure.db_utils`, `asyncpg` in search), but `db/schema.sql` is SQLite-oriented (e.g., `PRAGMA`, `fts5`, `rowid`, `porter unicode61`). Mismatch risks runtime errors and divergent behavior.

Evidence
- PostgreSQL usage: `app/main.py` (init_database, get_db_connection), `app/services/context/hybrid_search.py` (`asyncpg`, Postgres-specific query, `to_tsquery`, `ts_rank_cd`), `app/infrastructure/db_utils.py`.
- SQLite-specific schema: `db/schema.sql` (`PRAGMA`, `CREATE VIRTUAL TABLE ... fts5`, triggers referencing `rowid`).

Options
1. Standardize on PostgreSQL only; port schema to Postgres equivalents (GIN/GIST, tsvector).
2. Maintain dual backends; provide two schemas and an abstraction layer.
3. Migrate to SQLite only (contradicts current Postgres code paths).

Recommendation
- Adopt (1). Provide a Postgres-first schema and migrations (Alembic), map FTS5 to Postgres `tsvector` + `to_tsvector` and GIN index, replace triggers with Postgres triggers. Document migration path from existing SQLite DB if needed.

Impact
- Removes runtime inconsistencies, unlocks Postgres features (concurrency, SQL, indexes).

Effort
- M (schema port + migrations + tests).

Risks
- Data migration complexity from existing SQLite databases.

Acceptance Criteria
- Postgres schema and Alembic migrations exist; FTS-based code paths use `tsvector` with GIN indexes.
- All DB access tests pass on Postgres; README/docs updated with `DATABASE_URL` usage.


