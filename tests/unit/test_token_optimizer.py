"""
Tests for token optimization utilities.
"""

import pytest

from app.services.context.token_optimizer import (
    format_metadata_compact,
    summarize_media_compact,
    estimate_tokens_accurate,
    estimate_message_tokens,
    deduplicate_messages,
    calculate_dynamic_budget,
    summarize_old_messages,
    prune_low_relevance,
    limit_consecutive_messages,
)


class TestMetadataFormatting:
    def test_format_with_username(self):
        meta = {"username": "alice", "name": "Alice Johnson"}
        result = format_metadata_compact(meta)
        assert result == "@alice:"

    def test_format_with_name_only(self):
        meta = {"name": "Bob Smith"}
        result = format_metadata_compact(meta)
        assert result == "Bob Smith:"

    def test_format_with_long_name(self):
        meta = {"name": "Very Long Name That Should Be Truncated"}
        result = format_metadata_compact(meta)
        assert len(result) <= 24  # 20 chars + ": " + "..."

    def test_format_empty_meta(self):
        meta = {}
        result = format_metadata_compact(meta)
        assert result == ""


class TestMediaSummaries:
    def test_single_photo(self):
        media = [{"kind": "image"}]
        result = summarize_media_compact(media)
        assert result == "📷"

    def test_multiple_photos(self):
        media = [{"kind": "image"}, {"kind": "image"}]
        result = summarize_media_compact(media)
        assert result == "📷×2"

    def test_mixed_media(self):
        media = [
            {"kind": "image"},
            {"kind": "image"},
            {"kind": "video"},
        ]
        result = summarize_media_compact(media)
        assert "📷×2" in result
        assert "🎬" in result

    def test_youtube_detection(self):
        media = [
            {"file_uri": "https://www.youtube.com/watch?v=abc123", "kind": "video"}
        ]
        result = summarize_media_compact(media)
        assert result == "🎞️"

    def test_no_media(self):
        result = summarize_media_compact(None)
        assert result is None

        result = summarize_media_compact([])
        assert result is None


class TestTokenEstimation:
    def test_english_text(self):
        text = "Hello world, this is a test message."
        tokens = estimate_tokens_accurate(text)
        # Should be roughly: 38 chars / 4 = 9-10 tokens
        assert 8 <= tokens <= 12

    def test_ukrainian_text(self):
        text = "Привіт, це тестове повідомлення."
        tokens = estimate_tokens_accurate(text)
        # Should be roughly: 33 chars / 5 = 6-7 tokens
        assert 5 <= tokens <= 9

    def test_mixed_text(self):
        text = "Hello Привіт mixed text"
        tokens = estimate_tokens_accurate(text)
        assert tokens > 0

    def test_empty_text(self):
        assert estimate_tokens_accurate("") == 0
        assert estimate_tokens_accurate(None) == 0

    def test_code_like_text(self):
        text = "function(){return x++; }"
        tokens = estimate_tokens_accurate(text)
        # Code should have lower chars_per_token
        assert tokens > 0


class TestMessageTokens:
    def test_text_message(self):
        message = {"role": "user", "parts": [{"text": "Hello world"}]}
        tokens = estimate_message_tokens(message)
        assert tokens > 0

    def test_message_with_media(self):
        message = {
            "role": "user",
            "parts": [
                {"text": "Check this out"},
                {"inline_data": {"mime_type": "image/jpeg", "data": "..."}},
            ],
        }
        tokens = estimate_message_tokens(message)
        # Should include text tokens + ~250 for image
        assert tokens >= 250

    def test_empty_message(self):
        message = {"role": "user", "parts": []}
        tokens = estimate_message_tokens(message)
        assert tokens == 0


class TestDeduplication:
    def test_exact_duplicates(self):
        messages = [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "user", "parts": [{"text": "World"}]},
        ]
        result = deduplicate_messages(messages)
        assert len(result) == 2  # Only unique messages

    def test_similar_messages(self):
        messages = [
            {"role": "user", "parts": [{"text": "Hello world how are you"}]},
            {"role": "user", "parts": [{"text": "Hello world how are you today"}]},
        ]
        result = deduplicate_messages(messages, similarity_threshold=0.8)
        assert len(result) == 1  # Second is similar to first

    def test_different_messages(self):
        messages = [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "user", "parts": [{"text": "Goodbye"}]},
        ]
        result = deduplicate_messages(messages)
        assert len(result) == 2  # Both kept

    def test_empty_list(self):
        result = deduplicate_messages([])
        assert result == []


class TestDynamicBudget:
    def test_default_allocation(self):
        budgets = calculate_dynamic_budget(
            query_text="Hello",
            recent_message_count=1,
            has_profile_facts=True,
            has_episodes=True,
        )
        # Should sum to 1.0
        assert abs(sum(budgets.values()) - 1.0) < 0.01
        assert all(0 <= v <= 1 for v in budgets.values())

    def test_active_conversation(self):
        budgets = calculate_dynamic_budget(
            query_text="Yes exactly",
            recent_message_count=5,  # Active
            has_profile_facts=True,
            has_episodes=True,
        )
        # Should increase recent budget
        default = calculate_dynamic_budget("", 1, True, True)
        assert budgets["recent"] > default["recent"]

    def test_lookup_query(self):
        budgets = calculate_dynamic_budget(
            query_text="Що таке Київ?",
            recent_message_count=1,
            has_profile_facts=True,
            has_episodes=True,
        )
        # Should increase relevant budget
        default = calculate_dynamic_budget("", 1, True, True)
        assert budgets["relevant"] > default["relevant"]

    def test_no_profile(self):
        budgets = calculate_dynamic_budget(
            query_text="Hello",
            recent_message_count=1,
            has_profile_facts=False,
            has_episodes=True,
        )
        # Should reduce background budget
        assert budgets["background"] < 0.1

    def test_no_episodes(self):
        budgets = calculate_dynamic_budget(
            query_text="Hello",
            recent_message_count=1,
            has_profile_facts=True,
            has_episodes=False,
        )
        # Should have zero episodic budget
        assert budgets["episodic"] == 0.0


class TestMessageSummarization:
    def test_under_threshold(self):
        messages = [
            {"role": "user", "parts": [{"text": f"Message {i}"}]} for i in range(10)
        ]
        result = summarize_old_messages(messages, threshold_index=20)
        # Should return unchanged
        assert len(result) == 10

    def test_over_threshold(self):
        messages = [
            {"role": "user", "parts": [{"text": f"Message {i}"}]} for i in range(30)
        ]
        result = summarize_old_messages(messages, threshold_index=20)
        # Should have summary + 20 recent messages
        assert len(result) == 21
        assert "Раніше" in result[0]["parts"][0]["text"]

    def test_mixed_roles(self):
        messages = []
        for i in range(30):
            role = "user" if i % 2 == 0 else "model"
            messages.append({"role": role, "parts": [{"text": f"Message {i}"}]})

        result = summarize_old_messages(messages, threshold_index=20)
        assert len(result) == 21
        summary_text = result[0]["parts"][0]["text"]
        assert "повідомлень" in summary_text
        assert "відповідей" in summary_text


class TestRelevancePruning:
    def test_prune_low_scores(self):
        snippets = [
            {"text": "High relevance", "score": 0.8},
            {"text": "Medium relevance", "score": 0.5},
            {"text": "Low relevance", "score": 0.2},
        ]
        result = prune_low_relevance(snippets, min_score=0.4)
        assert len(result) == 2
        assert all(s["score"] >= 0.4 for s in result)

    def test_all_high_scores(self):
        snippets = [
            {"text": "Very relevant", "score": 0.9},
            {"text": "Also relevant", "score": 0.8},
        ]
        result = prune_low_relevance(snippets, min_score=0.4)
        assert len(result) == 2

    def test_all_low_scores(self):
        snippets = [
            {"text": "Low", "score": 0.1},
            {"text": "Also low", "score": 0.2},
        ]
        result = prune_low_relevance(snippets, min_score=0.4)
        assert len(result) == 0


class TestConsecutiveLimit:
    def test_no_limiting_needed(self):
        messages = [
            {"role": "user", "parts": [{"text": "A"}]},
            {"role": "model", "parts": [{"text": "B"}]},
            {"role": "user", "parts": [{"text": "C"}]},
        ]
        result = limit_consecutive_messages(messages, max_consecutive=3)
        assert len(result) == 3

    def test_limit_consecutive_user(self):
        messages = [
            {"role": "user", "parts": [{"text": "A"}]},
            {"role": "user", "parts": [{"text": "B"}]},
            {"role": "user", "parts": [{"text": "C"}]},
            {"role": "user", "parts": [{"text": "D"}]},
            {"role": "model", "parts": [{"text": "E"}]},
        ]
        result = limit_consecutive_messages(messages, max_consecutive=2)
        # Should keep first 2 user messages, skip 3rd and 4th
        assert len(result) == 3
        assert result[2]["role"] == "model"

    def test_limit_consecutive_model(self):
        messages = [
            {"role": "model", "parts": [{"text": "A"}]},
            {"role": "model", "parts": [{"text": "B"}]},
            {"role": "model", "parts": [{"text": "C"}]},
        ]
        result = limit_consecutive_messages(messages, max_consecutive=2)
        assert len(result) == 2
