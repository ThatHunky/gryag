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
        self.database_url = str(db_path)  # Accept database_url string
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
        self._cache_ttl = 300  # 5 minutes (increase from 1 min)
        # Persistent cache for recent chats (last N)
        self._recent_cache: dict[tuple[int, int | None], tuple[list[dict], float]] = {}
        self._recent_cache_size = 20  # Cache last 20 chats

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

        # Calculate adaptive budget allocation based on query and context
        from app.services.context.token_optimizer import calculate_dynamic_budget

        # Get recent message count for activity detection
        recent_messages = await self.context_store.recent(
            chat_id, thread_id, limit=10
        )
        recent_message_count = len(recent_messages)

        # Check if profile facts exist
        has_profile_facts = False
        if self.profile_store:
            try:
                facts = await self.profile_store.get_facts(
                    user_id, chat_id, limit=1, min_confidence=0.5
                )
                has_profile_facts = len(facts) > 0
            except Exception:
                pass

        # Check if episodes exist
        has_episodes = False
        if self.episode_store:
            try:
                episodes = await self.episode_store.retrieve_relevant_episodes(
                    chat_id=chat_id,
                    user_id=user_id,
                    query=query_text,
                    limit=1,
                    min_importance=0.3,
                )
                has_episodes = len(episodes) > 0
            except Exception:
                pass

        # Prepare base budgets from settings (percentages), used by dynamic allocator
        base_budgets = {
            "immediate": getattr(self.settings, "context_budget_immediate_pct", 0.20),
            "recent": getattr(self.settings, "context_budget_recent_pct", 0.30),
            "relevant": getattr(self.settings, "context_budget_relevant_pct", 0.25),
            "background": getattr(self.settings, "context_budget_background_pct", 0.15),
            "episodic": getattr(self.settings, "context_budget_episodic_pct", 0.10),
        }

        # Calculate dynamic budgets using query/activity signals and base settings
        budget_percentages = calculate_dynamic_budget(
            query_text=query_text,
            recent_message_count=recent_message_count,
            has_profile_facts=has_profile_facts,
            has_episodes=has_episodes,
            base_budgets=base_budgets,
        )

        # Convert percentages to token budgets
        immediate_budget = int(max_tokens * budget_percentages["immediate"])
        recent_budget = int(max_tokens * budget_percentages["recent"])
        relevant_budget = int(max_tokens * budget_percentages["relevant"])
        background_budget = int(max_tokens * budget_percentages["background"])
        episodic_budget = int(max_tokens * budget_percentages["episodic"])

        # Level 1: Immediate context (always included)
        immediate_start = time.time()
        immediate = await self._get_immediate_context(
            chat_id, thread_id, immediate_budget
        )
        immediate_time_ms = (time.time() - immediate_start) * 1000

        # Parallel retrieval of other levels
        tasks = []
        level_names = ["recent", "relevant", "background", "episodic"]
        parallel_start = time.time()

        if include_recent:
            tasks.append(self._get_recent_context(chat_id, thread_id, recent_budget))
        else:
            tasks.append(asyncio.sleep(0, result=None))

        # Detect query type to adjust context retrieval
        query_type = self._detect_query_type(query_text)
        is_news_query = query_type == "news"
        
        # For news queries, reduce or skip relevant context (past conversations)
        # to prevent pulling in irrelevant old conversations
        if include_relevant and self.hybrid_search:
            if is_news_query:
                # For news queries, significantly reduce relevant context budget
                # or skip it entirely to avoid confusion from old conversations
                news_relevant_budget = int(relevant_budget * 0.3)  # 30% of normal budget
                tasks.append(
                    self._get_relevant_context(
                        query_text, chat_id, thread_id, user_id, news_relevant_budget
                    )
                )
                LOGGER.debug(
                    f"News query detected, reducing relevant context budget to {news_relevant_budget} tokens",
                    extra={"chat_id": chat_id, "query": query_text[:100]}
                )
            else:
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
        parallel_time_ms = (time.time() - parallel_start) * 1000

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

        # Detailed timing breakdown for diagnostics
        timing_data = {
            "assembly_time_ms": assembly_time,
            "immediate_time_ms": immediate_time_ms,
            "parallel_time_ms": parallel_time_ms,
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
        }

        # Log at INFO level if assembly is slow (> 2 seconds)
        log_level_method = LOGGER.warning if assembly_time > 2000 else LOGGER.debug
        log_level_method(
            f"Assembled context: {total_tokens} tokens in {assembly_time:.1f}ms (immediate: {immediate_time_ms:.1f}ms, parallel: {parallel_time_ms:.1f}ms)",
            extra={
                "chat_id": chat_id,
                "total_tokens": total_tokens,
                "budget": max_tokens,
                "budget_usage_pct": round((total_tokens / max_tokens) * 100, 1),
                **timing_data,
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

        Cached for 5 minutes for performance. Also uses persistent cache for recent chats.
        """
        cache_key = (chat_id, thread_id)
        now = time.time()

        # Check immediate cache
        if cache_key in self._immediate_cache:
            messages, cache_time = self._immediate_cache[cache_key]
            if now - cache_time < self._cache_ttl:
                tokens = self._estimate_tokens(messages)
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

        # Check persistent recent cache
        if cache_key in self._recent_cache:
            messages, cache_time = self._recent_cache[cache_key]
            tokens = self._estimate_tokens(messages)
            LOGGER.debug(f"Immediate context (persistent cache) hit for chat {chat_id}")
            return ImmediateContext(
                messages=messages,
                token_count=tokens,
            )

        # Fetch recent messages (use message count directly)
        limit = self.settings.immediate_context_size
        messages = await self.context_store.recent(chat_id, thread_id, limit)
        messages = self._filter_history(messages)

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

        messages = self._truncate_to_budget(messages, max_tokens)

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

        # Cache it (immediate and persistent)
        self._immediate_cache[cache_key] = (messages, now)
        self._recent_cache[cache_key] = (messages, now)
        # Enforce persistent cache size
        if len(self._recent_cache) > self._recent_cache_size:
            # Remove oldest
            oldest = sorted(self._recent_cache.items(), key=lambda x: x[1][1])[:1]
            for k, _ in oldest:
                del self._recent_cache[k]

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
        # Use message count directly (no conversion needed)
        limit = self.settings.recent_context_size

        # Get recent messages beyond immediate
        all_recent = await self.context_store.recent(chat_id, thread_id, limit)
        # Filter and sanitize fetched messages before slicing into recent_only
        all_recent = self._filter_history(all_recent)

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

        # Calculate time span from actual timestamps
        time_span = 0
        if recent_only:
            timestamps = [
                msg.get("ts")
                for msg in recent_only
                if msg.get("ts") is not None
            ]
            if len(timestamps) >= 2:
                # Calculate span from oldest to newest
                oldest_ts = min(timestamps)
                newest_ts = max(timestamps)
                time_span = newest_ts - oldest_ts
            elif len(timestamps) == 1:
                # Single message, estimate based on current time
                now = int(time.time())
                time_span = now - timestamps[0]
            else:
                # No timestamps available, estimate conservatively
                time_span = len(recent_only) * 60  # Assume 1 message per minute

        tokens = self._estimate_tokens(recent_only)

        return RecentContext(
            messages=recent_only,
            token_count=tokens,
            time_span_seconds=time_span,
        )

    def _detect_query_type(self, query: str) -> str:
        """
        Detect query type based on patterns, keywords, and structure.
        
        Returns: "news", "factual", "conversational", "command", "general"
        """
        if not query:
            return "general"
        
        query_lower = query.lower().strip()
        query_words = query_lower.split()
        query_length = len(query_words)
        
        # News-related keywords (Ukrainian and English)
        news_keywords = [
            "новини", "новин", "новина", "новинка",
            "атака", "атаки", "атаку", "атакою",
            "події", "подій", "подія", "подією",
            "сьогодні", "сьогоднішня", "сьогоднішні", "сьогоднішньої",
            "останні", "останніх", "остання", "останнє",
            "що сталося", "що відбулося", "що трапилося",
            "news", "latest", "recent", "today", "attack", "attacks",
            "events", "happened", "breaking", "breaking news"
        ]
        
        # Factual/lookup question words (Ukrainian and English)
        factual_indicators = [
            "що", "хто", "коли", "де", "як", "чому", "скільки",
            "what", "who", "when", "where", "how", "why", "how many", "how much",
            "який", "яка", "яке", "які",
            "which", "whose"
        ]
        
        # Command indicators
        command_indicators = [
            "зроби", "створи", "напиши", "покажи", "знайди", "пошукай",
            "do", "create", "write", "show", "find", "search", "generate",
            "згенеруй", "зроби", "створи", "намалюй"
        ]
        
        # Conversational indicators (greetings, casual)
        conversational_indicators = [
            "привіт", "вітаю", "добрий день", "доброго ранку", "добрий вечір",
            "hello", "hi", "hey", "good morning", "good evening", "good day",
            "як справи", "що нового", "how are you", "what's up"
        ]
        
        # Check for news keywords
        for keyword in news_keywords:
            if keyword in query_lower:
                return "news"
        
        # Check for factual questions (question words at start)
        if query_words and query_words[0] in factual_indicators:
            return "factual"
        
        # Check for any factual indicators in query
        if any(indicator in query_lower for indicator in factual_indicators):
            return "factual"
        
        # Check for commands (imperative verbs)
        if any(indicator in query_lower for indicator in command_indicators):
            return "command"
        
        # Check for conversational patterns
        if any(indicator in query_lower for indicator in conversational_indicators):
            return "conversational"
        
        # Very short queries (< 3 words) are likely conversational or follow-ups
        if query_length < 3:
            return "conversational"
        
        return "general"

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
        Filters out low-relevance results and old context for news queries.
        """
        if not self.hybrid_search:
            return RelevantContext(
                snippets=[],
                token_count=0,
                average_relevance=0.0,
            )

        # Detect query type
        query_type = self._detect_query_type(query)
        is_news_query = query_type == "news"
        
        # For news queries, exclude old context
        time_range_days = None
        if is_news_query:
            time_range_days = self.settings.exclude_old_context_for_news_days
            LOGGER.debug(
                f"News query detected, excluding context older than {time_range_days} days",
                extra={"query": query[:100], "chat_id": chat_id}
            )

        # Determine how many results we need
        # Assume average of ~150 tokens per message
        estimated_results = max(1, max_tokens // 150)
        limit = min(estimated_results, self.settings.relevant_context_size)

        # Execute hybrid search with timeout to prevent runaway searches
        # Retry logic for transient errors
        max_retries = 2
        last_error = None
        results = []
        for attempt in range(max_retries + 1):
            try:
                results = await self.hybrid_search.search(
                    query=query,
                    chat_id=chat_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    limit=limit * 2,  # Get more results to filter
                    time_range_days=time_range_days,
                    timeout_seconds=5.0,  # 5 second timeout for relevant context search
                )
                last_error = None  # Success
                break  # Success, exit retry loop
            except asyncio.TimeoutError:
                # Timeout errors shouldn't be retried
                LOGGER.warning(
                    f"Hybrid search timeout for chat {chat_id}",
                    extra={"chat_id": chat_id, "query": query[:100], "attempt": attempt + 1}
                )
                last_error = "timeout"
                break
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    # Retry with exponential backoff
                    wait_time = 0.1 * (2 ** attempt)
                    LOGGER.warning(
                        f"Hybrid search failed (attempt {attempt + 1}/{max_retries + 1}), retrying in {wait_time}s: {e}",
                        extra={"chat_id": chat_id, "query": query[:100]}
                    )
                    await asyncio.sleep(wait_time)
                else:
                    LOGGER.error(
                        f"Hybrid search failed after {max_retries + 1} attempts: {e}",
                        exc_info=True,
                        extra={"chat_id": chat_id, "query": query[:100]}
                    )

        # Check if we have results (search succeeded)
        if last_error is not None or not results:
            # Return empty context on failure
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

        # Prune low-relevance snippets using utility function
        from app.services.context.token_optimizer import prune_low_relevance

        min_score = self.settings.min_relevance_score_threshold
        snippets = prune_low_relevance(snippets, min_score=min_score)

        # Recalculate total relevance after pruning
        total_relevance = sum(s.get("score", 0.0) for s in snippets)

        # Apply semantic deduplication if enabled
        if self.settings.enable_semantic_deduplication:
            snippets = self._deduplicate_snippets(snippets)
            # Recalculate again after deduplication
            total_relevance = sum(s.get("score", 0.0) for s in snippets)

        # Truncate to budget
        snippets = self._truncate_snippets_to_budget(snippets, max_tokens)

        avg_relevance = total_relevance / len(snippets) if snippets else 0.0
        # Use accurate token estimation
        from app.services.context.token_optimizer import estimate_tokens_accurate
        tokens = sum(estimate_tokens_accurate(s.get("text", "")) for s in snippets)

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
            from app.services.context.token_optimizer import estimate_tokens_accurate

            summary_tokens = estimate_tokens_accurate(summary) if summary else 0
            facts_tokens = sum(
                estimate_tokens_accurate(f.get("fact_key", "") + " " + f.get("fact_value", ""))
                for f in facts
            )

            chat_summary_tokens = estimate_tokens_accurate(chat_summary) if chat_summary else 0
            chat_facts_tokens = sum(
                estimate_tokens_accurate(f.get("fact_key", "") + " " + f.get("fact_value", ""))
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
            LOGGER.error(
                f"Failed to get background context: {e}",
                exc_info=True,
                extra={"user_id": user_id, "chat_id": chat_id, "query": query[:100]}
            )
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

            from app.services.context.token_optimizer import estimate_tokens_accurate

            for ep in episodes_obj:
                summary_tokens = estimate_tokens_accurate(ep.summary)

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
            LOGGER.error(
                f"Failed to get episodic context: {e}",
                exc_info=True,
                extra={"user_id": user_id, "chat_id": chat_id, "query": query[:100]}
            )
            return EpisodicContext(
                episodes=[],
                token_count=0,
            )

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """
        Estimate token count for messages using accurate token estimation.

        Uses character-based heuristic that accounts for:
        - English: ~4 chars per token
        - Ukrainian/Cyrillic: ~5 chars per token
        - Code/symbols: ~3.5 chars per token
        - Media (inline_data): ~258 tokens per item (Gemini's image token cost)
        - Media (file_data/URI): ~100 tokens per item (YouTube URLs, etc.)
        """
        from app.services.context.token_optimizer import estimate_message_tokens

        total = 0
        for msg in messages:
            total += estimate_message_tokens(msg)
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

        from app.services.context.token_optimizer import estimate_tokens_accurate

        for snippet in snippets:
            text = snippet.get("text", "")
            tokens = estimate_tokens_accurate(text)

            if total_tokens + tokens > max_tokens:
                break

            truncated.append(snippet)
            total_tokens += tokens

        return truncated

    def _is_allowed_message(self, msg: dict[str, Any]) -> bool:
        """
        Determine if a message is allowed to be included in LLM-visible context.

        Rules:
        - Exclude messages with visibility set to non-public (e.g., 'hidden', 'deleted')
        - Exclude messages explicitly marked as internal/debug
        - Exclude messages whose role is 'system' or 'internal'
        """
        if not isinstance(msg, dict):
            return False

        # Visibility flags
        visibility = msg.get("visibility") or msg.get("vis") or "public"
        if str(visibility).lower() in ("hidden", "deleted", "internal"):
            return False

        # Explicit internal/debug flags
        if msg.get("internal") or msg.get("is_debug") or msg.get("debug"):
            return False

        # Common role field
        role = msg.get("role") or msg.get("sender_role") or msg.get("actor_role")
        if role and str(role).lower() in ("system", "internal"):
            return False

        return True

    def _sanitize_text(self, text: str | None) -> str | None:
        """Sanitize text: redact emails, phone numbers, and strip obvious debug markers."""
        import re

        if text is None:
            return None
        if not text:
            return ""

        # Previously we redacted phone-like numbers here, but this caused legitimate
        # user IDs (especially numeric Telegram IDs) to be lost. We now preserve
        # the original values so context and logs reflect the real identifiers.

        # Remove leading debug lines
        text = re.sub(r"(?im)^\s*(debug|internal|trace):.*$", "", text)

        # Collapse repeated whitespace
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def _sanitize_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Return a sanitized shallow copy of a message suitable for inclusion in prompts."""
        import copy

        new_msg = copy.deepcopy(msg)

        # Remove metadata/provenance keys that should not be revealed
        for k in (
            "provenance",
            "metadata",
            "internal_notes",
            "debug_info",
            "source",
            "score",
        ):
            if k in new_msg:
                new_msg.pop(k, None)

        # Sanitize parts (text and placeholders). Keep minimal structure.
        # Preserve media parts (inline_data and file_data) so Gemini can see historical media.
        parts = []
        for part in new_msg.get("parts", []):
            if isinstance(part, dict):
                if "text" in part:
                    clean = self._sanitize_text(part.get("text"))
                    parts.append({"text": clean})
                elif "inline_data" in part:
                    # Preserve inline media (already base64-encoded, safe for API)
                    # This allows Gemini to see historical images/videos/audio
                    parts.append(part)
                elif "file_data" in part:
                    # Preserve file_data (file URIs like YouTube URLs, safe for API)
                    # This allows Gemini to see historical file references
                    parts.append(part)
                else:
                    # Fallback: stringify small values
                    text = " ".join(
                        str(v)
                        for v in part.values()
                        if isinstance(v, (str, int, float))
                    )
                    parts.append({"text": self._sanitize_text(text)})
            else:
                # Non-dict parts: coerce to text
                parts.append({"text": self._sanitize_text(str(part))})

        new_msg["parts"] = parts

        # Sanitize top-level textual fields
        for txt_field in ("text", "content", "body"):
            if txt_field in new_msg and isinstance(new_msg[txt_field], str):
                new_msg[txt_field] = self._sanitize_text(new_msg[txt_field])

        return new_msg

    def _filter_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter and sanitize a list of historical messages.

        Preserves chronological order. Removes messages that shouldn't be exposed to LLM.
        """
        if not history:
            return []

        filtered: list[dict[str, Any]] = []

        for msg in history:
            try:
                if not self._is_allowed_message(msg):
                    LOGGER.debug(
                        "Filtered message from history",
                        extra={"reason": "internal_or_hidden", "msg_id": msg.get("id")},
                    )
                    continue

                sanitized = self._sanitize_message(msg)
                filtered.append(sanitized)
            except Exception as e:
                LOGGER.warning(
                    f"Failed to sanitize history message: {e}", exc_info=True
                )

        return filtered

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
            system_parts.append(
                f"User Profile: {self._sanitize_text(context.background.profile_summary)}"
            )

        if context.relevant and context.relevant.snippets:
            relevant_texts = []
            for s in context.relevant.snippets[:5]:
                txt = s.get("text", "")
                txt = self._sanitize_text(txt[:200])
                score = s.get("score", 0.0)
                relevant_texts.append(f"[Relevance: {score:.2f}] {txt}...")
            system_parts.append("Relevant Past Context:\n" + "\n".join(relevant_texts))

        if context.episodes and context.episodes.episodes:
            episode_texts = []
            for ep in context.episodes.episodes:
                topic = self._sanitize_text(str(ep.get("topic", "")))
                summary = self._sanitize_text(ep.get("summary", "")[:150])
                episode_texts.append(f"[{topic}] {summary}...")
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
            system_parts.append(
                f"User Profile: {self._sanitize_text(context.background.profile_summary)}"
            )

        if context.relevant and context.relevant.snippets:
            relevant_texts = []
            for s in context.relevant.snippets[:5]:
                txt = s.get("text", "")
                txt = self._sanitize_text(txt[:200])
                score = s.get("score", 0.0)
                relevant_texts.append(f"[Relevance: {score:.2f}] {txt}...")
            system_parts.append("Relevant Past Context:\n" + "\n".join(relevant_texts))

        if context.episodes and context.episodes.episodes:
            episode_texts = []
            for ep in context.episodes.episodes:
                topic = self._sanitize_text(str(ep.get("topic", "")))
                summary = self._sanitize_text(ep.get("summary", "")[:150])
                episode_texts.append(f"[{topic}] {summary}...")
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
