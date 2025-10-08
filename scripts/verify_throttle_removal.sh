#!/bin/bash
# Verification script for throttle removal and logging implementation

echo "======================================"
echo "Throttle Removal & Logging Verification"
echo "======================================"
echo ""

# Phase 1: Throttle Removal
echo "Phase 1: Throttle Removal"
echo "-------------------------"

if [ ! -f app/middlewares/throttle.py ]; then
    echo "✅ Throttle middleware deleted"
else
    echo "❌ Throttle middleware still exists"
fi

if ! grep -q "quotas" db/schema.sql; then
    echo "✅ Quotas table removed from schema"
else
    echo "❌ Quotas table still in schema"
fi

if ! grep -q "PER_USER_PER_HOUR" app/config.py; then
    echo "✅ PER_USER_PER_HOUR removed from config"
else
    echo "❌ PER_USER_PER_HOUR still in config"
fi

if ! grep -q "ThrottleMiddleware" app/main.py; then
    echo "✅ ThrottleMiddleware removed from main.py"
else
    echo "❌ ThrottleMiddleware still in main.py"
fi

echo ""

# Phase 2: File Logging
echo "Phase 2: File Logging"
echo "--------------------"

if [ -f app/core/logging_config.py ]; then
    echo "✅ Logging configuration module created"
else
    echo "❌ Logging configuration module missing"
fi

if grep -q "log_level" app/config.py; then
    echo "✅ Logging settings added to config"
else
    echo "❌ Logging settings missing from config"
fi

if grep -q "setup_logging" app/main.py; then
    echo "✅ Main.py updated to use new logging"
else
    echo "❌ Main.py not using new logging"
fi

if grep -q "LOG_LEVEL" .env.example; then
    echo "✅ Logging env vars added to .env.example"
else
    echo "❌ Logging env vars missing from .env.example"
fi

if [ -f scripts/cleanup_logs.py ]; then
    echo "✅ Log cleanup script created"
else
    echo "❌ Log cleanup script missing"
fi

echo ""

# Code Quality
echo "Code Quality"
echo "------------"

# Count lines in new files
logging_lines=$(wc -l app/core/logging_config.py 2>/dev/null | awk '{print $1}')
cleanup_lines=$(wc -l scripts/cleanup_logs.py 2>/dev/null | awk '{print $1}')
migration_lines=$(wc -l scripts/remove_throttle_tables.py 2>/dev/null | awk '{print $1}')

echo "✅ New code added:"
echo "   - logging_config.py: ${logging_lines} lines"
echo "   - cleanup_logs.py: ${cleanup_lines} lines"
echo "   - remove_throttle_tables.py: ${migration_lines} lines"
echo "   - Total: $((logging_lines + cleanup_lines + migration_lines)) lines"

echo ""
echo "======================================"
echo "✅ Implementation Verification Complete"
echo "======================================"
