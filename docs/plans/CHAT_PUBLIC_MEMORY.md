# Chat Public Memory - Design Plan

**Status**: Planning  
**Date**: October 8, 2025  
**Priority**: Medium - Enhances group chat awareness  
**Author**: AI Planning based on codebase analysis

---

## Executive Summary

This document outlines a design for **Chat Public Memory** - a shared memory system that allows the bot to remember chat-wide facts, preferences, and culture. Unlike user-specific facts (tied to `user_id`), chat facts are scoped to the entire group (`chat_id` only).

### Key Features

1. **Chat-scoped facts** - Group preferences, traditions, rules, running jokes
2. **Automatic extraction** - Detect when conversation is about "we/us" not individuals
3. **Concise retrieval** - Top 5-10 most relevant chat facts (budget-aware)
4. **Quality management** - Deduplication, conflict resolution, importance scoring
5. **Temporal awareness** - Track changes in group preferences over time

### Expected Benefits

- **Better group awareness**: Bot understands chat culture and norms
- **Reduced repetition**: Remembers group decisions and preferences
- **Improved relevance**: Context-aware responses aligned with group expectations
- **Minimal overhead**: 200-400 tokens max (5% of context budget)

---

## Problem Statement

### Current Limitations

**The bot currently only remembers individual user facts**, missing critical group-level context:

```
❌ User asks: "Should we do this again like last time?"
   Bot response: Generic, doesn't know what "we" decided

❌ Chat has running joke about "pineapple pizza"
   Bot response: Doesn't participate, seems out of touch

❌ Group always discusses certain topics on Fridays
   Bot response: No awareness of group patterns

❌ Chat prefers dark humor / technical discussions
   Bot response: Generic tone, not adapted to group culture
```

### User Experience Gap

```
USER: "Hey gryag, we were talking about that restaurant chain"
BOT:  "Що за ресторан?" [What restaurant?]
      ❌ Doesn't remember group discussed McDonald's vs KFC yesterday

USER: "Remember our no-politics rule?"
BOT:  "Що за правило?" [What rule?]
      ❌ Chat-wide norms not stored

USER: "It's Friday, time for our weekly recap!"
BOT:  "Про що говоримо?" [What are we talking about?]
      ❌ No awareness of group traditions
```

---

## Proposed Solution

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     MULTI-LEVEL CONTEXT                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Immediate   │  │   Recent     │  │  Relevant    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐          │
│  │         BACKGROUND CONTEXT (enhanced)            │          │
│  │                                                  │          │
│  │  ┌────────────────┐    ┌──────────────────┐    │          │
│  │  │  User Profile  │    │  Chat Profile    │◄───┼─ NEW!   │
│  │  │  - Facts       │    │  - Chat Facts    │    │          │
│  │  │  - Prefs       │    │  - Preferences   │    │          │
│  │  │  - Relations   │    │  - Culture       │    │          │
│  │  └────────────────┘    └──────────────────┘    │          │
│  │                                                  │          │
│  └──────────────────────────────────────────────────┘          │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐          │
│  │              EPISODIC MEMORY                     │          │
│  └──────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

### Component Integration

**Chat Public Memory extends existing systems**:

1. **Schema**: New `chat_facts` table (parallel to `user_facts`)
2. **Extraction**: Enhanced fact extractor detects group-level facts
3. **Storage**: New `ChatProfileStore` (parallel to `UserProfileStore`)
4. **Retrieval**: Integrated into `BackgroundContext` layer
5. **Context**: Added to system prompt alongside user profile

---

## Design Details

### 1. Database Schema

**New Tables**:

```sql
-- ═══════════════════════════════════════════════════════════════
-- Chat Public Memory - Group-level facts and preferences
-- Added: October 2025
-- ═══════════════════════════════════════════════════════════════

-- Chat profile metadata (one per chat)
CREATE TABLE IF NOT EXISTS chat_profiles (
    chat_id INTEGER PRIMARY KEY,
    chat_type TEXT CHECK(chat_type IN ('group', 'supergroup', 'channel')),
    chat_title TEXT,
    participant_count INTEGER DEFAULT 0,
    bot_joined_at INTEGER NOT NULL,
    last_active INTEGER NOT NULL,
    culture_summary TEXT,  -- Optional AI-generated summary
    profile_version INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- Chat-level facts (group preferences, traditions, norms)
CREATE TABLE IF NOT EXISTS chat_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    fact_category TEXT NOT NULL CHECK(fact_category IN (
        'preference',    -- "prefers dark humor", "likes technical discussions"
        'tradition',     -- "Friday recap", "Monday memes"
        'rule',          -- "no politics", "Ukrainian only"
        'norm',          -- "emoji reactions common", "voice messages rare"
        'topic',         -- "frequently discusses AI", "crypto enthusiasts"
        'culture',       -- "sarcastic", "supportive", "competitive"
        'event',         -- "monthly meetups", "annual party planning"
        'shared_knowledge'  -- "discussed movie X", "planning trip to Y"
    )),
    fact_key TEXT NOT NULL,      -- e.g., "humor_style", "weekly_tradition"
    fact_value TEXT NOT NULL,    -- e.g., "dark_sarcastic", "friday_recap"
    fact_description TEXT,       -- Human-readable: "Group prefers dark humor"
    confidence REAL DEFAULT 0.7,
    evidence_count INTEGER DEFAULT 1,  -- How many times reinforced
    first_observed INTEGER NOT NULL,
    last_reinforced INTEGER NOT NULL,
    participant_consensus REAL,  -- 0-1: what % of users agree
    is_active INTEGER DEFAULT 1,
    decay_rate REAL DEFAULT 0.0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (chat_id) REFERENCES chat_profiles(chat_id) ON DELETE CASCADE
);

-- Chat fact versions (track changes over time)
CREATE TABLE IF NOT EXISTS chat_fact_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER NOT NULL,
    previous_version_id INTEGER,
    version_number INTEGER NOT NULL,
    change_type TEXT CHECK(change_type IN (
        'creation', 'reinforcement', 'evolution', 'correction', 'deprecation'
    )),
    confidence_delta REAL,
    change_evidence TEXT,  -- What triggered the change
    created_at INTEGER NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES chat_facts(id) ON DELETE CASCADE,
    FOREIGN KEY (previous_version_id) REFERENCES chat_facts(id) ON DELETE SET NULL
);

-- Chat fact quality metrics (deduplication, conflicts)
CREATE TABLE IF NOT EXISTS chat_fact_quality_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    fact_id INTEGER NOT NULL,
    duplicate_of INTEGER,  -- References another chat_fact id
    conflict_with INTEGER,
    similarity_score REAL,
    resolution_method TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES chat_facts(id) ON DELETE CASCADE,
    FOREIGN KEY (chat_id) REFERENCES chat_profiles(chat_id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_chat_facts_chat 
    ON chat_facts(chat_id, is_active);
CREATE INDEX IF NOT EXISTS idx_chat_facts_category 
    ON chat_facts(fact_category);
CREATE INDEX IF NOT EXISTS idx_chat_facts_confidence 
    ON chat_facts(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_chat_facts_reinforced 
    ON chat_facts(last_reinforced DESC);

CREATE INDEX IF NOT EXISTS idx_chat_fact_versions_fact 
    ON chat_fact_versions(fact_id, version_number);

CREATE INDEX IF NOT EXISTS idx_chat_fact_quality_chat 
    ON chat_fact_quality_metrics(chat_id);
```

**Key Design Choices**:

- **Separate from user_facts**: Different lifecycle, different retrieval patterns
- **Category system**: Structured types for better querying
- **Consensus tracking**: `participant_consensus` measures agreement
- **Evidence count**: Track how many times fact was reinforced
- **Temporal versioning**: Same pattern as user facts
- **Quality metrics**: Deduplication and conflict resolution

---

### 2. Fact Categories Explained

| Category | Examples | Extraction Signals |
|----------|----------|-------------------|
| **preference** | "likes dark humor", "prefers voice over text" | "we like", "we prefer", emoji usage patterns |
| **tradition** | "Friday recaps", "Monday motivation" | Recurring patterns, "every week/month" |
| **rule** | "no politics", "Ukrainian only" | "don't", "forbidden", admin announcements |
| **norm** | "lots of emoji", "formal tone" | Statistical patterns, message style analysis |
| **topic** | "AI discussions", "crypto focus" | Frequent keywords, semantic clustering |
| **culture** | "sarcastic", "supportive" | Sentiment analysis, interaction patterns |
| **event** | "planning trip", "birthday next week" | Future-oriented, coordination messages |
| **shared_knowledge** | "discussed movie X", "researched topic Y" | Episode summaries, collective learning |

---

### 3. Fact Extraction

**Enhanced fact extractor detects group-level facts**:

```python
class ChatFactExtractor:
    """Extracts chat-level facts from group conversations."""
    
    async def extract_chat_facts(
        self,
        messages: List[Message],
        chat_id: int,
        window: ConversationWindow,
    ) -> List[ChatFact]:
        """
        Extract facts about the chat/group from conversation.
        
        Signals for chat-level facts:
        1. Plural pronouns: "we", "us", "our"
        2. Group decisions: "let's", "we should"
        3. Traditions: "always", "every [time period]"
        4. Norms: "usually", "typically", "here we"
        5. Statistical patterns: emoji usage, message length, formality
        """
        
        # Method 1: Pattern-based extraction (fast, 70% coverage)
        pattern_facts = await self._extract_via_patterns(messages)
        
        # Method 2: Statistical analysis (group behavior)
        statistical_facts = await self._extract_statistical_facts(messages)
        
        # Method 3: LLM-based (for complex cases)
        llm_facts = await self._extract_via_llm(messages, window)
        
        # Merge and deduplicate
        all_facts = pattern_facts + statistical_facts + llm_facts
        
        return await self._deduplicate_chat_facts(all_facts, chat_id)
    
    async def _extract_via_patterns(
        self, messages: List[Message]
    ) -> List[ChatFact]:
        """Pattern-based extraction for common chat facts."""
        
        facts = []
        
        for msg in messages:
            text = msg.text.lower()
            
            # Preference patterns
            if re.search(r'(we|us|our) (like|love|prefer|enjoy)', text):
                facts.append(ChatFact(
                    category='preference',
                    fact_key=self._extract_preference_key(text),
                    fact_value=self._extract_preference_value(text),
                    confidence=0.75,
                    evidence_text=msg.text[:200]
                ))
            
            # Tradition patterns
            if re.search(r'(every|always) (week|month|friday|monday)', text):
                facts.append(ChatFact(
                    category='tradition',
                    fact_key='recurring_event',
                    fact_value=self._extract_tradition(text),
                    confidence=0.8,
                    evidence_text=msg.text[:200]
                ))
            
            # Rule patterns
            if re.search(r'(no|don\'t|forbidden|rule)', text):
                facts.append(ChatFact(
                    category='rule',
                    fact_key='chat_rule',
                    fact_value=self._extract_rule(text),
                    confidence=0.85,
                    evidence_text=msg.text[:200]
                ))
            
            # Shared knowledge patterns
            if re.search(r'(we (discussed|talked about|decided))', text):
                facts.append(ChatFact(
                    category='shared_knowledge',
                    fact_key='past_discussion',
                    fact_value=self._extract_topic(text),
                    confidence=0.7,
                    evidence_text=msg.text[:200]
                ))
        
        return facts
    
    async def _extract_statistical_facts(
        self, messages: List[Message]
    ) -> List[ChatFact]:
        """Extract facts from message patterns and statistics."""
        
        facts = []
        
        # Analyze emoji usage
        emoji_count = sum(
            len(re.findall(r'[\U0001F300-\U0001F9FF]', m.text))
            for m in messages if m.text
        )
        
        if emoji_count / max(len(messages), 1) > 2:
            facts.append(ChatFact(
                category='norm',
                fact_key='emoji_usage',
                fact_value='high',
                fact_description='Chat uses many emoji reactions',
                confidence=0.8,
            ))
        
        # Analyze message length
        avg_length = sum(len(m.text) for m in messages if m.text) / max(len(messages), 1)
        
        if avg_length > 200:
            facts.append(ChatFact(
                category='norm',
                fact_key='message_style',
                fact_value='detailed_messages',
                fact_description='Chat prefers longer, detailed messages',
                confidence=0.75,
            ))
        
        # Analyze formality (simple heuristic)
        formal_count = sum(
            1 for m in messages if m.text and self._is_formal(m.text)
        )
        
        if formal_count / max(len(messages), 1) > 0.7:
            facts.append(ChatFact(
                category='culture',
                fact_key='communication_style',
                fact_value='formal',
                fact_description='Chat maintains formal communication',
                confidence=0.8,
            ))
        
        return facts
    
    async def _extract_via_llm(
        self,
        messages: List[Message],
        window: ConversationWindow,
    ) -> List[ChatFact]:
        """LLM-based extraction for complex chat dynamics."""
        
        # Build conversation summary
        conversation = "\n".join(
            f"User{m.from_user.id}: {m.text}"
            for m in messages[-10:] if m.text  # Last 10 messages
        )
        
        prompt = f"""Analyze this group chat conversation and identify GROUP-LEVEL facts.

Conversation:
{conversation}

Extract facts about the GROUP (not individuals), such as:
- Preferences: What does this group like/dislike?
- Traditions: Any recurring activities or patterns?
- Rules: Explicit or implicit group rules?
- Norms: How does the group communicate?
- Topics: What does the group discuss often?
- Culture: What's the group's vibe/personality?

Output JSON array of facts:
[
  {{
    "category": "preference|tradition|rule|norm|topic|culture",
    "fact_key": "short_key",
    "fact_value": "concise_value",
    "fact_description": "Human-readable description",
    "confidence": 0.0-1.0,
    "evidence": "quote from conversation"
  }}
]

Focus on GROUP facts only (e.g., "we prefer", "the chat likes", "everyone does").
Ignore individual facts (e.g., "John likes", "Alice said").
"""
        
        try:
            response = await self.gemini_client.generate(
                system_prompt="You are an expert at analyzing group chat dynamics.",
                history=[],
                user_parts=[{"text": prompt}],
            )
            
            # Parse JSON response
            import json
            facts_data = json.loads(response)
            
            return [
                ChatFact(
                    category=f['category'],
                    fact_key=f['fact_key'],
                    fact_value=f['fact_value'],
                    fact_description=f.get('fact_description'),
                    confidence=f.get('confidence', 0.7),
                    evidence_text=f.get('evidence'),
                )
                for f in facts_data
            ]
            
        except Exception as e:
            LOGGER.error(f"LLM chat fact extraction failed: {e}")
            return []
```

---

### 4. Storage & Retrieval

**New repository**: `app/repositories/chat_profile.py`

```python
class ChatProfileRepository(Repository):
    """Repository for chat profiles and facts."""
    
    async def get_or_create_profile(
        self, chat_id: int, chat_type: str, chat_title: str
    ) -> ChatProfile:
        """Get or create chat profile."""
        
        existing = await self._get_profile(chat_id)
        if existing:
            return existing
        
        # Create new profile
        now = int(time.time())
        await self._execute(
            """
            INSERT INTO chat_profiles 
            (chat_id, chat_type, chat_title, bot_joined_at, last_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, chat_type, chat_title, now, now, now, now)
        )
        
        return await self._get_profile(chat_id)
    
    async def add_chat_fact(
        self,
        chat_id: int,
        category: str,
        fact_key: str,
        fact_value: str,
        fact_description: str | None = None,
        confidence: float = 0.7,
        evidence_text: str | None = None,
    ) -> int:
        """
        Add or update a chat fact.
        
        If fact with same key exists:
        - Reinforcement: Boost confidence, update last_reinforced
        - Conflict: Resolve based on confidence + recency
        - Evolution: Create new version
        """
        
        # Check for existing fact with same key
        existing = await self._get_fact_by_key(chat_id, fact_key)
        
        now = int(time.time())
        
        if existing:
            # Check if it's the same value (reinforcement)
            if existing['fact_value'] == fact_value:
                # Boost confidence (weighted average)
                new_confidence = min(1.0, existing['confidence'] * 0.7 + confidence * 0.3)
                new_evidence_count = existing['evidence_count'] + 1
                
                await self._execute(
                    """
                    UPDATE chat_facts
                    SET confidence = ?,
                        evidence_count = ?,
                        last_reinforced = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (new_confidence, new_evidence_count, now, now, existing['id'])
                )
                
                # Record version (reinforcement)
                await self._record_fact_version(
                    existing['id'], None, existing['version_number'] + 1,
                    'reinforcement', confidence - existing['confidence']
                )
                
                return existing['id']
            
            else:
                # Different value - create new version
                # Deactivate old fact
                await self._execute(
                    "UPDATE chat_facts SET is_active = 0 WHERE id = ?",
                    (existing['id'],)
                )
                
                # Create new fact
                cursor = await self._execute(
                    """
                    INSERT INTO chat_facts
                    (chat_id, fact_category, fact_key, fact_value, fact_description,
                     confidence, evidence_count, first_observed, last_reinforced,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (chat_id, category, fact_key, fact_value, fact_description,
                     confidence, now, now, now, now)
                )
                
                new_fact_id = cursor.lastrowid
                
                # Record version (evolution)
                await self._record_fact_version(
                    new_fact_id, existing['id'],
                    existing['version_number'] + 1,
                    'evolution', confidence - existing['confidence']
                )
                
                return new_fact_id
        
        else:
            # New fact
            cursor = await self._execute(
                """
                INSERT INTO chat_facts
                (chat_id, fact_category, fact_key, fact_value, fact_description,
                 confidence, evidence_count, first_observed, last_reinforced,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (chat_id, category, fact_key, fact_value, fact_description,
                 confidence, now, now, now, now)
            )
            
            fact_id = cursor.lastrowid
            
            # Record version (creation)
            await self._record_fact_version(
                fact_id, None, 1, 'creation', confidence
            )
            
            return fact_id
    
    async def get_top_chat_facts(
        self,
        chat_id: int,
        limit: int = 10,
        min_confidence: float = 0.6,
        categories: List[str] | None = None,
    ) -> List[ChatFact]:
        """
        Get top chat facts for context inclusion.
        
        Ranking factors:
        - Confidence (higher = better)
        - Recency (last_reinforced closer to now = better)
        - Evidence count (more reinforcement = better)
        - Category priority (rules > preferences > norms)
        """
        
        category_weights = {
            'rule': 1.5,
            'preference': 1.2,
            'tradition': 1.1,
            'culture': 1.0,
            'norm': 0.9,
            'topic': 0.8,
            'shared_knowledge': 0.7,
            'event': 0.6,
        }
        
        query = """
            SELECT * FROM chat_facts
            WHERE chat_id = ?
            AND is_active = 1
            AND confidence >= ?
        """
        params = [chat_id, min_confidence]
        
        if categories:
            placeholders = ','.join('?' * len(categories))
            query += f" AND fact_category IN ({placeholders})"
            params.extend(categories)
        
        query += " ORDER BY confidence DESC, last_reinforced DESC"
        
        rows = await self._fetch_all(query, tuple(params))
        
        # Apply category weighting and temporal decay
        now = int(time.time())
        scored_facts = []
        
        for row in rows:
            # Base score from confidence
            score = row['confidence']
            
            # Category weight
            category_weight = category_weights.get(row['fact_category'], 1.0)
            score *= category_weight
            
            # Temporal decay (half-life = 30 days for chat facts)
            age_seconds = now - row['last_reinforced']
            age_days = age_seconds / 86400
            temporal_factor = math.exp(-age_days / 30)
            score *= (0.5 + 0.5 * temporal_factor)  # Don't fully decay
            
            # Evidence count boost (more reinforcement = better)
            evidence_boost = min(1.5, 1.0 + (row['evidence_count'] - 1) * 0.1)
            score *= evidence_boost
            
            scored_facts.append((score, row))
        
        # Sort by final score
        scored_facts.sort(key=lambda x: x[0], reverse=True)
        
        # Return top facts
        return [
            ChatFact.from_row(row)
            for score, row in scored_facts[:limit]
        ]
    
    async def get_chat_summary(
        self, chat_id: int, max_facts: int = 10
    ) -> str:
        """
        Generate concise chat profile summary for context.
        
        Format:
        Chat Profile:
        - Preferences: [top 2-3]
        - Rules: [top 1-2]
        - Culture: [top 1-2]
        """
        
        facts = await self.get_top_chat_facts(chat_id, limit=max_facts)
        
        if not facts:
            return None
        
        # Group by category
        by_category = {}
        for fact in facts:
            by_category.setdefault(fact.category, []).append(fact)
        
        # Build summary
        summary_parts = ["Chat Profile:"]
        
        # Prioritize categories
        priority_categories = ['rule', 'preference', 'tradition', 'culture', 'norm']
        
        for category in priority_categories:
            if category not in by_category:
                continue
            
            category_facts = by_category[category][:3]  # Top 3 per category
            
            if category_facts:
                category_label = category.replace('_', ' ').title()
                fact_descriptions = [
                    f.fact_description or f"{f.fact_key}: {f.fact_value}"
                    for f in category_facts
                ]
                summary_parts.append(
                    f"- {category_label}: {', '.join(fact_descriptions)}"
                )
        
        return "\n".join(summary_parts)
```

---

### 5. Context Integration

**Enhanced `MultiLevelContextManager._get_background_context()`**:

```python
async def _get_background_context(
    self,
    user_id: int,
    chat_id: int,
    query: str,
    max_tokens: int,
) -> BackgroundContext:
    """
    Get background context - user profile AND chat profile.
    
    Token allocation:
    - User profile: 60% of budget
    - Chat profile: 40% of budget
    """
    
    user_budget = int(max_tokens * 0.6)
    chat_budget = int(max_tokens * 0.4)
    
    # Get user profile (existing logic)
    user_summary = await self.profile_store.get_user_summary(
        user_id, chat_id, max_facts=10
    )
    
    user_facts = await self.profile_store.get_facts(
        user_id, chat_id, limit=10
    )
    
    # Get chat profile (NEW)
    chat_summary = await self.chat_profile_store.get_chat_summary(
        chat_id, max_facts=8
    )
    
    chat_facts = await self.chat_profile_store.get_top_chat_facts(
        chat_id, limit=8, min_confidence=0.7
    )
    
    # Estimate tokens
    user_tokens = self._estimate_text_tokens(user_summary) if user_summary else 0
    user_tokens += sum(
        len(f['fact_key'].split() + f['fact_value'].split()) * 1.3
        for f in user_facts
    )
    
    chat_tokens = self._estimate_text_tokens(chat_summary) if chat_summary else 0
    chat_tokens += sum(
        len(f.fact_description.split()) * 1.3 if f.fact_description else 20
        for f in chat_facts
    )
    
    # Truncate if over budget
    if user_tokens > user_budget:
        user_facts = user_facts[:int(user_budget / 25)]
    
    if chat_tokens > chat_budget:
        chat_facts = chat_facts[:int(chat_budget / 30)]
    
    total_tokens = int(user_tokens + chat_tokens)
    
    return BackgroundContext(
        user_profile_summary=user_summary,
        user_key_facts=user_facts,
        chat_profile_summary=chat_summary,  # NEW
        chat_key_facts=chat_facts,          # NEW
        relationships=[],
        token_count=total_tokens,
    )
```

**Enhanced context formatting**:

```python
def format_for_gemini(self, context: LayeredContext) -> dict[str, Any]:
    """Format with chat profile included."""
    
    system_parts = []
    
    # User profile
    if context.background and context.background.user_profile_summary:
        system_parts.append(
            f"User Profile: {context.background.user_profile_summary}"
        )
    
    # Chat profile (NEW)
    if context.background and context.background.chat_profile_summary:
        system_parts.append(
            f"\n{context.background.chat_profile_summary}"
        )
    
    # ... rest of formatting ...
```

---

### 6. Extraction Integration

**Enhanced `ContinuousMonitor._extract_facts_from_window()`**:

```python
async def _extract_facts_from_window(
    self, window: ConversationWindow
) -> tuple[list[dict], list[ChatFact]]:
    """
    Extract both user facts AND chat facts from window.
    
    Returns:
        (user_facts, chat_facts)
    """
    
    # Existing user fact extraction
    user_facts = await self._extract_user_facts(window)
    
    # NEW: Chat fact extraction
    chat_facts = await self.chat_fact_extractor.extract_chat_facts(
        messages=window.raw_messages,  # Need access to Message objects
        chat_id=window.chat_id,
        window=window,
    )
    
    return user_facts, chat_facts

async def _store_facts(
    self,
    user_facts: list[dict],
    chat_facts: list[ChatFact],
    window: ConversationWindow,
) -> None:
    """Store both user and chat facts."""
    
    # Store user facts (existing logic)
    await self._store_user_facts(user_facts, window)
    
    # Store chat facts (NEW)
    for chat_fact in chat_facts:
        try:
            await self.chat_profile_store.add_chat_fact(
                chat_id=window.chat_id,
                category=chat_fact.category,
                fact_key=chat_fact.fact_key,
                fact_value=chat_fact.fact_value,
                fact_description=chat_fact.fact_description,
                confidence=chat_fact.confidence,
                evidence_text=chat_fact.evidence_text,
            )
        except Exception as e:
            LOGGER.error(f"Failed to store chat fact: {e}")
```

---

## Context Budget Management

**Token allocation within BackgroundContext**:

```
Total Background Budget: 1200 tokens (15% of 8000 total)

├─ User Profile: 720 tokens (60%)
│  ├─ Profile summary: ~300 tokens
│  ├─ Top 10 facts: ~420 tokens (42 each)
│
└─ Chat Profile: 480 tokens (40%)
   ├─ Chat summary: ~200 tokens
   ├─ Top 8 facts: ~280 tokens (35 each)
```

**Example formatted context**:

```
User Profile: Alice is a software engineer from Kyiv who speaks Ukrainian 
and English. She's interested in AI and enjoys dark humor. Vegetarian.

Chat Profile:
- Rules: No politics, Ukrainian preferred but English OK
- Preferences: Dark humor, technical discussions, lots of emoji
- Traditions: Friday recap of the week
- Culture: Supportive but sarcastic, active participation

[Relevant snippets, episodes, etc...]
```

**Total overhead**: ~200-400 tokens (2.5-5% of total context budget)

---

## Implementation Phases

### Phase 1: Schema & Repository (Week 1)

**Tasks**:
1. Add `chat_profiles`, `chat_facts`, `chat_fact_versions` tables
2. Create migration script
3. Implement `ChatProfileRepository`
4. Unit tests for repository
5. Database integrity tests

**Deliverables**:
- ✅ Updated `db/schema.sql`
- ✅ `app/repositories/chat_profile.py`
- ✅ Migration script
- ✅ Tests

---

### Phase 2: Extraction (Week 2)

**Tasks**:
1. Implement `ChatFactExtractor` class
2. Pattern-based extraction (regex, keywords)
3. Statistical extraction (emoji, length, formality)
4. LLM-based extraction (Gemini)
5. Deduplication logic
6. Integration tests

**Deliverables**:
- ✅ `app/services/fact_extractors/chat_fact_extractor.py`
- ✅ Pattern library
- ✅ Tests with real conversation samples

---

### Phase 3: Integration (Week 3)

**Tasks**:
1. Integrate with `ContinuousMonitor`
2. Update `MultiLevelContextManager`
3. Enhanced `BackgroundContext` dataclass
4. Context formatting updates
5. Token budget tuning
6. End-to-end tests

**Deliverables**:
- ✅ Updated monitoring pipeline
- ✅ Enhanced context assembly
- ✅ Integration tests

---

### Phase 4: Quality & Polish (Week 4)

**Tasks**:
1. Fact quality management (deduplication, conflicts)
2. Temporal decay tuning
3. Category priority optimization
4. Admin commands (`/gryadchatfacts`, `/gryadchatreset`)
5. Monitoring and logging
6. Performance optimization
7. Documentation

**Deliverables**:
- ✅ Quality manager for chat facts
- ✅ Admin tools
- ✅ Performance report
- ✅ User documentation

---

## Configuration

**Add to `app/config.py`**:

```python
class Settings(BaseSettings):
    # ... existing settings ...
    
    # ═══════════════════════════════════════════════════════════
    # Chat Public Memory
    # ═══════════════════════════════════════════════════════════
    
    # Master switch
    enable_chat_memory: bool = True
    
    # Extraction
    enable_chat_fact_extraction: bool = True
    chat_fact_min_confidence: float = 0.6
    chat_fact_extraction_method: str = "hybrid"  # pattern, statistical, llm, hybrid
    
    # Retrieval
    chat_facts_in_context: bool = True
    max_chat_facts_in_context: int = 8
    chat_context_token_budget: int = 480  # 40% of background budget
    
    # Quality
    enable_chat_fact_deduplication: bool = True
    chat_fact_similarity_threshold: float = 0.85
    chat_fact_temporal_half_life_days: int = 30
    
    # Categories
    chat_fact_category_priority: Dict[str, float] = {
        'rule': 1.5,
        'preference': 1.2,
        'tradition': 1.1,
        'culture': 1.0,
        'norm': 0.9,
        'topic': 0.8,
        'shared_knowledge': 0.7,
        'event': 0.6,
    }
```

---

## Admin Commands

**New commands for managing chat memory**:

```python
@router.message(Command("gryadchatfacts"))
async def show_chat_facts(message: Message, chat_profile_store: ChatProfileStore):
    """Show current chat facts."""
    
    facts = await chat_profile_store.get_top_chat_facts(
        message.chat.id, limit=20
    )
    
    if not facts:
        await message.reply("Немає збережених фактів про цей чат")
        return
    
    # Group by category
    by_category = {}
    for fact in facts:
        by_category.setdefault(fact.category, []).append(fact)
    
    # Format response
    response_parts = ["📊 Факти про чат:\n"]
    
    for category, category_facts in sorted(by_category.items()):
        category_label = category.replace('_', ' ').title()
        response_parts.append(f"\n{category_label}:")
        
        for fact in category_facts:
            confidence_bar = "▰" * int(fact.confidence * 5)
            response_parts.append(
                f"  • {fact.fact_description or fact.fact_value} "
                f"({confidence_bar} {fact.confidence:.0%}, "
                f"{fact.evidence_count}x)"
            )
    
    await message.reply("\n".join(response_parts))


@router.message(Command("gryadchatreset"))
async def reset_chat_facts(message: Message, chat_profile_store: ChatProfileStore):
    """Reset all chat facts (admin only)."""
    
    if not is_admin(message.from_user.id):
        await message.reply("Лише адміни можуть скидати факти чату")
        return
    
    deleted = await chat_profile_store.delete_all_facts(message.chat.id)
    
    await message.reply(
        f"Видалено {deleted} фактів про чат. "
        f"Починаю вчитися заново..."
    )
```

---

## Testing Strategy

### Unit Tests

1. **Repository tests**:
   - Create/update chat profile
   - Add/reinforce facts
   - Fact versioning
   - Deduplication
   - Ranking algorithm

2. **Extraction tests**:
   - Pattern matching
   - Statistical analysis
   - LLM parsing
   - Category classification

### Integration Tests

1. **End-to-end flow**:
   - Conversation → extraction → storage → retrieval
   - Context assembly with chat facts
   - Token budget enforcement

2. **Quality tests**:
   - Duplicate detection
   - Conflict resolution
   - Temporal decay

### Manual Testing

**Test scenarios**:

```
Scenario 1: Group Preference
User1: "Хлопці, давайте більше українською спілкуватися"
User2: "Підтримую!"
User3: "+1, українська краща"

Expected: Extract chat fact:
  - category: preference
  - fact_key: language_preference
  - fact_value: ukrainian
  - confidence: 0.8+

Scenario 2: Tradition
User1: "Як завжди, в п'ятницю підіб'ємо підсумки"
User2: "Так, це вже традиція :)"

Expected: Extract chat fact:
  - category: tradition
  - fact_key: weekly_recap
  - fact_value: friday
  - confidence: 0.85+

Scenario 3: Rule
Admin: "Нагадую: ніякої політики в чаті!"
User: "Зрозуміло"

Expected: Extract chat fact:
  - category: rule
  - fact_key: forbidden_topics
  - fact_value: politics
  - confidence: 0.9+
```

---

## Success Metrics

### Extraction Quality

- [ ] Chat fact extraction accuracy >75%
- [ ] Deduplication rate >80%
- [ ] False positive rate <10%
- [ ] Category classification accuracy >85%

### Context Quality

- [ ] Chat facts appear in context when relevant
- [ ] Token budget maintained (400 tokens max)
- [ ] No context window overflow
- [ ] Retrieval latency <50ms

### User Experience

- [ ] Bot demonstrates group awareness in responses
- [ ] Fewer repetitive questions about group preferences
- [ ] Better alignment with chat culture/norms
- [ ] Positive user feedback on awareness

### System Health

- [ ] No performance degradation
- [ ] Database growth within expected bounds (<5% increase)
- [ ] No errors in extraction pipeline
- [ ] Graceful fallback if extraction fails

---

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Noisy extraction** | Low-quality facts pollute context | Min confidence threshold (0.6), deduplication, quality scoring |
| **Context bloat** | Token budget exceeded | Strict limits (8 facts max, 480 tokens), ranking algorithm |
| **Privacy concerns** | Sensitive group info leaked | Admins can reset, facts expire after 90 days by default |
| **Extraction errors** | LLM hallucinates fake facts | Pattern-based fallback, confidence thresholds, human review via `/gryadchatfacts` |
| **Performance** | Slow extraction | Async processing, pattern-first (fast), LLM only when needed |

---

## Future Enhancements

### Short-term (3-6 months)

1. **Consensus tracking**: Weight facts by how many users agree
2. **Fact suggestions**: Bot proactively asks to confirm detected patterns
3. **Cross-chat learning**: Similar chats share patterns (privacy-preserving)
4. **Visualization**: Show chat "personality profile"

### Long-term (6-12 months)

1. **Hierarchical facts**: Topics → subtopics, nested preferences
2. **Temporal patterns**: Track how chat culture evolves over time
3. **Predictive facts**: Anticipate group needs based on patterns
4. **Multi-modal**: Extract facts from images, voice messages

---

## Conclusion

Chat Public Memory extends the bot's existing sophisticated memory system to include **group-level awareness**. By extracting and maintaining chat-scoped facts, the bot can:

- ✅ Understand group preferences and culture
- ✅ Remember shared decisions and traditions
- ✅ Respect chat-specific rules and norms
- ✅ Provide more contextually appropriate responses

**Implementation**: 4 weeks, phased rollout
**Risk**: Low (extends existing patterns, optional feature)
**Impact**: Medium-High (noticeably improves group awareness)

The design prioritizes **conciseness** (strict token budgets), **quality** (deduplication, confidence scoring), and **seamless integration** (reuses existing infrastructure).

---

## How to Verify

After implementation:

1. **Schema check**: `sqlite3 gryag.db ".schema chat_facts"`
2. **Test extraction**: Have conversation with clear group preference, check `/gryadchatfacts`
3. **Context verification**: Enable debug logging, verify chat facts appear in system prompt
4. **Token budget**: Log context assembly, confirm <500 tokens for background context
5. **User testing**: Ask bot about "our preferences" - should reference chat facts

---

**Document Version**: 1.0  
**Status**: Ready for Review  
**Next Steps**: Review plan, approve schema, begin Phase 1

**Estimated effort**: 4 weeks  
**Expected token overhead**: 200-400 tokens (2.5-5% of budget)  
**Integration complexity**: Low (reuses existing patterns)
