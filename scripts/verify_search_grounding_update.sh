#!/bin/bash
# Verification script for Google Search Grounding API update

echo "======================================="
echo "Search Grounding API Update Verification"
echo "======================================="
echo ""

# Check if modern API format is used
echo "1. Checking for modern google_search API format..."
if grep -q '"google_search": {}' app/handlers/chat.py; then
    echo "   ✅ Modern google_search format found in chat.py"
else
    echo "   ❌ Modern format not found"
fi

# Check if legacy format is removed
echo ""
echo "2. Checking legacy google_search_retrieval is removed..."
if ! grep -q 'google_search_retrieval' app/handlers/chat.py; then
    echo "   ✅ Legacy format removed from chat.py"
else
    echo "   ⚠️  Legacy format still present (might be in comments/docs)"
fi

# Check documentation updates
echo ""
echo "3. Checking documentation updates..."
if grep -q "modern \`google_search\` API" .github/copilot-instructions.md; then
    echo "   ✅ Copilot instructions updated"
else
    echo "   ❌ Copilot instructions not updated"
fi

if grep -q "google_search" README.md; then
    echo "   ✅ README mentions google_search"
else
    echo "   ⚠️  README might need review"
fi

# Check changelog
echo ""
echo "4. Checking changelog entry..."
if grep -q "Google Search Grounding API Update" docs/CHANGELOG.md; then
    echo "   ✅ Changelog entry added"
else
    echo "   ❌ Changelog entry missing"
fi

# Check fix documentation
echo ""
echo "5. Checking fix documentation..."
if [ -f "docs/fixes/SEARCH_GROUNDING_API_UPDATE.md" ]; then
    echo "   ✅ Fix documentation created"
else
    echo "   ❌ Fix documentation missing"
fi

# Syntax check
echo ""
echo "6. Running Python syntax check..."
if python3 -c "import ast; ast.parse(open('app/handlers/chat.py').read())" 2>/dev/null; then
    echo "   ✅ Python syntax valid"
else
    echo "   ❌ Syntax errors found"
fi

# Summary
echo ""
echo "======================================="
echo "Verification Complete"
echo "======================================="
echo ""
echo "Next steps:"
echo "1. Set ENABLE_SEARCH_GROUNDING=true in .env"
echo "2. Test with: 'What's the latest news about AI?'"
echo "3. Monitor logs for search grounding activity"
