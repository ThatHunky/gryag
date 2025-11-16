#!/usr/bin/env sh
set -euo pipefail

# Optional: run migrations based on env flag (app honors RUN_DB_MIGRATIONS)
echo "[entrypoint] starting bot..."
exec python -m app.main


