#!/bin/bash
# Verification script for continuous learning system
# Run this while bot is active to check if facts are being extracted

echo "=== Continuous Learning System Verification ==="
echo ""

# Check if local model exists
echo "1. Checking local model..."
if [ -f "models/phi-3-mini-q4.gguf" ]; then
    echo "   ✅ Local model found"
    ls -lh models/phi-3-mini-q4.gguf
else
    echo "   ❌ Local model NOT found"
    echo "   Run: bash download_model.sh"
fi
echo ""

# Check configuration
echo "2. Checking .env configuration..."
grep -E "FACT_EXTRACTION_METHOD|FACT_CONFIDENCE_THRESHOLD|ENABLE_MESSAGE_FILTERING|ENABLE_GEMINI_FALLBACK" .env
echo ""

# Check database for recent facts
echo "3. Checking recent fact extraction (last 24 hours)..."
sqlite3 gryag.db <<EOF
.headers on
.mode column
SELECT 
    COUNT(*) as total_facts,
    COUNT(DISTINCT user_id) as unique_users,
    MIN(datetime(created_at, 'localtime')) as first_fact,
    MAX(datetime(created_at, 'localtime')) as last_fact
FROM user_facts 
WHERE created_at > datetime('now', '-24 hours');
EOF
echo ""

# Check fact types
echo "4. Recent facts by type (last 24 hours)..."
sqlite3 gryag.db <<EOF
.headers on
.mode column
SELECT 
    fact_type,
    COUNT(*) as count,
    AVG(confidence) as avg_confidence
FROM user_facts 
WHERE created_at > datetime('now', '-24 hours')
GROUP BY fact_type
ORDER BY count DESC;
EOF
echo ""

# Check last 10 facts
echo "5. Last 10 facts extracted..."
sqlite3 gryag.db <<EOF
.headers on
.mode column
.width 15 30 10
SELECT 
    fact_type,
    fact_value,
    ROUND(confidence, 2) as conf,
    datetime(created_at, 'localtime') as created
FROM user_facts 
ORDER BY created_at DESC
LIMIT 10;
EOF
echo ""

# Check conversation windows
echo "6. Conversation window activity (if table exists)..."
sqlite3 gryag.db <<EOF
SELECT COUNT(*) as window_count
FROM sqlite_master 
WHERE type='table' AND name='conversation_windows';
EOF
echo ""

# Check fact quality metrics
echo "7. Fact quality metrics (if table exists)..."
sqlite3 gryag.db <<EOF
.headers on
.mode column
SELECT 
    AVG(duplicates_removed) as avg_dupes,
    AVG(conflicts_resolved) as avg_conflicts,
    AVG(processing_time_ms) as avg_time_ms,
    COUNT(*) as total_runs
FROM fact_quality_metrics
WHERE created_at > datetime('now', '-24 hours');
EOF
echo ""

echo "=== Next Steps ==="
echo ""
echo "To monitor live fact extraction:"
echo "  python -m app.main 2>&1 | grep -E 'facts|window|extract' --color=always"
echo ""
echo "To test fact extraction, send these messages in Telegram:"
echo "  1. Short fact: 'я з Києва'"
echo "  2. Long fact: 'я програміст, працюю з Python вже 5 років'"
echo "  3. Addressed: '@gryag скажи щось'"
echo ""
echo "After 5 minutes, run this script again to see if facts were extracted"
