#!/usr/bin/env python3
"""
Test script for hybrid search functionality.

Tests:
1. FTS keyword search
2. Semantic search
3. Hybrid search with scoring
"""

import asyncio
import pytest

pytestmark = pytest.mark.asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import get_settings
from app.services.gemini import GeminiClient
from app.services.context.hybrid_search import HybridSearchEngine


async def test_keyword_search():
    """Test FTS keyword search."""
    print("\n" + "=" * 80)
    print("TEST 1: Keyword Search (FTS)")
    print("=" * 80)

    settings = get_settings()
    gemini = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        embed_model=settings.gemini_embed_model,
    )

    engine = HybridSearchEngine(
        db_path=settings.db_path,
        settings=settings,
        gemini_client=gemini,
    )

    # Test keyword search
    query = "memory context improvements"
    print(f"\nQuery: '{query}'")
    print("Searching for exact keyword matches...\n")

    # Temporarily disable semantic to test keyword only
    settings.semantic_weight = 0.0
    settings.keyword_weight = 1.0

    results = await engine.search(
        query=query,
        chat_id=1,  # Adjust based on your test data
        thread_id=None,
        limit=5,
    )

    if results:
        print(f"Found {len(results)} results:")
        for i, result in enumerate(results, 1):
            print(f"\n{i}. Message ID: {result.message_id}")
            print(f"   Keyword Score: {result.keyword_score:.3f}")
            print(f"   Matched Keywords: {result.matched_keywords}")
            print(f"   Text: {result.text[:100]}...")
    else:
        print("No results found. Try a different query.")

    # Reset weights
    settings.semantic_weight = 0.5
    settings.keyword_weight = 0.3


async def test_semantic_search():
    """Test semantic search."""
    print("\n" + "=" * 80)
    print("TEST 2: Semantic Search (Embeddings)")
    print("=" * 80)

    settings = get_settings()
    gemini = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        embed_model=settings.gemini_embed_model,
    )

    engine = HybridSearchEngine(
        db_path=settings.db_path,
        settings=settings,
        gemini_client=gemini,
    )

    query = "what features have been implemented"
    print(f"\nQuery: '{query}'")
    print("Searching semantically (similar meaning)...\n")

    # Semantic only
    settings.semantic_weight = 1.0
    settings.keyword_weight = 0.0
    settings.enable_temporal_boosting = False

    results = await engine.search(
        query=query,
        chat_id=1,
        thread_id=None,
        limit=5,
    )

    if results:
        print(f"Found {len(results)} results:")
        for i, result in enumerate(results, 1):
            print(f"\n{i}. Message ID: {result.message_id}")
            print(f"   Semantic Score: {result.semantic_score:.3f}")
            print(f"   Text: {result.text[:100]}...")
    else:
        print("No results with embeddings found.")

    # Reset
    settings.semantic_weight = 0.5
    settings.keyword_weight = 0.3
    settings.enable_temporal_boosting = True


async def test_hybrid_search():
    """Test full hybrid search with all signals."""
    print("\n" + "=" * 80)
    print("TEST 3: Hybrid Search (All Signals)")
    print("=" * 80)

    settings = get_settings()
    gemini = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        embed_model=settings.gemini_embed_model,
    )

    engine = HybridSearchEngine(
        db_path=settings.db_path,
        settings=settings,
        gemini_client=gemini,
    )

    query = "hybrid search implementation"
    print(f"\nQuery: '{query}'")
    print("Using hybrid search (semantic + keyword + temporal + importance)...\n")

    results = await engine.search(
        query=query,
        chat_id=1,
        thread_id=None,
        user_id=1,  # For importance weighting
        limit=5,
    )

    if results:
        print(f"Found {len(results)} results:")
        for i, result in enumerate(results, 1):
            print(f"\n{i}. Message ID: {result.message_id}")
            print(f"   Final Score: {result.final_score:.3f}")
            print(f"   - Semantic: {result.semantic_score:.3f}")
            print(f"   - Keyword: {result.keyword_score:.3f}")
            print(f"   - Temporal: {result.temporal_factor:.3f}")
            print(f"   - Importance: {result.importance_factor:.3f}")
            print(f"   - Type Boost: {result.type_boost:.3f}")
            print(f"   Text: {result.text[:100]}...")
    else:
        print("No results found.")


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("HYBRID SEARCH TESTS")
    print("=" * 80)

    try:
        # await test_keyword_search()
        # await test_semantic_search()
        await test_hybrid_search()

        print("\n" + "=" * 80)
        print("All tests completed!")
        print("=" * 80)

    except Exception as e:
        print(f"\nTest failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
