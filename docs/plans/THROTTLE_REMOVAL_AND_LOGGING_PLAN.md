# Throttle Removal and File Logging Implementation Plan

**Date**: October 8, 2025  
**Status**: ✅ **IMPLEMENTED**  
**Estimated Duration**: 2-3 hours  
**Actual Duration**: 1.5 hours

---

## ✅ Implementation Complete!

**See**: [`docs/fixes/THROTTLE_REMOVAL_AND_LOGGING_SUMMARY.md`](../fixes/THROTTLE_REMOVAL_AND_LOGGING_SUMMARY.md) for complete implementation summary.

### Quick Summary

**Phase 1: Throttle Removal** ✅
- Deleted `app/middlewares/throttle.py` (183 lines)
- Removed quota tracking from `ContextStore` (~100 lines)
- Dropped `quotas` and `notices` from schema
- Cleaned configuration (removed `PER_USER_PER_HOUR`, `REDIS_NAMESPACE`)
- **Total removed**: ~350 lines

**Phase 2: File Logging** ✅
- Created `app/core/logging_config.py` (130 lines)
- Added logging configuration to `app/config.py` (35 lines)
- Updated `app/main.py` to use new logging system
- Created migration and cleanup scripts
- **Total added**: ~260 lines

**Net Result**: -90 lines of code, cleaner architecture, better logging!

---

## Original Plan Below

(Plan content follows...)

## Overview

This plan covers:
1. **Complete removal of throttling system** - Remove rate limiting entirely
2. **File-based logging with rotation** - Replace console logging with rotating file logs
3. **Automatic log cleanup** - Prevent disk space issues with old logs

**Rationale**:
- Throttling adds complexity without clear benefit in current use case
- File logging enables better debugging and audit trails
- Log rotation prevents disk space exhaustion

---

## Current State Analysis

### Throttling System Components

**Files to modify/remove**:
1. `app/middlewares/throttle.py` (183 lines) - **DELETE**
2. `app/middlewares/__init__.py` - Remove ThrottleMiddleware export
3. `app/main.py` - Remove throttle middleware registration
4. `app/handlers/chat.py` - Remove throttle_blocked/throttle_reason logic
5. `app/services/context_store.py` - Remove quota tracking methods
6. `app/config.py` - Remove throttle-related settings
7. `db/schema.sql` - Remove quotas table

**Database tables to drop**:
- `quotas` table (stores request timestamps)
- `notices` table (tracks throttle notices sent)

**Configuration to remove** (from `app/config.py`):
```python
per_user_per_hour: int = Field(5, alias="PER_USER_PER_HOUR", ge=1)
redis_namespace: str = Field("gryag", alias="REDIS_NAMESPACE")
```

**Handler logic to clean** (from `app/handlers/chat.py`):
- `throttle_blocked` parameter (line 595)
- `throttle_reason` parameter (line 596)
- Quota logging (lines 690-700)
- Throttle check logging (lines 968-976)

**Redis usage for quotas**:
- Remove quota zadd/zremrangebyscore operations
- Keep Redis for other features (if needed)

---

## New Logging System Design

### Architecture

**Logging hierarchy**:
```
logs/
├── gryag.log              # Current log (rotated daily)
├── gryag.log.2025-10-08   # Yesterday's log
├── gryag.log.2025-10-07   # 2 days ago
└── ...                    # Older logs (auto-deleted after 7 days)
```

**Log rotation strategy**:
- **Type**: Time-based rotation (daily at midnight)
- **Retention**: 7 days (configurable via `LOG_RETENTION_DAYS`)
- **Max size**: 10 MB per file (backup rotation if exceeded)
- **Compression**: Optional gzip compression for old logs

**Log format**:
```
2025-10-08 15:30:45,123 - INFO - app.handlers.chat - [chat_id=123 user_id=456] Message addressed to bot
```

**Structured logging** (JSON mode optional):
```json
{
  "timestamp": "2025-10-08T15:30:45.123Z",
  "level": "INFO",
  "logger": "app.handlers.chat",
  "message": "Message addressed to bot",
  "extra": {
    "chat_id": 123,
    "user_id": 456
  }
}
```

### Configuration

**New settings** (add to `app/config.py`):
```python
# Logging configuration
log_dir: Path = Field(Path("./logs"), alias="LOG_DIR")
log_level: str = Field("INFO", alias="LOG_LEVEL")
log_format: str = Field(
    "text",  # "text" or "json"
    alias="LOG_FORMAT"
)
log_retention_days: int = Field(7, alias="LOG_RETENTION_DAYS", ge=1, le=90)
log_max_bytes: int = Field(
    10 * 1024 * 1024,  # 10 MB
    alias="LOG_MAX_BYTES",
    ge=1024 * 1024,
    le=100 * 1024 * 1024
)
log_backup_count: int = Field(5, alias="LOG_BACKUP_COUNT", ge=1, le=30)
enable_console_logging: bool = Field(True, alias="ENABLE_CONSOLE_LOGGING")
enable_file_logging: bool = Field(True, alias="ENABLE_FILE_LOGGING")
```

**Environment variables** (add to `.env.example`):
```bash
# Logging Configuration
LOG_DIR=./logs                    # Directory for log files
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT=text                   # text or json
LOG_RETENTION_DAYS=7              # Auto-delete logs older than this
LOG_MAX_BYTES=10485760            # Max size per file (10 MB)
LOG_BACKUP_COUNT=5                # Number of rotated files to keep
ENABLE_CONSOLE_LOGGING=true       # Log to console (stdout/stderr)
ENABLE_FILE_LOGGING=true          # Log to files
```

---

## Implementation Plan

### Phase 1: Remove Throttling System (1 hour)

#### Step 1.1: Database Schema Changes
**File**: `db/schema.sql`

```sql
-- Remove these sections:
-- DROP TABLE IF EXISTS quotas;
-- DROP TABLE IF EXISTS notices;
```

**Migration script**: `scripts/remove_throttle_tables.py`
```python
"""Remove throttle-related database tables."""
import asyncio
import aiosqlite
from pathlib import Path

async def migrate():
    db_path = Path("./gryag.db")
    async with aiosqlite.connect(db_path) as db:
        # Backup first
        await db.execute("VACUUM INTO 'gryag.db.pre-throttle-removal'")
        
        # Drop tables
        await db.execute("DROP TABLE IF EXISTS quotas")
        await db.execute("DROP TABLE IF EXISTS notices")
        
        await db.commit()
        print("✅ Throttle tables removed")

if __name__ == "__main__":
    asyncio.run(migrate())
```

#### Step 1.2: Remove Context Store Methods
**File**: `app/services/context_store.py`

**Methods to delete**:
- `log_request(chat_id, user_id)` - Records quota usage
- `count_requests_last_hour(chat_id, user_id)` - Counts requests
- `recent_request_times(chat_id, user_id, ...)` - Fetches request timestamps
- `should_send_notice(chat_id, user_id, kind, ttl)` - Throttle notice logic
- `reset_quotas(chat_id)` - Admin command for quota reset

**Lines to remove**: Approximately 100-150 lines

#### Step 1.3: Remove Middleware
**File**: `app/middlewares/throttle.py`

**Action**: DELETE entire file

**File**: `app/middlewares/__init__.py`

```python
# Remove this import:
# from app.middlewares.throttle import ThrottleMiddleware
```

#### Step 1.4: Update Main Application
**File**: `app/main.py`

**Remove**:
```python
from app.middlewares.throttle import ThrottleMiddleware  # Line 18

# Remove middleware registration (line 315):
dispatcher.message.middleware(
    ThrottleMiddleware(store, settings, redis_client=redis_client)
)
```

**Simplify middleware order comment**:
```python
# Middleware order:
# 1. ChatMetaMiddleware - Inject services
# 2. ChatFilterMiddleware - Filter blocked chats
# (Throttle removed - no rate limiting)
```

#### Step 1.5: Clean Chat Handler
**File**: `app/handlers/chat.py`

**Remove parameters** (lines 595-596):
```python
throttle_blocked: bool | None = None,
throttle_reason: dict[str, Any] | None = None,
```

**Remove logging extra** (line 678):
```python
# Remove from logging dict:
"throttle_blocked": throttle_blocked,
```

**Remove blocked check** (line 682):
```python
blocked = bool(throttle_blocked)  # Delete
```

**Remove quota logging** (lines 690-700):
```python
# Delete this block:
if not is_admin and not blocked:
    await store.log_request(chat_id, user_id)

if redis_client is not None and redis_quota is not None:
    key, ts = redis_quota
    member = f"{ts}:{message.message_id}"
    try:
        await redis_client.zadd(key, {member: ts})
        await redis_client.expire(key, 3600)
    except Exception as e:
        LOGGER.warning(...)
```

**Remove throttle reason logging** (lines 968-976):
```python
# Delete this block:
if throttle_reason:
    LOGGER.info(
        "Message throttled - skipping Gemini call",
        extra={
            "chat_id": chat_id,
            "user_id": user_id,
            "reason": throttle_reason,
        },
    )
    telemetry.increment_counter("chat.throttled")
    return
```

#### Step 1.6: Update Configuration
**File**: `app/config.py`

**Remove fields**:
```python
per_user_per_hour: int = Field(5, alias="PER_USER_PER_HOUR", ge=1)
redis_namespace: str = Field("gryag", alias="REDIS_NAMESPACE")
```

**File**: `.env.example`

**Remove**:
```bash
PER_USER_PER_HOUR=5
REDIS_NAMESPACE=gryag
```

#### Step 1.7: Update Admin Commands
**File**: `app/handlers/admin.py`

**Remove** (if exists):
- `/gryagreset` command (quota reset)
- Any quota-related admin functionality

#### Step 1.8: Update Documentation
**Files to update**:
- `.github/copilot-instructions.md` - Remove throttle middleware references
- `README.md` - Remove rate limiting from features list
- `docs/CHANGELOG.md` - Add entry for throttle removal

---

### Phase 2: Implement File Logging (1-2 hours)

#### Step 2.1: Create Logging Configuration Module
**New file**: `app/core/logging_config.py` (120 lines)

```python
"""Logging configuration with file rotation and cleanup."""

from __future__ import annotations

import logging
import logging.handlers
import json
from pathlib import Path
from typing import Any

from app.config import Settings


class JSONFormatter(logging.Formatter):
    """Format log records as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields
        if hasattr(record, "extra"):
            log_data["extra"] = record.extra
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(settings: Settings) -> None:
    """
    Configure application logging with rotation and cleanup.
    
    Creates:
    - Console handler (optional)
    - File handler with daily rotation
    - Automatic cleanup of old logs
    """
    # Create logs directory
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))
    root_logger.handlers.clear()  # Remove any existing handlers

    # Formatter
    if settings.log_format == "json":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

    # Console handler
    if settings.enable_console_logging:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler with rotation
    if settings.enable_file_logging:
        log_file = settings.log_dir / "gryag.log"
        
        # Time-based rotation (daily at midnight)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            interval=1,
            backupCount=settings.log_retention_days,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        
        # Also add size-based backup rotation
        file_handler.maxBytes = settings.log_max_bytes
        
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)

    logging.info(
        "Logging configured",
        extra={
            "log_dir": str(settings.log_dir),
            "log_level": settings.log_level,
            "log_format": settings.log_format,
            "console": settings.enable_console_logging,
            "file": settings.enable_file_logging,
            "retention_days": settings.log_retention_days,
        }
    )


def cleanup_old_logs(settings: Settings) -> None:
    """
    Manually remove logs older than retention period.
    
    TimedRotatingFileHandler handles this automatically,
    but this can be called for manual cleanup.
    """
    import time
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=settings.log_retention_days)
    cutoff_timestamp = cutoff.timestamp()

    deleted_count = 0
    for log_file in settings.log_dir.glob("gryag.log.*"):
        # Check modification time
        if log_file.stat().st_mtime < cutoff_timestamp:
            log_file.unlink()
            deleted_count += 1

    if deleted_count > 0:
        logging.info(f"Cleaned up {deleted_count} old log files")
```

#### Step 2.2: Update Main Application
**File**: `app/main.py`

**Replace**:
```python
# OLD:
async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    settings = get_settings()
    # ...

# NEW:
async def main() -> None:
    settings = get_settings()
    
    # Setup logging with rotation and cleanup
    from app.core.logging_config import setup_logging
    setup_logging(settings)
    
    # ...
```

#### Step 2.3: Add Configuration Fields
**File**: `app/config.py`

**Add** (in appropriate section):
```python
# ═══════════════════════════════════════════════════════════════════════════
# Logging Configuration
# ═══════════════════════════════════════════════════════════════════════════

log_dir: Path = Field(Path("./logs"), alias="LOG_DIR")
log_level: str = Field("INFO", alias="LOG_LEVEL")
log_format: str = Field("text", alias="LOG_FORMAT")  # text or json
log_retention_days: int = Field(7, alias="LOG_RETENTION_DAYS", ge=1, le=90)
log_max_bytes: int = Field(
    10 * 1024 * 1024,  # 10 MB
    alias="LOG_MAX_BYTES",
    ge=1024 * 1024,
    le=100 * 1024 * 1024
)
log_backup_count: int = Field(5, alias="LOG_BACKUP_COUNT", ge=1, le=30)
enable_console_logging: bool = Field(True, alias="ENABLE_CONSOLE_LOGGING")
enable_file_logging: bool = Field(True, alias="ENABLE_FILE_LOGGING")

@field_validator("log_level")
@classmethod
def _validate_log_level(cls, v: str) -> str:
    """Validate log level is valid."""
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    v_upper = v.upper()
    if v_upper not in valid_levels:
        raise ValueError(
            f"log_level must be one of {valid_levels}, got '{v}'"
        )
    return v_upper

@field_validator("log_format")
@classmethod
def _validate_log_format(cls, v: str) -> str:
    """Validate log format is valid."""
    valid_formats = {"text", "json"}
    if v not in valid_formats:
        raise ValueError(
            f"log_format must be one of {valid_formats}, got '{v}'"
        )
    return v
```

#### Step 2.4: Update .env.example
**File**: `.env.example`

**Add section**:
```bash
# ═══════════════════════════════════════════════════════════════════
# Logging Configuration
# ═══════════════════════════════════════════════════════════════════

# Directory for log files (created automatically)
LOG_DIR=./logs

# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO

# Log format: text (human-readable) or json (structured)
LOG_FORMAT=text

# Auto-delete logs older than this many days
LOG_RETENTION_DAYS=7

# Maximum size per log file before rotation (bytes)
# Default: 10 MB = 10485760 bytes
LOG_MAX_BYTES=10485760

# Number of rotated backup files to keep
LOG_BACKUP_COUNT=5

# Enable console output (stdout/stderr)
ENABLE_CONSOLE_LOGGING=true

# Enable file logging
ENABLE_FILE_LOGGING=true
```

#### Step 2.5: Add .gitignore Entry
**File**: `.gitignore`

**Add**:
```
# Log files
logs/
*.log
*.log.*
```

#### Step 2.6: Create Log Cleanup Utility
**New file**: `scripts/cleanup_logs.py`

```python
"""Manual log cleanup utility."""
import asyncio
from pathlib import Path
from app.config import get_settings
from app.core.logging_config import cleanup_old_logs

def main():
    settings = get_settings()
    print(f"Cleaning logs older than {settings.log_retention_days} days...")
    cleanup_old_logs(settings)
    print("Done!")

if __name__ == "__main__":
    main()
```

---

### Phase 3: Testing & Verification (30 minutes)

#### Test 1: Throttle Removal Verification
```bash
# 1. Check middleware is not registered
python -c "from app.main import main; import inspect; print(inspect.getsource(main))" | grep -i throttle
# Should return nothing

# 2. Check database schema
sqlite3 gryag.db ".schema quotas"
# Should show: Error: no such table: quotas

# 3. Check handler has no throttle logic
grep -n "throttle" app/handlers/chat.py
# Should show minimal/no results

# 4. Start bot and send messages rapidly (no throttling should occur)
python -m app.main
# Send 10+ messages in 1 minute - all should process
```

#### Test 2: File Logging Verification
```bash
# 1. Check log directory created
ls -la logs/
# Should show: gryag.log

# 2. Check log format
tail -20 logs/gryag.log
# Should show formatted log entries

# 3. Check rotation works
# Wait until midnight or manually trigger:
python -c "
import logging.handlers
from pathlib import Path
handler = logging.handlers.TimedRotatingFileHandler('logs/gryag.log', when='S', interval=1, backupCount=3)
handler.doRollover()
"
ls -la logs/
# Should show: gryag.log, gryag.log.2025-10-08

# 4. Check cleanup works
# Create old fake log
touch logs/gryag.log.2020-01-01
python scripts/cleanup_logs.py
# Old log should be deleted
```

#### Test 3: Performance Check
```bash
# Before: Check current performance
time curl -X POST https://api.telegram.org/bot$TOKEN/sendMessage -d "chat_id=123&text=test"

# After: Compare (should be similar or faster without throttle overhead)
time curl -X POST https://api.telegram.org/bot$TOKEN/sendMessage -d "chat_id=123&text=test"
```

#### Test 4: Log Levels
```bash
# Test different log levels
export LOG_LEVEL=DEBUG
python -m app.main
# Check logs/gryag.log has DEBUG entries

export LOG_LEVEL=WARNING
python -m app.main
# Check logs/gryag.log only has WARNING+ entries
```

---

## Migration Guide for Existing Deployments

### Pre-Migration Checklist
```bash
# 1. Backup database
cp gryag.db gryag.db.backup

# 2. Backup configuration
cp .env .env.backup

# 3. Note current quota settings
grep "PER_USER_PER_HOUR" .env
```

### Migration Steps
```bash
# 1. Pull new code
git pull origin main

# 2. Run migration script
python scripts/remove_throttle_tables.py

# 3. Update .env (add logging config)
# Copy from .env.example

# 4. Restart bot
# Docker: docker-compose restart bot
# Manual: pkill -f "python -m app.main" && python -m app.main &

# 5. Verify logs
tail -f logs/gryag.log
```

### Rollback Plan
```bash
# If issues occur:

# 1. Restore database
cp gryag.db.backup gryag.db

# 2. Restore config
cp .env.backup .env

# 3. Checkout previous commit
git checkout HEAD~1

# 4. Restart bot
```

---

## Documentation Updates

### Files to Update

1. **README.md**
   - Remove "Adaptive rate limiting" from features
   - Add "File-based logging with rotation" to features

2. **.github/copilot-instructions.md**
   - Remove throttle middleware references (lines 20, 33-39)
   - Add logging configuration section

3. **docs/CHANGELOG.md**
   - Add entry:
     ```markdown
     ### 2025-10-08 - Throttle Removal and File Logging
     
     **Breaking Change**: Rate limiting completely removed
     
     **Removed**:
     - ThrottleMiddleware (183 lines)
     - Quota tracking in ContextStore (150 lines)
     - quotas and notices database tables
     - PER_USER_PER_HOUR and REDIS_NAMESPACE config
     
     **Added**:
     - File-based logging with daily rotation
     - Automatic log cleanup (7-day retention default)
     - JSON and text log formats
     - app/core/logging_config.py (120 lines)
     
     **Migration**: Run `python scripts/remove_throttle_tables.py`
     ```

4. **docs/README.md**
   - Add entry for this plan document

---

## Risks and Mitigation

### Risk 1: Spam/Abuse Without Throttling
**Severity**: Medium  
**Mitigation**:
- Monitor logs for suspicious activity patterns
- Can implement lightweight flood detection later if needed
- Admin commands (/gryagban) still available
- Chat filtering still active (whitelist/blacklist mode)

### Risk 2: Database Migration Issues
**Severity**: Low  
**Mitigation**:
- Migration script creates backup automatically
- Tables are dropped (no ALTER needed - safe)
- Rollback plan documented

### Risk 3: Log Disk Space
**Severity**: Low  
**Mitigation**:
- Automatic rotation configured
- 7-day retention (configurable)
- 10 MB max file size
- Manual cleanup script available

### Risk 4: Breaking Existing Deployments
**Severity**: Medium  
**Mitigation**:
- Clear migration guide provided
- Rollback plan documented
- Database backup enforced
- Configuration changes documented

---

## Success Criteria

✅ **Throttle Removal**:
- [ ] No ThrottleMiddleware in codebase
- [ ] No quota-related database tables
- [ ] No throttle logic in handlers
- [ ] Bot processes messages without rate limits
- [ ] All tests pass

✅ **File Logging**:
- [ ] Logs written to `logs/gryag.log`
- [ ] Daily rotation works (new file each day)
- [ ] Old logs auto-deleted after 7 days
- [ ] Both text and JSON formats work
- [ ] Console logging can be toggled
- [ ] Log level configurable

✅ **Documentation**:
- [ ] README updated
- [ ] Copilot instructions updated
- [ ] CHANGELOG entry added
- [ ] Migration guide complete

---

## Timeline

**Total**: 2-3 hours

- **Phase 1** (Throttle Removal): 1 hour
  - Database schema: 10 min
  - Context store cleanup: 15 min
  - Middleware removal: 10 min
  - Handler cleanup: 15 min
  - Config updates: 10 min

- **Phase 2** (File Logging): 1-2 hours
  - Logging config module: 45 min
  - Integration: 15 min
  - Configuration: 15 min
  - Scripts: 15 min

- **Phase 3** (Testing): 30 min
  - Throttle tests: 10 min
  - Logging tests: 15 min
  - Documentation: 5 min

---

## Next Steps

After reviewing this plan:

1. **Approve plan** - Confirm approach is correct
2. **Create backup** - `cp gryag.db gryag.db.backup`
3. **Execute Phase 1** - Remove throttling
4. **Execute Phase 2** - Add file logging
5. **Execute Phase 3** - Test and verify
6. **Update docs** - CHANGELOG, README, copilot-instructions

Ready to proceed? 🚀
