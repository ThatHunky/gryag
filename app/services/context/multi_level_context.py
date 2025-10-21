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
from app.services import telemetry

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
    """Background context - user profile, facts, relationships, and chat facts."""

    profile_summary: str | None
    key_facts: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    chat_summary: str | None
    chat_facts: list[dict[str, Any]]
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
        chat_profile_store: Any | None = None,
        hybrid_search: Any | None = None,
        episode_store: Any | None = None,
        gemini_client: Any | None = None,
    ):
        self.db_path = Path(db_path)
        self.settings = settings
        self.context_store = context_store
        self.profile_store = profile_store
        self.chat_profile_store = chat_profile_store
        self.hybrid_search = hybrid_search
        self.episode_store = episode_store
        self.gemini_client = gemini_client

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

        # Enhanced token tracking with telemetry
        if self.settings.enable_token_tracking:
            telemetry.increment_counter("context.total_tokens", total_tokens)
            telemetry.increment_counter(
                "context.immediate_tokens", immediate.token_count
            )
            if recent and not isinstance(recent, Exception):
                telemetry.increment_counter("context.recent_tokens", recent.token_count)
            if relevant and not isinstance(relevant, Exception):
                telemetry.increment_counter(
                    "context.relevant_tokens", relevant.token_count
                )
            if background and not isinstance(background, Exception):
                telemetry.increment_counter(
                    "context.background_tokens", background.token_count
                )
            if episodes and not isinstance(episodes, Exception):
                telemetry.increment_counter(
                    "context.episodic_tokens", episodes.token_count
                )

        LOGGER.debug(
            f"Assembled context: {total_tokens} tokens in {assembly_time:.1f}ms",
            extra={
                "chat_id": chat_id,
                "total_tokens": total_tokens,
                "budget": max_tokens,
                "budget_usage_pct": round((total_tokens / max_tokens) * 100, 1),
                "assembly_time_ms": assembly_time,
                "levels": {
                    "immediate": immediate.token_count,
                    "recent": (
                        recent.token_count
                        if recent and not isinstance(recent, Exception)
                        else 0
                    ),
                    "relevant": (
                        relevant.token_count
                        if relevant and not isinstance(relevant, Exception)
                        else 0
                    ),
                    "background": (
                        background.token_count
                        if background and not isinstance(background, Exception)
                        else 0
                    ),
                    "episodic": (
                        episodes.token_count
                        if episodes and not isinstance(episodes, Exception)
                        else 0
                    ),
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

                # Debug: Log media presence
                media_count = sum(
                    1
                    for msg in messages
                    for part in msg.get("parts", [])
                    if isinstance(part, dict)
                    and ("inline_data" in part or "file_data" in part)
                )
                if media_count > 0:
                    LOGGER.debug(
                        f"Immediate context (cached) contains {media_count} media items"
                    )

                return ImmediateContext(
                    messages=messages,
                    token_count=tokens,
                )

        # Fetch recent messages
        # immediate_context_size is in messages, but recent() expects turns (pairs)
        # Convert message count to turn count (divide by 2, round up)
        limit = (self.settings.immediate_context_size + 1) // 2
        messages = await self.context_store.recent(chat_id, thread_id, limit)

        # Debug: Log media presence before truncation
        media_count_before = sum(
            1
            for msg in messages
            for part in msg.get("parts", [])
            if isinstance(part, dict) and ("inline_data" in part or "file_data" in part)
        )
        if media_count_before > 0:
            LOGGER.debug(
                f"Retrieved {len(messages)} messages with {media_count_before} media items"
            )

        # Truncate to budget
        messages = self._truncate_to_budget(messages, max_tokens)

        # Debug: Log media presence after truncation
        media_count_after = sum(
            1
            for msg in messages
            for part in msg.get("parts", [])
            if isinstance(part, dict) and ("inline_data" in part or "file_data" in part)
        )
        if media_count_before > 0:
            LOGGER.debug(
                f"After truncation: {len(messages)} messages with {media_count_after} media items "
                f"(lost {media_count_before - media_count_after})"
            )

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
        # recent_context_size is in messages, but recent() expects turns (pairs)
        # Convert message count to turn count (divide by 2, round up)
        limit = (self.settings.recent_context_size + 1) // 2

        # Get recent messages beyond immediate
        all_recent = await self.context_store.recent(chat_id, thread_id, limit)

        # Skip immediate context (already included)
        immediate_size = self.settings.immediate_context_size
        recent_only = (
            all_recent[immediate_size:] if len(all_recent) > immediate_size else []
        )

        # Debug: Log media presence before truncation
        media_count_before = sum(
            1
            for msg in recent_only
            for part in msg.get("parts", [])
            if isinstance(part, dict) and ("inline_data" in part or "file_data" in part)
        )
        if media_count_before > 0:
            LOGGER.debug(
                f"Recent context has {media_count_before} media items before truncation"
            )

        # Truncate to budget
        recent_only = self._truncate_to_budget(recent_only, max_tokens)

        # Debug: Log media presence after truncation
        media_count_after = sum(
            1
            for msg in recent_only
            for part in msg.get("parts", [])
            if isinstance(part, dict) and ("inline_data" in part or "file_data" in part)
        )
        if media_count_before > 0 or media_count_after > 0:
            LOGGER.debug(
                f"Recent context after truncation: {media_count_after} media items "
                f"(lost {media_count_before - media_count_after})"
            )

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

        # Apply semantic deduplication if enabled
        if self.settings.enable_semantic_deduplication:
            snippets = self._deduplicate_snippets(snippets)

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
        Get background context - user profile and facts, plus chat-level facts.

        Selects most relevant facts for current query.
        Allocates budget between user facts (60%) and chat facts (40%).
        """
        if not self.profile_store:
            return BackgroundContext(
                profile_summary=None,
                key_facts=[],
                relationships=[],
                chat_summary=None,
                chat_facts=[],
                token_count=0,
            )

        try:
            # Allocate budget: 60% for user facts, 40% for chat facts
            user_budget = int(max_tokens * 0.6)
            chat_budget = max_tokens - user_budget

            # Get profile summary
            summary = await self.profile_store.get_user_summary(
                user_id,
                chat_id,
                include_facts=True,
                include_relationships=True,
                max_facts=10,
            )

            # Get top user facts (sorted by confidence)
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

            # Get chat-level facts (if chat_profile_store available)
            chat_summary = None
            chat_facts = []
            if self.chat_profile_store and self.settings.enable_chat_memory:
                try:
                    chat_summary = await self.chat_profile_store.get_chat_summary(
                        chat_id=chat_id,
                        max_facts=self.settings.max_chat_facts_in_context,
                    )

                    # Get top chat facts
                    chat_facts_raw = await self.chat_profile_store.get_top_chat_facts(
                        chat_id=chat_id,
                        limit=self.settings.max_chat_facts_in_context,
                        min_confidence=self.settings.chat_fact_min_confidence,
                    )

                    # Convert to dict format for consistency
                    chat_facts = [
                        {
                            "fact_category": f.fact_category,
                            "fact_key": f.fact_key,
                            "fact_value": f.fact_value,
                            "fact_description": f.fact_description,
                            "confidence": f.confidence,
                        }
                        for f in chat_facts_raw
                    ]

                except Exception as e:
                    LOGGER.warning(f"Failed to get chat facts: {e}")

            # Estimate tokens and truncate if needed
            summary_tokens = len(summary.split()) * 1.3 if summary else 0
            facts_tokens = sum(
                len(f["fact_key"].split() + f["fact_value"].split()) * 1.3
                for f in facts
            )

            chat_summary_tokens = len(chat_summary.split()) * 1.3 if chat_summary else 0
            chat_facts_tokens = sum(
                len(f["fact_key"].split() + f["fact_value"].split()) * 1.3
                for f in chat_facts
            )

            # Truncate user facts if over budget
            remaining_user_budget = user_budget - summary_tokens
            if facts_tokens > remaining_user_budget:
                # Keep highest confidence facts
                facts = facts[: int(remaining_user_budget / 20)]  # ~20 tokens per fact

            # Truncate chat facts if over budget
            remaining_chat_budget = chat_budget - chat_summary_tokens
            if chat_facts_tokens > remaining_chat_budget:
                # Respect the configured limit
                max_chat_facts = min(len(chat_facts), int(remaining_chat_budget / 20))
                chat_facts = chat_facts[:max_chat_facts]

            total_tokens = int(
                summary_tokens
                + len(facts) * 20
                + chat_summary_tokens
                + len(chat_facts) * 20
            )

            return BackgroundContext(
                profile_summary=summary,
                key_facts=facts,
                relationships=relationships[:5],  # Top 5 relationships
                chat_summary=chat_summary,
                chat_facts=chat_facts,
                token_count=total_tokens,
            )

        except Exception as e:
            LOGGER.error(f"Failed to get background context: {e}", exc_info=True)
            return BackgroundContext(
                profile_summary=None,
                key_facts=[],
                relationships=[],
                chat_summary=None,
                chat_facts=[],
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

        Rough heuristic:
        - Text: words * 1.3 (accounts for tokenization)
        - Media (inline_data): ~258 tokens per item (Gemini's image token cost)
        - Media (file_data/URI): ~100 tokens per item (YouTube URLs, etc.)
        """
        total = 0
        for msg in messages:
            parts = msg.get("parts", [])
            for part in parts:
                if isinstance(part, dict):
                    if "text" in part:
                        text = part["text"]
                        words = len(text.split())
                        total += int(words * 1.3)
                    elif "inline_data" in part:
                        # Images/audio/video consume significant tokens
                        # Gemini uses ~258 tokens per image
                        total += 258
                    elif "file_data" in part:
                        # File URIs (e.g., YouTube URLs) are cheaper
                        total += 100
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

    def _deduplicate_snippets(
        self,
        snippets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Remove semantically duplicate snippets.

        Uses simple text similarity: if snippet text is very similar to
        a higher-scored snippet, it's considered a duplicate.

        Args:
            snippets: List of snippet dicts sorted by score (descending)

        Returns:
            Deduplicated list of snippets
        """
        if not snippets or len(snippets) < 2:
            return snippets

        threshold = self.settings.deduplication_similarity_threshold
        deduplicated = [snippets[0]]  # Always keep the highest-scored snippet

        for candidate in snippets[1:]:
            candidate_text = candidate.get("text", "").lower()
            candidate_words = set(candidate_text.split())

            is_duplicate = False
            for kept in deduplicated:
                kept_text = kept.get("text", "").lower()
                kept_words = set(kept_text.split())

                if not candidate_words or not kept_words:
                    continue

                # Jaccard similarity: intersection / union
                intersection = len(candidate_words & kept_words)
                union = len(candidate_words | kept_words)
                similarity = intersection / union if union > 0 else 0.0

                if similarity >= threshold:
                    is_duplicate = True
                    LOGGER.debug(
                        f"Deduplicated snippet (similarity={similarity:.2f}): {candidate_text[:50]}..."
                    )
                    break

            if not is_duplicate:
                deduplicated.append(candidate)

        if len(deduplicated) < len(snippets):
            removed = len(snippets) - len(deduplicated)
            LOGGER.info(f"Removed {removed} duplicate snippet(s) from relevant context")

        return deduplicated

    def clear_cache(self) -> None:
        """Clear immediate context cache."""
        self._immediate_cache.clear()

    def _limit_media_in_history(
        self, history: list[dict[str, Any]], max_media: int
    ) -> list[dict[str, Any]]:
        """
        Limit total number of media items and filter unsupported types in history.

        Performs two types of filtering:
        1. Removes unsupported media types (audio/video for Gemma models)
        2. Limits total media count (removes oldest first if over limit)

        Args:
            history: List of message dicts with 'parts' containing media
            max_media: Maximum number of media items to keep

        Returns:
            Modified history with filtered and limited media
        """
        import copy

        # Create a deep copy to avoid modifying the original
        modified_history = copy.deepcopy(history)

        # Phase 1: Filter unsupported media types
        filtered_by_type = 0
        if self.gemini_client:
            for msg_idx, msg in enumerate(modified_history):
                parts = msg.get("parts", [])
                new_parts = []

                for part in parts:
                    if isinstance(part, dict):
                        # Check if this is media
                        if "inline_data" in part:
                            mime = part["inline_data"].get("mime_type", "")
                            # Detect media kind from mime type
                            kind = "unknown"
                            if "audio" in mime.lower():
                                kind = "audio"
                            elif "video" in mime.lower():
                                kind = "video"
                            elif "image" in mime.lower():
                                kind = "photo"

                            # Check if supported
                            if hasattr(self.gemini_client, "_is_media_supported"):
                                if not self.gemini_client._is_media_supported(
                                    mime, kind
                                ):
                                    # Replace with text placeholder
                                    new_parts.append({"text": f"[{kind}: {mime}]"})
                                    filtered_by_type += 1
                                    continue

                        elif "file_data" in part:
                            # file_uri (YouTube URLs) - always supported
                            pass

                    # Keep the part (either supported media or text)
                    new_parts.append(part)

                # Update message parts
                msg["parts"] = new_parts

        if filtered_by_type > 0:
            LOGGER.info(
                f"Filtered {filtered_by_type} unsupported media item(s) from history"
            )

        # Phase 2: Limit total media count
        total_media = 0
        media_positions = []  # List of (message_idx, part_idx)

        for msg_idx, msg in enumerate(modified_history):
            parts = msg.get("parts", [])
            for part_idx, part in enumerate(parts):
                if isinstance(part, dict):
                    # Check if this part is media (inline_data or file_data)
                    is_media = "inline_data" in part or "file_data" in part
                    if is_media:
                        total_media += 1
                        media_positions.append((msg_idx, part_idx))

        # If under limit, return early
        if total_media <= max_media:
            if filtered_by_type > 0 or total_media > 0:
                LOGGER.debug(
                    f"Media count OK: {total_media} items (max: {max_media}, filtered: {filtered_by_type})"
                )
            return modified_history

        # We need to remove (total_media - max_media) items
        # Remove from oldest first (start of list)
        to_remove = total_media - max_media
        removed_count = 0

        # Remove media from oldest messages first
        for msg_idx, part_idx in media_positions:
            if removed_count >= to_remove:
                break

            # Replace media part with a text placeholder
            msg = modified_history[msg_idx]
            parts = msg.get("parts", [])

            if part_idx < len(parts):
                part = parts[part_idx]
                if "inline_data" in part:
                    mime = part["inline_data"].get("mime_type", "media")
                    parts[part_idx] = {"text": f"[media: {mime}]"}
                    removed_count += 1
                elif "file_data" in part:
                    uri = part["file_data"].get("file_uri", "")
                    parts[part_idx] = {"text": f"[media: {uri}]"}
                    removed_count += 1

        LOGGER.info(
            f"Limited media in history: removed {removed_count} of {total_media} items (max: {max_media}, also filtered {filtered_by_type} by type)"
        )

        return modified_history

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

        # Limit media/images to prevent Gemini API errors
        # Use configured max (default 28 for Gemma models with 32 limit)
        max_media = getattr(self.settings, "gemini_max_media_items", 28)
        history = self._limit_media_in_history(history, max_media)

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

    def format_for_gemini_compact(self, context: LayeredContext) -> dict[str, Any]:
        """
        Format layered context using compact plain text format.

        Converts verbose JSON format to efficient plain text:
        - "Alice#987654: Hello world"
        - "gryag: Привіт"
        - "Bob#111222 → Alice#987654: Thanks!"

        Expected token savings: 70-80% compared to JSON format.

        Returns dict with:
        - conversation_text: Plain text conversation
        - system_context: Profile/episodes (same as JSON format)
        - historical_media: Media parts from conversation history
        - token_count: Estimated tokens
        """
        from app.services.conversation_formatter import (
            format_history_compact,
            estimate_tokens,
        )

        # Combine immediate + recent into single list
        all_messages = []
        if context.immediate:
            all_messages.extend(context.immediate.messages)
        if context.recent:
            all_messages.extend(context.recent.messages)

        # Collect media parts from all historical messages
        historical_media = []
        for msg in all_messages:
            parts = msg.get("parts", [])
            for part in parts:
                if "inline_data" in part or "file_data" in part:
                    historical_media.append(part)

        # Convert to compact format
        conversation_text = format_history_compact(all_messages, bot_name="gryag")

        # Add [RESPOND] marker to indicate end of context
        if conversation_text:
            conversation_text += "\n[RESPOND]"

        # Build system context (same as JSON format)
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

        # Estimate tokens for both conversation and system context
        total_text = conversation_text
        if system_context:
            total_text += "\n\n" + system_context
        token_count = estimate_tokens(total_text)

        # Add token count for historical media (258 per inline_data, 100 per file_uri)
        for part in historical_media:
            if "inline_data" in part:
                token_count += 258
            elif "file_data" in part:
                token_count += 100

        return {
            "conversation_text": conversation_text,
            "system_context": system_context,
            "historical_media": historical_media,
            "token_count": token_count,
        }
