#!/bin/bash
# Bot Self-Learning - Quick Verification Script
# Run this after implementation to check everything is in place

set -e

echo "🤖 Bot Self-Learning System - Verification"
echo "==========================================="
echo ""

# Check database schema
echo "1️⃣  Checking database tables..."
if command -v sqlite3 &> /dev/null; then
    TABLES=$(sqlite3 gryag.db ".tables" 2>/dev/null | grep -o "bot_[a-z_]*" | sort)
    EXPECTED_TABLES="bot_facts
bot_insights
bot_interaction_outcomes
bot_performance_metrics
bot_persona_rules
bot_profiles"
    
    if [ "$TABLES" = "$EXPECTED_TABLES" ]; then
        echo "   ✅ All 6 bot self-learning tables present"
    else
        echo "   ❌ Missing tables. Expected:"
        echo "$EXPECTED_TABLES"
        echo "   Found:"
        echo "$TABLES"
        exit 1
    fi
else
    echo "   ⚠️  sqlite3 not found, skipping database check"
fi

echo ""
echo "2️⃣  Checking Python files exist..."
FILES=(
    "app/services/bot_profile.py"
    "app/services/bot_learning.py"
    "app/services/tools/bot_self_tools.py"
    "docs/features/BOT_SELF_LEARNING.md"
    "docs/phases/PHASE_5_IMPLEMENTATION_SUMMARY.md"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "   ✅ $file"
    else
        echo "   ❌ Missing: $file"
        exit 1
    fi
done

echo ""
echo "3️⃣  Checking Python syntax..."
python3 -c "
import ast
files = [
    'app/services/bot_profile.py',
    'app/services/bot_learning.py',
    'app/services/tools/bot_self_tools.py',
]
for f in files:
    ast.parse(open(f).read())
print('   ✅ All Python files have valid syntax')
"

echo ""
echo "4️⃣  Checking configuration settings..."
if grep -q "ENABLE_BOT_SELF_LEARNING" app/config.py; then
    echo "   ✅ Config settings present in app/config.py"
else
    echo "   ❌ Config settings missing"
    exit 1
fi

echo ""
echo "5️⃣  Checking database schema additions..."
if grep -q "bot_profiles" db/schema.sql; then
    echo "   ✅ Schema additions present in db/schema.sql"
else
    echo "   ❌ Schema additions missing"
    exit 1
fi

echo ""
echo "6️⃣  Checking middleware integration..."
if grep -q "bot_profile" app/middlewares/chat_meta.py; then
    echo "   ✅ Middleware injection configured"
else
    echo "   ❌ Middleware injection missing"
    exit 1
fi

echo ""
echo "7️⃣  Checking main.py initialization..."
if grep -q "BotProfileStore" app/main.py; then
    echo "   ✅ Main.py initialization present"
else
    echo "   ❌ Main.py initialization missing"
    exit 1
fi

echo ""
echo "8️⃣  Checking admin commands..."
if grep -q "gryagself" app/handlers/profile_admin.py; then
    echo "   ✅ Admin commands implemented"
else
    echo "   ❌ Admin commands missing"
    exit 1
fi

echo ""
echo "9️⃣  Checking documentation..."
DOCS=(
    "docs/features/BOT_SELF_LEARNING.md"
    "docs/phases/PHASE_5_IMPLEMENTATION_SUMMARY.md"
)
for doc in "${DOCS[@]}"; do
    if [ -f "$doc" ]; then
        LINE_COUNT=$(wc -l < "$doc")
        echo "   ✅ $doc ($LINE_COUNT lines)"
    else
        echo "   ❌ Missing: $doc"
        exit 1
    fi
done

echo ""
echo "🔟 Checking CHANGELOG entry..."
if grep -q "Phase 5" docs/CHANGELOG.md; then
    echo "   ✅ CHANGELOG updated"
else
    echo "   ❌ CHANGELOG entry missing"
    exit 1
fi

echo ""
echo "==========================================="
echo "✅ All verification checks passed!"
echo ""
echo "📋 Next steps:"
echo "   1. Set ENABLE_BOT_SELF_LEARNING=true in .env"
echo "   2. Run: python -m app.main"
echo "   3. Look for: 'Bot self-learning initialized' in logs"
echo "   4. Test admin commands:"
echo "      - /gryagself (view bot profile)"
echo "      - /gryaginsights (generate insights)"
echo "   5. After interactions, check learned facts:"
echo "      sqlite3 gryag.db \"SELECT * FROM bot_facts ORDER BY updated_at DESC LIMIT 5;\""
echo ""
echo "📚 Documentation:"
echo "   - Comprehensive guide: docs/features/BOT_SELF_LEARNING.md"
echo "   - Implementation summary: docs/phases/PHASE_5_IMPLEMENTATION_SUMMARY.md"
echo ""
