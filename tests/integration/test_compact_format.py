"""
Integration test for compact conversation format.

Tests end-to-end flow with compact format enabled.
"""

from app.services.conversation_formatter import (
    estimate_tokens,
    format_history_compact,
)


def test_format_comparison():
    """Compare token usage between JSON and compact formats."""

    # Sample conversation in JSON format (Gemini API structure)
    json_messages = [
        {
            "role": "user",
            "parts": [
                {
                    "text": '[meta] chat_id=-123456789 thread_id=12 message_id=456 user_id=987654321 name="Alice" username="alice_ua"'
                },
                {"text": "Як справи, гряг?"},
            ],
        },
        {
            "role": "model",
            "parts": [
                {
                    "text": '[meta] chat_id=-123456789 message_id=457 name="gryag" username="gryag_bot" reply_to_message_id=456'
                },
                {"text": "Не набридай."},
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "text": '[meta] chat_id=-123456789 message_id=458 user_id=111222333 name="Bob" username="bob_kyiv" reply_to_message_id=457'
                },
                {"text": "А що тут відбувається?"},
            ],
        },
    ]

    # Calculate JSON token count (rough estimate)
    import json

    json_text = json.dumps(json_messages, ensure_ascii=False)
    json_tokens = estimate_tokens(json_text)

    # Convert to compact format
    compact_text = format_history_compact(json_messages)
    compact_tokens = estimate_tokens(compact_text)

    print("\n" + "=" * 70)
    print("COMPACT CONVERSATION FORMAT - TOKEN COMPARISON")
    print("=" * 70)

    print("\nJSON Format:")
    print("-" * 70)
    print(json_text[:200] + "..." if len(json_text) > 200 else json_text)
    print(f"\nEstimated tokens: {json_tokens}")

    print("\n" + "=" * 70)
    print("Compact Format:")
    print("-" * 70)
    print(compact_text)
    print(f"\nEstimated tokens: {compact_tokens}")

    print("\n" + "=" * 70)
    print("RESULTS:")
    print("-" * 70)
    print(f"Token reduction: {json_tokens - compact_tokens} tokens")
    print(
        f"Percentage saved: {((json_tokens - compact_tokens) / json_tokens * 100):.1f}%"
    )
    print("=" * 70 + "\n")

    # Verify we have significant savings
    assert compact_tokens < json_tokens, "Compact format should use fewer tokens"
    savings_percent = (json_tokens - compact_tokens) / json_tokens * 100
    assert savings_percent > 50, f"Expected >50% savings, got {savings_percent:.1f}%"

    print("✅ Compact format achieves significant token savings!")


def test_long_conversation():
    """Test compact format with longer conversation (20+ messages)."""

    # Generate a realistic long conversation
    messages = []
    user_ids = [111111, 222222, 333333]
    usernames = ["Alice", "Bob", "Charlie"]

    for i in range(20):
        user_idx = i % 3
        user_id = user_ids[user_idx]
        username = usernames[user_idx]

        if i % 4 == 0:
            # Bot response
            messages.append(
                {
                    "role": "model",
                    "parts": [
                        {"text": '[meta] name="gryag"'},
                        {"text": f"Відповідь {i}"},
                    ],
                }
            )
        else:
            # User message
            messages.append(
                {
                    "role": "user",
                    "parts": [
                        {"text": f'[meta] user_id={user_id} name="{username}"'},
                        {"text": f"Повідомлення {i} від {username}"},
                    ],
                }
            )

    # Format as compact
    compact_text = format_history_compact(messages)
    tokens = estimate_tokens(compact_text)

    print("\n" + "=" * 70)
    print("LONG CONVERSATION TEST (20 messages)")
    print("=" * 70)
    print(f"\nMessages: {len(messages)}")
    print(f"Lines in compact format: {len(compact_text.split(chr(10)))}")
    print(f"Estimated tokens: {tokens}")
    print(f"Tokens per message: {tokens / len(messages):.1f}")
    print("\nFirst 5 lines:")
    print("-" * 70)
    for line in compact_text.split("\n")[:5]:
        print(line)
    print("-" * 70)
    print("=" * 70 + "\n")

    # Verify reasonable token count
    tokens_per_message = tokens / len(messages)
    assert (
        tokens_per_message < 50
    ), f"Expected <50 tokens/msg, got {tokens_per_message:.1f}"

    print("✅ Long conversation formatted efficiently!")


def test_media_messages():
    """Test compact format with media messages."""

    messages = [
        {
            "role": "user",
            "parts": [
                {"text": '[meta] user_id=123456 name="Alice"'},
                {"text": "Подивись на це фото"},
                {"inline_data": {"mime_type": "image/jpeg", "data": "base64data..."}},
            ],
        },
        {
            "role": "model",
            "parts": [
                {"text": '[meta] name="gryag"'},
                {"text": "Гарне фото!"},
            ],
        },
        {
            "role": "user",
            "parts": [
                {"text": '[meta] user_id=789012 name="Bob"'},
                {"inline_data": {"mime_type": "video/mp4", "data": "base64data..."}},
                {"inline_data": {"mime_type": "audio/ogg", "data": "base64data..."}},
            ],
        },
    ]

    compact_text = format_history_compact(messages)

    print("\n" + "=" * 70)
    print("MEDIA MESSAGES TEST")
    print("=" * 70)
    print("\nCompact format with media:")
    print("-" * 70)
    print(compact_text)
    print("-" * 70)
    print("=" * 70 + "\n")

    # Verify media descriptions are present
    assert "[Media]" in compact_text, "Media markers should be present"

    print("✅ Media messages formatted correctly!")


def test_reply_chains():
    """Test compact format with reply chains."""

    messages = [
        {
            "role": "user",
            "parts": [
                {"text": '[meta] user_id=111111 name="Alice"'},
                {"text": "Привіт!"},
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "text": '[meta] user_id=222222 name="Bob" reply_to_user_id=111111 reply_to_name="Alice"'
                },
                {"text": "Привіт, Аліс!"},
            ],
        },
        {
            "role": "model",
            "parts": [
                {
                    "text": '[meta] name="gryag" reply_to_user_id=222222 reply_to_name="Bob"'
                },
                {"text": "Йо."},
            ],
        },
    ]

    compact_text = format_history_compact(messages)

    print("\n" + "=" * 70)
    print("REPLY CHAINS TEST")
    print("=" * 70)
    print("\nCompact format with replies:")
    print("-" * 70)
    print(compact_text)
    print("-" * 70)
    print("=" * 70 + "\n")

    # Verify reply arrows are present
    assert "→" in compact_text, "Reply arrows should be present"

    print("✅ Reply chains formatted correctly!")


def main():
    """Run all integration tests."""
    print("\n" + "█" * 70)
    print("█" + " " * 68 + "█")
    print("█" + " " * 15 + "COMPACT CONVERSATION FORMAT TESTS" + " " * 20 + "█")
    print("█" + " " * 68 + "█")
    print("█" * 70)

    try:
        test_format_comparison()
        test_long_conversation()
        test_media_messages()
        test_reply_chains()

        print("\n" + "█" * 70)
        print("█" + " " * 68 + "█")
        print("█" + " " * 20 + "ALL TESTS PASSED! ✅" + " " * 28 + "█")
        print("█" + " " * 68 + "█")
        print("█" * 70 + "\n")

        return 0
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n💥 ERROR: {e}\n")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
