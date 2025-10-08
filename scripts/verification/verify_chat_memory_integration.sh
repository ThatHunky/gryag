#!/usr/bin/env bash
#
# Verification script for Chat Public Memory System - Phase 3 Integration
# Checks that all components are properly integrated into the pipeline
#

echo "=== Chat Public Memory Integration Verification ==="
echo

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

check_passed=0
check_failed=0

# Helper function to check if grep finds a pattern
check_pattern() {
    local file=$1
    local pattern=$2
    local description=$3
    
    if grep -q "$pattern" "$file"; then
        echo -e "${GREEN}✓${NC} $description"
        ((check_passed++))
    else
        echo -e "${RED}✗${NC} $description"
        echo "  Missing: $pattern in $file"
        ((check_failed++))
    fi
}

# Helper function to count occurrences
count_pattern() {
    local file=$1
    local pattern=$2
    local expected=$3
    local description=$4
    
    local count=$(grep -c "$pattern" "$file" || true)
    if [ "$count" -ge "$expected" ]; then
        echo -e "${GREEN}✓${NC} $description (found $count, expected ≥$expected)"
        ((check_passed++))
    else
        echo -e "${RED}✗${NC} $description (found $count, expected ≥$expected)"
        ((check_failed++))
    fi
}

echo "1. Database Schema Checks"
echo "--------------------------"
check_pattern "db/schema.sql" "CREATE TABLE IF NOT EXISTS chat_profiles" "Chat profiles table exists"
check_pattern "db/schema.sql" "CREATE TABLE IF NOT EXISTS chat_facts" "Chat facts table exists"
check_pattern "db/schema.sql" "CREATE TABLE IF NOT EXISTS chat_fact_versions" "Chat fact versions table exists"
check_pattern "db/schema.sql" "CREATE TABLE IF NOT EXISTS chat_fact_quality_metrics" "Chat fact quality metrics table exists"
count_pattern "db/schema.sql" "CREATE INDEX.*chat_" 11 "Chat-related indexes"
echo

echo "2. Repository Layer Checks"
echo "-------------------------"
check_pattern "app/repositories/chat_profile.py" "class ChatProfileRepository" "ChatProfileRepository class exists"
check_pattern "app/repositories/chat_profile.py" "async def add_chat_fact" "add_chat_fact method exists"
check_pattern "app/repositories/chat_profile.py" "async def get_top_chat_facts" "get_top_chat_facts method exists"
check_pattern "app/repositories/chat_profile.py" "async def get_chat_summary" "get_chat_summary method exists"
echo

echo "3. Extraction Layer Checks"
echo "-------------------------"
check_pattern "app/services/fact_extractors/chat_fact_extractor.py" "class ChatFactExtractor" "ChatFactExtractor class exists"
check_pattern "app/services/fact_extractors/chat_fact_extractor.py" "async def extract_chat_facts" "extract_chat_facts method exists"
count_pattern "app/services/fact_extractors/chat_fact_extractor.py" "async def _extract_via" 3 "Three extraction methods (pattern/statistical/LLM)"
echo

echo "4. Configuration Checks"
echo "----------------------"
check_pattern "app/config.py" "enable_chat_memory" "enable_chat_memory setting exists"
check_pattern "app/config.py" "chat_fact_min_confidence" "chat_fact_min_confidence setting exists"
check_pattern "app/config.py" "max_chat_facts_in_context" "max_chat_facts_in_context setting exists"
check_pattern "app/config.py" "chat_context_token_budget" "chat_context_token_budget setting exists"
echo

echo "5. Continuous Monitor Integration"
echo "--------------------------------"
check_pattern "app/services/monitoring/continuous_monitor.py" "from app.services.fact_extractors.chat_fact_extractor import ChatFactExtractor" "ChatFactExtractor imported"
check_pattern "app/services/monitoring/continuous_monitor.py" "from app.repositories.chat_profile import ChatProfileRepository" "ChatProfileRepository imported"
check_pattern "app/services/monitoring/continuous_monitor.py" "chat_profile_store: ChatProfileRepository" "chat_profile_store parameter in __init__"
check_pattern "app/services/monitoring/continuous_monitor.py" "async def _store_chat_facts" "_store_chat_facts method exists"
check_pattern "app/services/monitoring/continuous_monitor.py" "List\[dict\], List\[ChatFact\]" "_extract_facts_from_window returns tuple"
echo

echo "6. Conversation Analyzer Integration"
echo "-----------------------------------"
check_pattern "app/services/monitoring/conversation_analyzer.py" "raw_messages: list\[Message\]" "raw_messages field in ConversationWindow"
check_pattern "app/services/monitoring/conversation_analyzer.py" "raw_message: Message | None" "add_message accepts raw_message parameter"
count_pattern "app/services/monitoring/conversation_analyzer.py" "self.raw_messages.append" 1 "Raw messages are stored in window"
echo

echo "7. Multi-Level Context Integration"
echo "----------------------------------"
check_pattern "app/services/context/multi_level_context.py" "chat_profile_store: Any | None" "chat_profile_store parameter in __init__"
check_pattern "app/services/context/multi_level_context.py" "chat_summary: str | None" "chat_summary field in BackgroundContext"
check_pattern "app/services/context/multi_level_context.py" "chat_facts: list\[dict" "chat_facts field in BackgroundContext"
check_pattern "app/services/context/multi_level_context.py" "self.chat_profile_store.get_chat_summary" "get_chat_summary called in _get_background_context"
check_pattern "app/services/context/multi_level_context.py" "self.chat_profile_store.get_top_chat_facts" "get_top_chat_facts called in _get_background_context"
echo

echo "8. Documentation Checks"
echo "----------------------"
check_pattern "docs/plans/CHAT_PUBLIC_MEMORY.md" "# Chat Public Memory System" "Full technical design document exists"
check_pattern "docs/plans/CHAT_PUBLIC_MEMORY_SUMMARY.md" "# Chat Public Memory" "Executive summary exists"
check_pattern "docs/CHANGELOG.md" "Chat Public Memory System (Phase 3 Integration Complete)" "Changelog entry exists"
echo

echo "9. Python Syntax Checks"
echo "----------------------"
if python3 -m py_compile app/repositories/chat_profile.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} chat_profile.py compiles"
    ((check_passed++))
else
    echo -e "${RED}✗${NC} chat_profile.py has syntax errors"
    ((check_failed++))
fi

if python3 -m py_compile app/services/fact_extractors/chat_fact_extractor.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} chat_fact_extractor.py compiles"
    ((check_passed++))
else
    echo -e "${RED}✗${NC} chat_fact_extractor.py has syntax errors"
    ((check_failed++))
fi

if python3 -m py_compile app/services/monitoring/continuous_monitor.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} continuous_monitor.py compiles"
    ((check_passed++))
else
    echo -e "${RED}✗${NC} continuous_monitor.py has syntax errors"
    ((check_failed++))
fi

if python3 -m py_compile app/services/monitoring/conversation_analyzer.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} conversation_analyzer.py compiles"
    ((check_passed++))
else
    echo -e "${RED}✗${NC} conversation_analyzer.py has syntax errors"
    ((check_failed++))
fi

if python3 -m py_compile app/services/context/multi_level_context.py 2>/dev/null; then
    echo -e "${GREEN}✓${NC} multi_level_context.py compiles"
    ((check_passed++))
else
    echo -e "${RED}✗${NC} multi_level_context.py has syntax errors"
    ((check_failed++))
fi
echo

echo "=== Summary ==="
echo -e "${GREEN}Passed: $check_passed${NC}"
echo -e "${RED}Failed: $check_failed${NC}"
echo

if [ $check_failed -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed! Phase 3 integration is complete.${NC}"
    echo
    echo "Next steps:"
    echo "1. Initialize chat_profile_store in app/main.py"
    echo "2. Create admin commands (/gryadchatfacts, /gryadchatreset)"
    echo "3. Run end-to-end tests with real conversations"
    echo "4. Create database migration script"
    exit 0
else
    echo -e "${RED}✗ Some checks failed. Please review the output above.${NC}"
    exit 1
fi
