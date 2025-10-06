"""
Multi-level context manager for layered context retrieval.

Provides 5 levels of context with different granularities and purposes:
1. Immediate - Current conversation turn (0-5 messages, <1 min)
2. Recent - Active conversation thread (5-30 messages, <30 min)
3. Relevant - Hybrid search results (semantic + keyword + temporal)
4. Background - User profile and facts
5. Episodic - Memorable conversation events

Each level has its own retrieval strategy and token budget.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import Settings

LOGGER = logging.getLogger(__name__)


@dataclass
class ImmediateContext:
    """Immediate context - last few messages in current turn."""

    messages: list[dict[str, Any]]
    token_count: int
    source: str = "immediate"


@dataclass
class RecentContext:
    """Recent context - chronological messages from active conversation."""

    messages: list[dict[str, Any]]
    token_count: int
    time_span_seconds: int
    source: str = "recent"


@dataclass
class RelevantContext:
    """Relevant context - hybrid search results for query."""

    snippets: list[dict[str, Any]]
    token_count: int
    average_relevance: float
    source: str = "relevant"


@dataclass
class BackgroundContext:
    """Background context - user profile, facts, relationships."""

    profile_summary: str | None
    key_facts: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    token_count: int
    source: str = "background"


@dataclass
class EpisodicContext:
    """Episodic context - memorable conversation events."""

    episodes: list[dict[str, Any]]
    token_count: int
    source: str = "episodic"


@dataclass
class LayeredContext:
    """Complete layered context with all levels."""

    immediate: ImmediateContext
    recent: RecentContext | None
    relevant: RelevantContext | None
    background: BackgroundContext | None
    episodes: EpisodicContext | None
    total_tokens: int
    assembly_time_ms: float


class MultiLevelContextManager:
    """
    Manages retrieval and assembly of multi-level context.

    Coordinates between different context sources to build a comprehensive
    but token-budget-aware context for the bot's responses.
    """

    def __init__(
        self,
        db_path: Path | str,
        settings: Settings,
        context_store: Any,
        profile_store: Any | None = None,
        hybrid_search: Any | None = None,
        episode_store: Any | None = None,
    ):
        self.db_path = Path(db_path)
        self.settings = settings
        self.context_store = context_store
        self.profile_store = profile_store
        self.hybrid_search = hybrid_search
        self.episode_store = episode_store

        # Cache for immediate context
        self._immediate_cache: dict[
            tuple[int, int | None], tuple[list[dict], float]
        ] = {}
        self._cache_ttl = 60  # 1 minute

    async def build_context(
        self,
        chat_id: int,
        thread_id: int | None,
        user_id: int,
        query_text: str,
        max_tokens: int | None = None,
        include_recent: bool = True,
        include_relevant: bool = True,
        include_background: bool = True,
        include_episodes: bool = True,
    ) -> LayeredContext:
        """
        Build multi-level context for a query.

        Args:
            chat_id: Chat ID
            thread_id: Thread ID (optional)
            user_id: User making request
            query_text: Text of user's query
            max_tokens: Max context tokens (defaults to settings.context_token_budget)
            include_recent: Include recent chronological context
            include_relevant: Include relevant hybrid search results
            include_background: Include user profile
            include_episodes: Include episodic memory

        Returns:
            LayeredContext with all requested levels populated
        """
        start_time = time.time()

        max_tokens = max_tokens or self.settings.context_token_budget

        # Token allocation (as percentages of budget)
        immediate_budget = int(max_tokens * 0.20)  # 20% - most recent
        recent_budget = int(max_tokens * 0.30)  # 30% - chronological
        relevant_budget = int(max_tokens * 0.25)  # 25% - search results
        background_budget = int(max_tokens * 0.15)  # 15% - profile
        episodic_budget = int(max_tokens * 0.10)  # 10% - episodes

        # Level 1: Immediate context (always included)
        immediate = await self._get_immediate_context(
            chat_id, thread_id, immediate_budget
        )

        # Parallel retrieval of other levels
        tasks = []

        if include_recent:
            tasks.append(self._get_recent_context(chat_id, thread_id, recent_budget))
        else:
            tasks.append(asyncio.sleep(0, result=None))

        if include_relevant and self.hybrid_search:
            tasks.append(
                self._get_relevant_context(
                    query_text, chat_id, thread_id, user_id, relevant_budget
                )
            )
        else:
            tasks.append(asyncio.sleep(0, result=None))

        if include_background and self.profile_store:
            tasks.append(
                self._get_background_context(
                    user_id, chat_id, query_text, background_budget
                )
            )
        else:
            tasks.append(asyncio.sleep(0, result=None))

        if include_episodes and self.episode_store:
            tasks.append(
                self._get_episodic_context(
                    user_id, chat_id, query_text, episodic_budget
                )
            )
        else:
            tasks.append(asyncio.sleep(0, result=None))

        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Unpack results
        recent = results[0] if not isinstance(results[0], Exception) else None
        relevant = (
            results[1]
            if len(results) > 1 and not isinstance(results[1], Exception)
            else None
        )
        background = (
            results[2]
            if len(results) > 2 and not isinstance(results[2], Exception)
            else None
        )
        episodes = (
            results[3]
            if len(results) > 3 and not isinstance(results[3], Exception)
            else None
        )

        # Log any exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                level_names = ["recent", "relevant", "background", "episodic"]
                LOGGER.error(
                    f"Failed to retrieve {level_names[i]} context: {result}",
                    exc_info=result,
                )

        # Calculate total tokens
        total_tokens = immediate.token_count
        if recent:
            total_tokens += recent.token_count
        if relevant:
            total_tokens += relevant.token_count
        if background:
            total_tokens += background.token_count
        if episodes:
            total_tokens += episodes.token_count

        assembly_time = (time.time() - start_time) * 1000  # milliseconds

        LOGGER.debug(
            f"Assembled context: {total_tokens} tokens in {assembly_time:.1f}ms",
            extra={
                "chat_id": chat_id,
                "total_tokens": total_tokens,
                "assembly_time_ms": assembly_time,
                "levels": {
                    "immediate": immediate.token_count,
                    "recent": recent.token_count if recent else 0,
                    "relevant": relevant.token_count if relevant else 0,
                    "background": background.token_count if background else 0,
                    "episodic": episodes.token_count if episodes else 0,
                },
            },
        )

        return LayeredContext(
            immediate=immediate,
            recent=recent,
            relevant=relevant,
            background=background,
            episodes=episodes,
            total_tokens=total_tokens,
            assembly_time_ms=assembly_time,
        )

    async def _get_immediate_context(
        self,
        chat_id: int,
        thread_id: int | None,
        max_tokens: int,
    ) -> ImmediateContext:
        """
        Get immediate context - last few messages.

        Cached for 1 minute for performance.
        """
        cache_key = (chat_id, thread_id)
        now = time.time()

        # Check cache
        if cache_key in self._immediate_cache:
            messages, cache_time = self._immediate_cache[cache_key]
            if now - cache_time < self._cache_ttl:
                tokens = self._estimate_tokens(messages)
                return ImmediateContext(
                    messages=messages,
                    token_count=tokens,
                )

        # Fetch recent messages
        limit = self.settings.immediate_context_size
        messages = await self.context_store.recent(chat_id, thread_id, limit)

        # Truncate to budget
        messages = self._truncate_to_budget(messages, max_tokens)

        # Cache it
        self._immediate_cache[cache_key] = (messages, now)

        tokens = self._estimate_tokens(messages)

        return ImmediateContext(
            messages=messages,
            token_count=tokens,
        )

    async def _get_recent_context(
        self,
        chat_id: int,
        thread_id: int | None,
        max_tokens: int,
    ) -> RecentContext:
        """
        Get recent chronological context.

        Returns messages from active conversation window.
        """
        limit = self.settings.recent_context_size

        # Get recent messages beyond immediate
        all_recent = await self.context_store.recent(chat_id, thread_id, limit)

        # Skip immediate context (already included)
        immediate_size = self.settings.immediate_context_size
        recent_only = (
            all_recent[immediate_size:] if len(all_recent) > immediate_size else []
        )

        # Truncate to budget
        recent_only = self._truncate_to_budget(recent_only, max_tokens)

        # Calculate time span
        time_span = 0
        if recent_only:
            # Would need timestamps in messages - for now just estimate
            time_span = len(recent_only) * 60  # Assume 1 message per minute

        tokens = self._estimate_tokens(recent_only)

        return RecentContext(
            messages=recent_only,
            token_count=tokens,
            time_span_seconds=time_span,
        )

    async def _get_relevant_context(
        self,
        query: str,
        chat_id: int,
        thread_id: int | None,
        user_id: int,
        max_tokens: int,
    ) -> RelevantContext:
        """
        Get relevant context via hybrid search.

        Uses semantic + keyword + temporal + importance signals.
        """
        if not self.hybrid_search:
            return RelevantContext(
                snippets=[],
                token_count=0,
                average_relevance=0.0,
            )

        # Determine how many results we need
        # Assume average of ~150 tokens per message
        estimated_results = max(1, max_tokens // 150)
        limit = min(estimated_results, self.settings.relevant_context_size)

        # Execute hybrid search
        try:
            results = await self.hybrid_search.search(
                query=query,
                chat_id=chat_id,
                thread_id=thread_id,
                user_id=user_id,
                limit=limit,
            )
        except Exception as e:
            LOGGER.error(f"Hybrid search failed: {e}", exc_info=True)
            return RelevantContext(
                snippets=[],
                token_count=0,
                average_relevance=0.0,
            )

        # Convert to snippet format
        snippets = []
        total_relevance = 0.0

        for result in results:
            snippet = {
                "text": result.text,
                "score": result.final_score,
                "semantic": result.semantic_score,
                "keyword": result.keyword_score,
                "temporal": result.temporal_factor,
                "message_id": result.message_id,
                "timestamp": result.timestamp,
            }
            snippets.append(snippet)
            total_relevance += result.final_score

        # Truncate to budget
        snippets = self._truncate_snippets_to_budget(snippets, max_tokens)

        avg_relevance = total_relevance / len(snippets) if snippets else 0.0
        tokens = sum(len(s["text"].split()) * 1.3 for s in snippets)  # Rough estimate

        return RelevantContext(
            snippets=snippets,
            token_count=int(tokens),
            average_relevance=avg_relevance,
        )

    async def _get_background_context(
        self,
        user_id: int,
        chat_id: int,
        query: str,
        max_tokens: int,
    ) -> BackgroundContext:
        """
        Get background context - user profile and facts.

        Selects most relevant facts for current query.
        """
        if not self.profile_store:
            return BackgroundContext(
                profile_summary=None,
                key_facts=[],
                relationships=[],
                token_count=0,
            )

        try:
            # Get profile summary
            summary = await self.profile_store.get_user_summary(
                user_id,
                chat_id,
                include_facts=True,
                include_relationships=True,
                max_facts=10,
            )

            # Get top facts (sorted by confidence)
            facts = await self.profile_store.get_facts(
                user_id,
                chat_id,
                min_confidence=self.settings.fact_confidence_threshold,
                limit=15,
            )

            # Get relationships
            relationships = await self.profile_store.get_relationships(
                user_id,
                chat_id,
                min_strength=0.5,
            )

            # Estimate tokens and truncate if needed
            summary_tokens = len(summary.split()) * 1.3 if summary else 0
            facts_tokens = sum(
                len(f["fact_key"].split() + f["fact_value"].split()) * 1.3
                for f in facts
            )

            # Truncate facts if over budget
            remaining_budget = max_tokens - summary_tokens
            if facts_tokens > remaining_budget:
                # Keep highest confidence facts
                facts = facts[: int(remaining_budget / 20)]  # ~20 tokens per fact

            total_tokens = int(summary_tokens + len(facts) * 20)

            return BackgroundContext(
                profile_summary=summary,
                key_facts=facts,
                relationships=relationships[:5],  # Top 5 relationships
                token_count=total_tokens,
            )

        except Exception as e:
            LOGGER.error(f"Failed to get background context: {e}", exc_info=True)
            return BackgroundContext(
                profile_summary=None,
                key_facts=[],
                relationships=[],
                token_count=0,
            )

    async def _get_episodic_context(
        self,
        user_id: int,
        chat_id: int,
        query: str,
        max_tokens: int,
    ) -> EpisodicContext:
        """
        Get episodic context - memorable conversation events.

        Retrieved only when relevant to current query.
        """
        if not self.episode_store:
            return EpisodicContext(
                episodes=[],
                token_count=0,
            )

        try:
            # Retrieve relevant episodes
            episodes_obj = await self.episode_store.retrieve_relevant_episodes(
                chat_id=chat_id,
                user_id=user_id,
                query=query,
                limit=3,  # Max 3 episodes
                min_importance=self.settings.episode_min_importance,
            )

            # Convert to dict format
            episodes = []
            total_tokens = 0

            for ep in episodes_obj:
                summary_tokens = len(ep.summary.split()) * 1.3

                if total_tokens + summary_tokens > max_tokens:
                    break

                episodes.append(
                    {
                        "id": ep.id,
                        "topic": ep.topic,
                        "summary": ep.summary,
                        "importance": ep.importance,
                        "emotional_valence": ep.emotional_valence,
                        "tags": ep.tags,
                    }
                )

                total_tokens += int(summary_tokens)

            return EpisodicContext(
                episodes=episodes,
                token_count=int(total_tokens),
            )

        except Exception as e:
            LOGGER.error(f"Failed to get episodic context: {e}", exc_info=True)
            return EpisodicContext(
                episodes=[],
                token_count=0,
            )

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """
        Estimate token count for messages.

        Rough heuristic: words * 1.3 (accounts for tokenization)
        """
        total = 0
        for msg in messages:
            parts = msg.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    text = part["text"]
                    words = len(text.split())
                    total += int(words * 1.3)
        return total

    def _truncate_to_budget(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        """Truncate messages to fit token budget."""
        truncated = []
        total_tokens = 0

        for msg in messages:
            msg_tokens = self._estimate_tokens([msg])
            if total_tokens + msg_tokens > max_tokens:
                break
            truncated.append(msg)
            total_tokens += msg_tokens

        return truncated

    def _truncate_snippets_to_budget(
        self,
        snippets: list[dict[str, Any]],
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        """Truncate snippets to fit token budget."""
        truncated = []
        total_tokens = 0

        for snippet in snippets:
            text = snippet.get("text", "")
            tokens = int(len(text.split()) * 1.3)

            if total_tokens + tokens > max_tokens:
                break

            truncated.append(snippet)
            total_tokens += tokens

        return truncated

    def clear_cache(self) -> None:
        """Clear immediate context cache."""
        self._immediate_cache.clear()

    def format_for_gemini(self, context: LayeredContext) -> dict[str, Any]:
        """
        Format layered context for Gemini API.

        Returns dict with history and system_context.
        """
        # Immediate + Recent become conversation history
        history = []

        if context.immediate:
            history.extend(context.immediate.messages)

        if context.recent:
            history.extend(context.recent.messages)

        # Relevant, Background, Episodes become system context
        system_parts = []

        if context.background and context.background.profile_summary:
            system_parts.append(f"User Profile: {context.background.profile_summary}")

        if context.relevant and context.relevant.snippets:
            relevant_texts = [
                f"[Relevance: {s['score']:.2f}] {s['text'][:200]}..."
                for s in context.relevant.snippets[:5]
            ]
            system_parts.append("Relevant Past Context:\n" + "\n".join(relevant_texts))

        if context.episodes and context.episodes.episodes:
            episode_texts = [
                f"[{ep['topic']}] {ep['summary'][:150]}..."
                for ep in context.episodes.episodes
            ]
            system_parts.append("Memorable Events:\n" + "\n".join(episode_texts))

        system_context = "\n\n".join(system_parts) if system_parts else None

        return {
            "history": history,
            "system_context": system_context,
            "token_count": context.total_tokens,
        }
