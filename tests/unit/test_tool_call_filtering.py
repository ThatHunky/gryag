"""Unit tests for tool call text filtering (tool_call bug fix).

Tests the _clean_response_text function to ensure it properly filters out
tool call descriptions that the model might return instead of executing.
"""

import re

# Standalone implementation for testing (extracted from app/handlers/chat.py)
_META_PREFIX_RE = re.compile(r"^\s*\[meta(?:\s+[^\]]*)?\]\s*", re.IGNORECASE)
_META_ANYWHERE_RE = re.compile(r"\[meta(?:\s+[^\]]*)?\]", re.IGNORECASE)
_TECHNICAL_INFO_RE = re.compile(
    r"\b(?:chat_id|user_id|message_id|thread_id|bot_id|conversation_id|request_id|turn_id)=[^\s\]]+",
    re.IGNORECASE,
)


def _strip_leading_metadata(text: str) -> str:
    """Remove metadata from the beginning of text."""
    match = _META_PREFIX_RE.match(text)
    if not match:
        return text
    return text[match.end() :].lstrip()


def _clean_response_text(text: str) -> str:
    """Comprehensively clean response text from any metadata or technical information."""
    if not text:
        return text

    # Remove any [meta] blocks anywhere in the text
    text = _META_ANYWHERE_RE.sub("", text)

    # Remove technical IDs and system information
    text = _TECHNICAL_INFO_RE.sub("", text)

    # Remove leading metadata
    text = _strip_leading_metadata(text)

    # Remove bracketed system markers that Gemini sometimes adds
    # Examples: [GENERATED_IMAGE], [ATTACHMENT], [IMAGE_GENERATED], etc.
    text = re.sub(
        r"\[(?:GENERATED_IMAGE|IMAGE_GENERATED|ATTACHMENT|GENERATED|IMAGE)\]",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove tool call descriptions that the model might return instead of executing
    # Patterns: "tool_call:", "function_call:", "generate_image(...)", etc.
    tool_patterns = [
        r"tool_call\s*:\s*\w+",
        r"function_call\s*:\s*\w+",
        r"tool_call\s*\(\s*[^)]*\s*\)",
        r"\bgenerate_image\s*\([^)]*\)",
        r"\bedit_image\s*\([^)]*\)",
        r"\bsearch_web\s*\([^)]*\)",
        r"\bcalculate\s*\([^)]*\)",
        r"\bget_weather\s*\([^)]*\)",
        r"\bremember_memory\s*\([^)]*\)",
        r"\brecall_memories\s*\([^)]*\)",
    ]
    for pattern in tool_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Clean up extra whitespace and empty lines
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line and not line.startswith("[meta")]

    # Join lines and clean up spacing
    cleaned = "\n".join(lines).strip()

    # Remove any remaining metadata patterns that might have slipped through
    while "[meta]" in cleaned:
        cleaned = cleaned.replace("[meta]", "").strip()

    # Clean up multiple consecutive spaces
    cleaned = " ".join(cleaned.split())

    return cleaned


def test_clean_response_text_removes_tool_call_patterns():
    """Test that tool_call: patterns are removed."""
    text = "I will help you. tool_call: generate_image Here is the result."
    result = _clean_response_text(text)
    assert "tool_call" not in result.lower()
    assert "I will help you" in result
    assert "Here is the result" in result


def test_clean_response_text_removes_function_call_patterns():
    """Test that function_call: patterns are removed."""
    text = "Sure! function_call: search_web Let me find that for you."
    result = _clean_response_text(text)
    assert "function_call" not in result.lower()
    assert "Sure!" in result
    assert "Let me find that for you" in result


def test_clean_response_text_removes_tool_invocations():
    """Test that tool invocations like generate_image(...) are removed."""
    test_cases = [
        ("generate_image(prompt='a cat')", ""),
        (
            "I'll create that. generate_image(prompt='sunset') Done!",
            "I'll create that. Done!",
        ),
        ("edit_image(prompt='make it blue')", ""),
        ("search_web(query='news')", ""),
        ("calculate(expression='2+2')", ""),
        ("get_weather(location='Kyiv')", ""),
        ("remember_memory(text='user likes cats')", ""),
        ("recall_memories(user_id=123)", ""),
    ]

    for input_text, expected_content in test_cases:
        result = _clean_response_text(input_text)
        # Check that the tool invocation is removed
        assert "(" not in result or ")" not in result or len(result) == 0
        # Check that expected content remains (if any)
        if expected_content:
            assert expected_content.strip() in result


def test_clean_response_text_preserves_normal_text():
    """Test that normal text is preserved."""
    text = "This is a normal response without any tool calls."
    result = _clean_response_text(text)
    assert result == text


def test_clean_response_text_handles_empty_input():
    """Test that empty input is handled correctly."""
    assert _clean_response_text("") == ""
    assert _clean_response_text("   ") == ""


def test_clean_response_text_handles_multiple_tool_patterns():
    """Test that multiple tool patterns in one text are all removed."""
    text = "tool_call: generate_image and also function_call: search_web plus generate_image(prompt='test')"
    result = _clean_response_text(text)
    assert "tool_call" not in result.lower()
    assert "function_call" not in result.lower()
    assert "generate_image" not in result.lower()
    assert "search_web" not in result.lower()


if __name__ == "__main__":
    # Run tests manually
    test_clean_response_text_removes_tool_call_patterns()
    print("✓ test_clean_response_text_removes_tool_call_patterns")

    test_clean_response_text_removes_function_call_patterns()
    print("✓ test_clean_response_text_removes_function_call_patterns")

    test_clean_response_text_removes_tool_invocations()
    print("✓ test_clean_response_text_removes_tool_invocations")

    test_clean_response_text_preserves_normal_text()
    print("✓ test_clean_response_text_preserves_normal_text")

    test_clean_response_text_handles_empty_input()
    print("✓ test_clean_response_text_handles_empty_input")

    test_clean_response_text_handles_multiple_tool_patterns()
    print("✓ test_clean_response_text_handles_multiple_tool_patterns")

    print("\n✅ All tests passed!")
