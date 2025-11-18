"""Test Gemini handling of empty responses after tool calls."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.gemini import GeminiClient


class MockCandidate:
    """Mock Gemini candidate response."""

    def __init__(
        self,
        has_function_call: bool = False,
        text: str | None = None,
        thinking: str | None = None,
    ):
        self.finish_reason = "STOP"
        self.content = MagicMock()
        parts = []

        if has_function_call:
            function_call_part = MagicMock()
            function_call_part.function_call = MagicMock()
            function_call_part.function_call.name = "recall_facts"
            function_call_part.function_call.args = {"user_id": 123456}
            function_call_part.text = None
            function_call_part.thought = False
            parts.append(function_call_part)

        if thinking:
            thinking_part = MagicMock()
            thinking_part.text = thinking
            thinking_part.function_call = None
            thinking_part.thought = True
            parts.append(thinking_part)

        if text:
            text_part = MagicMock()
            text_part.text = text
            text_part.function_call = None
            text_part.thought = False
            parts.append(text_part)

        self.content.parts = parts
        self.content.role = "model"


class MockResponse:
    """Mock Gemini response."""

    def __init__(self, candidates: list[MockCandidate]):
        self.candidates = candidates
        self.text = None  # SDK fallback attribute


@pytest.mark.asyncio
async def test_empty_tool_response_forces_retry():
    """Test that Gemini retries without tools when it returns only function_calls."""
    client = GeminiClient(
        api_key="test_key",
        model="gemini-2.0-flash-exp",
        embed_model="text-embedding-004",
    )

    # Mock tool callback
    async def mock_recall_facts(args: dict[str, Any]) -> str:
        return '{"facts": []}'

    callbacks: dict[str, Any] = {"recall_facts": mock_recall_facts}

    # First response: function_call only (the problem case - passed to _handle_tools)
    first_response = MockResponse([MockCandidate(has_function_call=True)])

    # Second response after first tool execution in loop: still only function_call
    # Loop runs again (attempt 2)
    second_response = MockResponse([MockCandidate(has_function_call=True)])

    # Third response from second loop iteration: exits loop with function_call, no text
    # This triggers the after-loop check
    third_response = MockResponse([MockCandidate(has_function_call=True)])

    # Fourth response after forcing text: actual text response (added after loop)
    fourth_response = MockResponse(
        [MockCandidate(text="На жаль, я не знаю достатньо про цього користувача.")]
    )

    with patch.object(client, "_invoke_model", new_callable=AsyncMock) as mock_invoke:
        # Set up the sequence of responses
        # Call 1: After first tool execution (attempt 1 in loop)
        # Call 2: After second tool execution (attempt 2 in loop, exits)
        # Call 3: Forced retry without tools (after loop detects empty+function_call)
        mock_invoke.side_effect = [second_response, third_response, fourth_response]

        await client._handle_tools(
            initial_contents=[{"role": "user", "parts": [{"text": "Test"}]}],
            response=first_response,
            tools=[{"function_declarations": [{"name": "recall_facts"}]}],
            callbacks=callbacks,
            system_instruction="Test system instruction",
            include_thinking=False,
        )

        # Should have been called 3 times:
        # 1-2: In the normal tool loop (both still have function_call, no text)
        # 3: After loop exits with empty text + function_call -> forced retry without tools
        assert mock_invoke.call_count == 3

        # Third call should have no tools (None) to force text response
        # This is the key fix - when we detect empty response with function_calls after loop,
        # we retry without tools
        third_call_positional = mock_invoke.call_args_list[2][0]
        assert third_call_positional[1] is None  # tools parameter should be None


@pytest.mark.asyncio
async def test_normal_tool_response_no_retry():
    """Test that Gemini doesn't retry when tools return proper text."""
    client = GeminiClient(
        api_key="test_key",
        model="gemini-2.0-flash-exp",
        embed_model="text-embedding-004",
    )

    # Mock tool callback
    async def mock_recall_facts(args: dict[str, Any]) -> str:
        return '{"facts": ["User likes cats"]}'

    callbacks: dict[str, Any] = {"recall_facts": mock_recall_facts}

    # First response: function_call
    first_response = MockResponse([MockCandidate(has_function_call=True)])

    # Second response after tool execution: proper text response
    second_response = MockResponse(
        [MockCandidate(text="Based on my memory, you like cats!")]
    )

    with patch.object(client, "_invoke_model", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.return_value = second_response

        result = await client._handle_tools(
            initial_contents=[
                {"role": "user", "parts": [{"text": "What do you know about me?"}]}
            ],
            response=first_response,
            tools=[{"function_declarations": [{"name": "recall_facts"}]}],
            callbacks=callbacks,
            system_instruction="Test system instruction",
            include_thinking=False,
        )

        # Should have been called only once (normal tool execution)
        assert mock_invoke.call_count == 1

        # Verify text was extracted properly
        extracted = client._extract_text(result)
        assert "cats" in extracted.lower()


@pytest.mark.asyncio
async def test_extract_text_empty_with_function_call():
    """Test _extract_text returns empty string when only function_call parts exist."""
    client = GeminiClient(
        api_key="test_key",
        model="gemini-2.0-flash-exp",
        embed_model="text-embedding-004",
    )

    # Response with only function_call, no text
    response = MockResponse([MockCandidate(has_function_call=True)])

    extracted = client._extract_text(response)
    assert extracted == ""
    assert not extracted or extracted.isspace()


@pytest.mark.asyncio
async def test_extract_text_with_mixed_parts():
    """Test _extract_text correctly extracts text when mixed with function_calls."""
    client = GeminiClient(
        api_key="test_key",
        model="gemini-2.0-flash-exp",
        embed_model="text-embedding-004",
    )

    # Create a candidate with both function_call and text
    candidate = MockCandidate(has_function_call=True)
    text_part = MagicMock()
    text_part.text = "Here is my response"
    text_part.function_call = None
    text_part.thought = False
    candidate.content.parts.append(text_part)

    response = MockResponse([candidate])

    extracted = client._extract_text(response)
    assert extracted == "Here is my response"


@pytest.mark.asyncio
async def test_extract_thinking_only():
    """Test _extract_thinking correctly extracts thinking parts."""
    client = GeminiClient(
        api_key="test_key",
        model="gemini-2.0-flash-exp",
        embed_model="text-embedding-004",
    )

    # Response with only thinking, no text
    response = MockResponse(
        [MockCandidate(thinking="Блять, що робити? Треба подумати...")]
    )

    extracted_thinking = client._extract_thinking(response)
    assert extracted_thinking == "Блять, що робити? Треба подумати..."

    # Text should be empty since only thinking parts exist
    extracted_text = client._extract_text(response)
    assert extracted_text == ""


@pytest.mark.asyncio
async def test_extract_thinking_with_text():
    """Test _extract_thinking when response has both thinking and text."""
    client = GeminiClient(
        api_key="test_key",
        model="gemini-2.0-flash-exp",
        embed_model="text-embedding-004",
    )

    # Response with both thinking and text
    response = MockResponse(
        [
            MockCandidate(
                thinking="Гм, це складно. Треба перевірити факти.",
                text="Ось моя відповідь.",
            )
        ]
    )

    extracted_thinking = client._extract_thinking(response)
    assert extracted_thinking == "Гм, це складно. Треба перевірити факти."

    extracted_text = client._extract_text(response)
    assert extracted_text == "Ось моя відповідь."


@pytest.mark.asyncio
async def test_extract_multiple_thinking_parts():
    """Test _extract_thinking with multiple thinking parts."""
    client = GeminiClient(
        api_key="test_key",
        model="gemini-2.0-flash-exp",
        embed_model="text-embedding-004",
    )

    # Create a candidate with multiple thinking parts
    candidate = MockCandidate()
    thinking_part_1 = MagicMock()
    thinking_part_1.text = "Перша думка про проблему."
    thinking_part_1.function_call = None
    thinking_part_1.thought = True
    candidate.content.parts.append(thinking_part_1)

    thinking_part_2 = MagicMock()
    thinking_part_2.text = "Друга думка, більш детальна."
    thinking_part_2.function_call = None
    thinking_part_2.thought = True
    candidate.content.parts.append(thinking_part_2)

    response = MockResponse([candidate])

    extracted_thinking = client._extract_thinking(response)
    # Multiple thinking parts should be joined with double newlines
    assert "Перша думка про проблему." in extracted_thinking
    assert "Друга думка, більш детальна." in extracted_thinking
    assert "\n\n" in extracted_thinking
