#!/bin/bash
# verify_model_capabilities.sh
# Verification script for comprehensive model capability detection system

set -e

echo "=== Comprehensive Model Capability Detection Verification ==="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track pass/fail
TOTAL_TESTS=0
PASSED_TESTS=0

test_check() {
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $1"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo -e "${RED}✗${NC} $1"
    fi
}

# Test 1: Check capability detection methods exist
echo "Test 1: Capability detection methods..."
grep -q "_detect_audio_support" app/services/gemini.py
test_check "Audio support detection method exists"

grep -q "_detect_video_support" app/services/gemini.py
test_check "Video support detection method exists"

grep -q "_detect_tools_support" app/services/gemini.py
test_check "Tool support detection method exists"

# Test 2: Check media filtering logic
echo ""
echo "Test 2: Media filtering implementation..."
grep -q "_is_media_supported" app/services/gemini.py
test_check "Media support check method exists"

grep -q "def build_media_parts" app/services/gemini.py
test_check "build_media_parts method exists"

# Test 3: Check historical media filtering
echo ""
echo "Test 3: Historical context filtering..."
grep -q "_limit_media_in_history" app/services/context/multi_level_context.py
test_check "Historical media limiting method exists"

grep -q "gemini_client.*Any.*None" app/services/context/multi_level_context.py
test_check "MultiLevelContextManager accepts gemini_client"

# Test 4: Check tool disabling logic
echo ""
echo "Test 4: Tool support handling..."
grep -q "if not self._tools_supported" app/services/gemini.py
test_check "Tool filtering checks tool support flag"

grep -q "_maybe_disable_tools" app/services/gemini.py
test_check "Runtime tool disabling exists"

# Test 5: Check configuration
echo ""
echo "Test 5: Configuration..."
grep -q "gemini_max_media_items" app/config.py
test_check "Media limit configuration field exists"

if [ -f .env ]; then
    grep -q "GEMINI_MODEL" .env
    test_check ".env has GEMINI_MODEL configured"
fi

# Test 6: Check documentation
echo ""
echo "Test 6: Documentation..."
[ -f docs/features/comprehensive-model-capability-detection.md ]
test_check "Comprehensive capability detection doc exists"

[ -f docs/features/function-calling-support-detection.md ]
test_check "Function calling detection doc exists"

[ -f docs/fixes/historical-media-filtering.md ]
test_check "Historical media filtering doc exists"

# Test 7: Syntax validation
echo ""
echo "Test 7: Syntax validation..."
python3 -c "import ast; ast.parse(open('app/services/gemini.py').read())" 2>/dev/null
test_check "gemini.py syntax is valid"

python3 -c "import ast; ast.parse(open('app/services/context/multi_level_context.py').read())" 2>/dev/null
test_check "multi_level_context.py syntax is valid"

python3 -c "import ast; ast.parse(open('app/handlers/chat.py').read())" 2>/dev/null
test_check "handlers/chat.py syntax is valid"

# Test 8: Check Docker build
echo ""
echo "Test 8: Docker verification..."
if command -v docker &> /dev/null; then
    docker compose config >/dev/null 2>&1
    test_check "Docker compose configuration is valid"
    
    # Check if bot container exists
    if docker compose ps bot | grep -q "bot"; then
        test_check "Bot container is running"
    else
        echo -e "${YELLOW}⚠${NC} Bot container not running (skipped)"
    fi
else
    echo -e "${YELLOW}⚠${NC} Docker not available (skipped)"
fi

# Test 9: Check for backward compatibility
echo ""
echo "Test 9: Backward compatibility..."
grep -q "def build_media_parts" app/services/gemini.py
test_check "build_media_parts method still exists (backward compatible)"

grep -q "def format_for_gemini" app/services/context/multi_level_context.py
test_check "format_for_gemini method still exists (backward compatible)"

# Test 10: Count code changes
echo ""
echo "Test 10: Code coverage..."
CAPABILITY_CHECKS=$(grep -E "_detect.*support|_is_media_supported|_limit_media_in_history" app/services/gemini.py app/services/context/multi_level_context.py | wc -l)
if [ "$CAPABILITY_CHECKS" -ge 10 ]; then
    echo -e "${GREEN}✓${NC} Found $CAPABILITY_CHECKS capability-related code lines (expected ≥10)"
    PASSED_TESTS=$((PASSED_TESTS + 1))
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
else
    echo -e "${RED}✗${NC} Found only $CAPABILITY_CHECKS capability-related code lines (expected ≥10)"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
fi

# Summary
echo ""
echo "==================================================================="
echo -e "Tests passed: ${GREEN}$PASSED_TESTS${NC}/$TOTAL_TESTS"
if [ $PASSED_TESTS -eq $TOTAL_TESTS ]; then
    echo -e "${GREEN}All tests passed! ✓${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Test with voice messages (Gemma model should filter audio)"
    echo "2. Test with video files (Gemma model should filter video)"
    echo "3. Test with 30+ images (should limit to 28 for Gemma)"
    echo "4. Test tool usage (Gemma should disable tools gracefully)"
    echo ""
    echo "Monitor logs:"
    echo "  docker compose logs bot | grep -E 'Filtered|support|tool'"
    exit 0
else
    echo -e "${RED}Some tests failed! ✗${NC}"
    echo "Check the failed tests above for details."
    exit 1
fi
