# Scripts

This directory contains utility scripts for the gryag project, organized by purpose.

## Directory Structure

- **migrations/** - Database schema migrations and data transformations
  - `add_embedding_column.py` - Adds embedding support to messages table
  - `apply_schema.py` - Applies the canonical schema from `db/schema.sql`
  - `migrate_gemini_sdk.py` - Migration script for Google Gemini SDK upgrade
  - `migrate_phase1.py` - Phase 1 database migration
  - `fix_bot_profiles_constraint.py` - Fixes UNIQUE constraint in bot_profiles table

- **diagnostics/** - Diagnostic and inspection tools
  - `diagnose.py` - General diagnostic tool for troubleshooting
  - `check_phase3_ready.py` - Verifies Phase 3 readiness

- **tests/** - Integration and verification test scripts
  - `test_bot_learning_integration.py` - Bot self-learning integration tests
  - `test_hybrid_search.py` - Hybrid search engine tests
  - `test_integration.py` - General integration tests
  - `test_kyiv_timezone.py` - Timezone handling tests
  - `test_memory_tools_phase5.py` - Phase 5 memory tools tests
  - `test_multi_level_context.py` - Multi-level context manager tests
  - `test_phase3.py` - Phase 3 feature tests
  - `test_timestamp_feature.py` - Timestamp feature tests
  - `test_timezone_solution.py` - Timezone solution tests
  - `verify_multimodal.py` - Multimodal capabilities verification

- **verification/** - Shell scripts for verifying features and fixes
  - `verify_bot_self_learning.sh` - Verifies bot self-learning system
  - `verify_critical_fixes.sh` - Verifies critical bug fixes
  - `verify_learning.sh` - Verifies learning infrastructure
  - `verify_model_capabilities.sh` - Verifies model capability detection
  - `setup.sh` - Initial project setup script
  - `download_model.sh` - Downloads local LLM models (deprecated, kept for reference)
  - `verify_search_grounding_update.sh` - Verifies search grounding configuration
  - `verify_throttle_removal.sh` - Verifies throttle system removal

- **deprecated/** - Old scripts kept for reference (not actively used)
  - `main.py` - Deprecated compatibility shim (use `python -m app.main`)
  - `gemini_client.py` - Old Gemini client (replaced by `app/services/gemini.py`)
  - `persona.py` - Old persona file (replaced by `app/persona.py`)

- **Root scripts/** - Active utility scripts
  - `cleanup_logs.py` - Cleans old log files
  - `reset_database.py` - Wipes the SQLite database and reapplies `db/schema.sql`
  - `remove_throttle_tables.py` - Removes throttle-related database tables

## Usage

### Running Migrations

```bash
# Apply canonical schema
python scripts/migrations/apply_schema.py

# Add embedding column (if needed)
python scripts/migrations/add_embedding_column.py
```

### Running Tests

```bash
# Run specific test
python scripts/tests/test_hybrid_search.py

# Run all tests (use pytest from root)
pytest tests/
```

### Running Diagnostics

```bash
# General diagnostics
python scripts/diagnostics/diagnose.py

# Check Phase 3 readiness
python scripts/diagnostics/check_phase3_ready.py
```

### Running Verification Scripts

```bash
# Verify bot self-learning
bash scripts/verification/verify_bot_self_learning.sh

# Verify critical fixes
bash scripts/verification/verify_critical_fixes.sh
```

## Notes

- **Migration scripts** should be run carefully - they modify the database
- **Test scripts** in this folder are integration tests; unit tests live in `tests/`
- **Deprecated scripts** are kept for historical reference only
- Always check script contents before running to understand what they do
