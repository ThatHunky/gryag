# Phase 4: Proactive Responses - Implementation Plan

**Status**: Planning  
**Dependencies**: Phase 3 (Continuous Learning) must be active  
**Timeline**: Week 5-6 (estimated 12-15 hours)  
**Risk Level**: Medium-High (changes bot behavior, user-facing)

## Executive Summary

Phase 4 enables the bot to **proactively join conversations** when it can add value, transforming from "answer when asked" to "participate naturally." This is the most visible change to users and requires careful tuning to avoid being intrusive.

**Key Principles**:
- 🎯 **Conservative by default**: Better to stay silent than spam
- 🧠 **Context-aware**: Only respond when relevant to conversation
- 👤 **User-adaptive**: Learn each user's preferences for proactivity
- ⏱️ **Cooldown-limited**: Enforce 5+ minute gaps between proactive messages
- 🚨 **Safety-first**: Multiple checks before sending

## Current State vs. Target

### Current Behavior (Phase 3)
```
User: "What's the weather in Kyiv?"
Bot: [responds - addressed message]

User A: "I'm going to Kyiv tomorrow"
User B: "Nice! What's the weather like?"
Bot: [silent - learning facts, not responding]
```

### Target Behavior (Phase 4)
```
User: "What's the weather in Kyiv?"
Bot: [responds - addressed message]

User A: "I'm going to Kyiv tomorrow"
User B: "Nice! What's the weather like?"
Bot: [detects weather query about location just mentioned]
Bot: "The weather in Kyiv tomorrow is 18°C, partly cloudy ☁️"
     [proactive response - not addressed, but contextually relevant]
```

## Architecture Overview

### Components

1. **IntentClassifier** (new class in `proactive_trigger.py`)
   - Detects conversation intents: `question`, `request`, `problem`, `opportunity`
   - Uses Gemini to classify window content
   - Scores intent confidence (0.0-1.0)

2. **UserPreferenceManager** (new class in `proactive_trigger.py`)
   - Tracks user reactions: `positive`, `neutral`, `negative`, `ignored`
   - Manages per-user cooldowns and spam protection
   - Adapts proactivity level per user

3. **ResponseTrigger** (extends `ProactiveTrigger` class)
   - Decides when to send proactive response
   - Enforces safety limits and cooldowns
   - Scores response relevance

4. **ProactiveResponse** (new dataclass)
   - Encapsulates response decision with justification
   - Stores context, confidence, reason

### Data Model Extensions

```sql
-- New table for tracking proactive responses
CREATE TABLE IF NOT EXISTS proactive_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER,  -- NULL = bot-initiated
    window_id INTEGER,
    intent_type TEXT NOT NULL,  -- question, request, problem, opportunity
    confidence REAL NOT NULL,
    response_text TEXT NOT NULL,
    context_summary TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- User reaction tracking
    reaction TEXT,  -- positive, neutral, negative, ignored, NULL (pending)
    reaction_time_seconds INTEGER,  -- How long until reaction
    
    FOREIGN KEY (window_id) REFERENCES conversation_windows(id)
);

-- Index for cooldown checks
CREATE INDEX IF NOT EXISTS idx_proactive_cooldown 
ON proactive_responses(chat_id, sent_at);

-- Index for preference learning
CREATE INDEX IF NOT EXISTS idx_proactive_reactions 
ON proactive_responses(user_id, reaction);
```

### Configuration Settings

```python
# Add to app/config.py

class Settings:
    # ... existing settings ...
    
    # Proactive Response Settings
    ENABLE_PROACTIVE_RESPONSES: bool = False  # Master switch
    
    # Intent Classification
    PROACTIVE_MIN_CONFIDENCE: float = 0.7  # Minimum intent confidence
    PROACTIVE_INTENT_TYPES: list = [
        "question",      # User asks question bot can answer
        "request",       # User requests information/action
        "problem",       # User describes problem bot can help with
        "opportunity",   # Bot has relevant info to share
    ]
    
    # Cooldowns (seconds)
    PROACTIVE_GLOBAL_COOLDOWN: int = 300  # 5 minutes between any proactive
    PROACTIVE_PER_USER_COOLDOWN: int = 600  # 10 minutes per user
    PROACTIVE_SAME_INTENT_COOLDOWN: int = 1800  # 30 minutes for same intent type
    
    # Safety Limits
    PROACTIVE_MAX_PER_HOUR: int = 6  # Max proactive responses per hour
    PROACTIVE_MAX_PER_DAY: int = 40  # Max proactive responses per day
    PROACTIVE_MAX_CONSECUTIVE: int = 2  # Max consecutive without user response
    
    # User Preferences
    PROACTIVE_LEARN_FROM_REACTIONS: bool = True  # Adapt per user
    PROACTIVE_NEGATIVE_REACTION_PENALTY: float = 0.5  # Reduce confidence by 50%
    PROACTIVE_IGNORED_THRESHOLD: int = 3  # After 3 ignores, reduce proactivity
    
    # Context Requirements
    PROACTIVE_MIN_WINDOW_SIZE: int = 3  # Need at least 3 messages
    PROACTIVE_REQUIRE_RECENT_ACTIVITY: bool = True  # Only if chat active
    PROACTIVE_RECENT_ACTIVITY_SECONDS: int = 180  # Within 3 minutes
```

## Implementation Tasks

### Task 1: Intent Classification System

**File**: `app/services/monitoring/proactive_trigger.py`

**Implementation**:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class IntentType(Enum):
    """Types of conversation intents we can respond to."""
    QUESTION = "question"  # User asks something
    REQUEST = "request"    # User wants information/action
    PROBLEM = "problem"    # User describes issue
    OPPORTUNITY = "opportunity"  # Bot has relevant info

@dataclass
class ConversationIntent:
    """Detected intent in conversation window."""
    intent_type: IntentType
    confidence: float  # 0.0-1.0
    trigger_message: str  # The message that triggered detection
    context_summary: str  # What the conversation is about
    suggested_response: Optional[str] = None  # Optional AI suggestion
    
class IntentClassifier:
    """Detects conversation intents for proactive responses."""
    
    def __init__(self, gemini_client, settings):
        self.gemini = gemini_client
        self.settings = settings
        self._intent_cache = {}  # window_id -> ConversationIntent
        
    async def classify_window(
        self, 
        window: ConversationWindow,
        bot_capabilities: list[str]
    ) -> Optional[ConversationIntent]:
        """
        Analyze window to detect if proactive response would be helpful.
        
        Args:
            window: Conversation window to analyze
            bot_capabilities: List of bot capabilities (e.g., ["weather", "currency", "search"])
            
        Returns:
            ConversationIntent if opportunity detected, None otherwise
        """
        # Check cache first
        if window.id in self._intent_cache:
            return self._intent_cache[window.id]
            
        # Build conversation context
        conversation_text = self._build_conversation_text(window)
        
        # Prompt Gemini to classify intent
        prompt = self._build_classification_prompt(
            conversation_text,
            bot_capabilities,
            window.participant_count
        )
        
        try:
            response = await self.gemini.generate(
                message=prompt,
                context=[],
                system_prompt=self._get_intent_system_prompt()
            )
            
            intent = self._parse_intent_response(response, window)
            
            if intent and intent.confidence >= self.settings.PROACTIVE_MIN_CONFIDENCE:
                self._intent_cache[window.id] = intent
                return intent
                
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            
        return None
        
    def _build_conversation_text(self, window: ConversationWindow) -> str:
        """Build readable conversation from window."""
        lines = []
        for msg in window.messages[-5:]:  # Last 5 messages
            username = msg.username or f"User{msg.user_id}"
            lines.append(f"{username}: {msg.text}")
        return "\n".join(lines)
        
    def _build_classification_prompt(
        self,
        conversation: str,
        capabilities: list[str],
        participant_count: int
    ) -> str:
        """Build prompt for intent classification."""
        return f"""Analyze this conversation and determine if I should proactively respond.

Conversation:
{conversation}

My capabilities: {', '.join(capabilities)}
Participants: {participant_count}

Should I respond proactively? Consider:
1. Is there an unanswered question I can help with?
2. Did someone request information I can provide?
3. Is there a problem I can solve?
4. Do I have relevant information that would add value?

Response format (JSON):
{{
    "should_respond": true/false,
    "intent_type": "question|request|problem|opportunity",
    "confidence": 0.0-1.0,
    "context_summary": "brief description",
    "suggested_response": "optional response text"
}}

Be conservative - only respond if genuinely helpful."""
        
    def _get_intent_system_prompt(self) -> str:
        """System prompt for intent classification."""
        return """You are analyzing conversations to detect when a bot should proactively respond.
        
Rules:
- Be VERY conservative - silence is better than spam
- Only suggest responses that add clear value
- Consider conversation flow and social dynamics
- Respect that users may not want bot involvement
- Return structured JSON only"""
        
    def _parse_intent_response(
        self, 
        response: str,
        window: ConversationWindow
    ) -> Optional[ConversationIntent]:
        """Parse Gemini's intent classification response."""
        try:
            import json
            data = json.loads(response)
            
            if not data.get("should_respond", False):
                return None
                
            intent_type = IntentType(data["intent_type"])
            confidence = float(data["confidence"])
            
            return ConversationIntent(
                intent_type=intent_type,
                confidence=confidence,
                trigger_message=window.messages[-1].text if window.messages else "",
                context_summary=data.get("context_summary", ""),
                suggested_response=data.get("suggested_response")
            )
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse intent response: {e}")
            return None
```

**Testing Strategy**:
1. Test with conversations that should NOT trigger response (chitchat, complete exchanges)
2. Test with conversations that SHOULD trigger (unanswered questions, requests for help)
3. Verify confidence scores are calibrated (70%+ = high confidence)
4. Check JSON parsing handles malformed responses

### Task 2: User Preference Learning

**File**: `app/services/monitoring/proactive_trigger.py`

**Implementation**:

```python
from collections import defaultdict
from datetime import datetime, timedelta

class UserReaction(Enum):
    """User reactions to proactive responses."""
    POSITIVE = "positive"    # Engaged with response (replied, reacted positively)
    NEUTRAL = "neutral"      # Acknowledged but didn't engage
    NEGATIVE = "negative"    # Expressed annoyance or asked to stop
    IGNORED = "ignored"      # No reaction within timeout

@dataclass
class UserPreference:
    """Learned preferences for proactive responses."""
    user_id: int
    proactivity_multiplier: float  # 0.0-2.0, default 1.0
    last_proactive_response: Optional[datetime]
    total_proactive_sent: int
    reaction_counts: dict[UserReaction, int]
    consecutive_ignores: int
    last_negative_feedback: Optional[datetime]

class UserPreferenceManager:
    """Manages user preferences for proactive responses."""
    
    def __init__(self, context_store, settings):
        self.store = context_store
        self.settings = settings
        self._preferences = {}  # user_id -> UserPreference
        
    async def get_preference(self, user_id: int) -> UserPreference:
        """Get user's proactive response preferences."""
        if user_id not in self._preferences:
            self._preferences[user_id] = await self._load_preference(user_id)
        return self._preferences[user_id]
        
    async def _load_preference(self, user_id: int) -> UserPreference:
        """Load preference from database."""
        # Query proactive_responses table for user's history
        conn = await self.store._get_connection()
        cursor = await conn.execute("""
            SELECT 
                COUNT(*) as total,
                MAX(sent_at) as last_sent,
                SUM(CASE WHEN reaction = 'positive' THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN reaction = 'neutral' THEN 1 ELSE 0 END) as neutral,
                SUM(CASE WHEN reaction = 'negative' THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN reaction = 'ignored' THEN 1 ELSE 0 END) as ignored
            FROM proactive_responses
            WHERE user_id = ?
        """, (user_id,))
        
        row = await cursor.fetchone()
        
        # Calculate proactivity multiplier based on history
        multiplier = self._calculate_multiplier(
            positive=row[2] or 0,
            neutral=row[3] or 0,
            negative=row[4] or 0,
            ignored=row[5] or 0
        )
        
        # Check for consecutive ignores
        cursor = await conn.execute("""
            SELECT reaction
            FROM proactive_responses
            WHERE user_id = ?
            ORDER BY sent_at DESC
            LIMIT 5
        """, (user_id,))
        
        recent_reactions = [r[0] for r in await cursor.fetchall()]
        consecutive_ignores = 0
        for reaction in recent_reactions:
            if reaction == "ignored":
                consecutive_ignores += 1
            else:
                break
                
        return UserPreference(
            user_id=user_id,
            proactivity_multiplier=multiplier,
            last_proactive_response=row[1],
            total_proactive_sent=row[0] or 0,
            reaction_counts={
                UserReaction.POSITIVE: row[2] or 0,
                UserReaction.NEUTRAL: row[3] or 0,
                UserReaction.NEGATIVE: row[4] or 0,
                UserReaction.IGNORED: row[5] or 0,
            },
            consecutive_ignores=consecutive_ignores,
            last_negative_feedback=None  # Would need separate query
        )
        
    def _calculate_multiplier(
        self, 
        positive: int, 
        neutral: int, 
        negative: int, 
        ignored: int
    ) -> float:
        """
        Calculate proactivity multiplier based on reaction history.
        
        Returns:
            0.0-2.0 multiplier (1.0 = normal, <1.0 = reduce, >1.0 = increase)
        """
        total = positive + neutral + negative + ignored
        if total == 0:
            return 1.0  # No history, default
            
        # Positive reactions increase multiplier
        positive_ratio = positive / total
        negative_ratio = negative / total
        ignored_ratio = ignored / total
        
        # Base multiplier
        multiplier = 1.0
        
        # Adjust based on ratios
        if positive_ratio > 0.5:  # >50% positive
            multiplier += 0.3
        elif positive_ratio > 0.3:  # >30% positive
            multiplier += 0.1
            
        if negative_ratio > 0.2:  # >20% negative
            multiplier -= 0.5
        elif negative_ratio > 0.1:  # >10% negative
            multiplier -= 0.3
            
        if ignored_ratio > 0.6:  # >60% ignored
            multiplier -= 0.4
        elif ignored_ratio > 0.4:  # >40% ignored
            multiplier -= 0.2
            
        # Clamp to 0.0-2.0
        return max(0.0, min(2.0, multiplier))
        
    async def record_reaction(
        self,
        response_id: int,
        reaction: UserReaction,
        reaction_time: Optional[int] = None
    ):
        """Record user's reaction to proactive response."""
        conn = await self.store._get_connection()
        await conn.execute("""
            UPDATE proactive_responses
            SET reaction = ?, reaction_time_seconds = ?
            WHERE id = ?
        """, (reaction.value, reaction_time, response_id))
        await conn.commit()
        
        # Invalidate cache for this user
        cursor = await conn.execute(
            "SELECT user_id FROM proactive_responses WHERE id = ?",
            (response_id,)
        )
        row = await cursor.fetchone()
        if row and row[0] in self._preferences:
            del self._preferences[row[0]]
            
    async def check_cooldown(
        self,
        chat_id: int,
        user_id: Optional[int] = None,
        intent_type: Optional[IntentType] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Check if cooldown period has passed.
        
        Returns:
            (allowed, reason) - True if can send, False + reason if blocked
        """
        conn = await self.store._get_connection()
        
        # Check global cooldown (any proactive in last N minutes)
        cursor = await conn.execute("""
            SELECT sent_at FROM proactive_responses
            WHERE chat_id = ?
            ORDER BY sent_at DESC
            LIMIT 1
        """, (chat_id,))
        
        row = await cursor.fetchone()
        if row:
            last_sent = datetime.fromisoformat(row[0])
            elapsed = (datetime.now() - last_sent).total_seconds()
            
            if elapsed < self.settings.PROACTIVE_GLOBAL_COOLDOWN:
                return False, f"Global cooldown: {int(elapsed)}s / {self.settings.PROACTIVE_GLOBAL_COOLDOWN}s"
                
        # Check per-user cooldown if user specified
        if user_id:
            cursor = await conn.execute("""
                SELECT sent_at FROM proactive_responses
                WHERE chat_id = ? AND user_id = ?
                ORDER BY sent_at DESC
                LIMIT 1
            """, (chat_id, user_id))
            
            row = await cursor.fetchone()
            if row:
                last_sent = datetime.fromisoformat(row[0])
                elapsed = (datetime.now() - last_sent).total_seconds()
                
                if elapsed < self.settings.PROACTIVE_PER_USER_COOLDOWN:
                    return False, f"User cooldown: {int(elapsed)}s / {self.settings.PROACTIVE_PER_USER_COOLDOWN}s"
                    
        # Check same-intent cooldown if intent specified
        if intent_type:
            cursor = await conn.execute("""
                SELECT sent_at FROM proactive_responses
                WHERE chat_id = ? AND intent_type = ?
                ORDER BY sent_at DESC
                LIMIT 1
            """, (chat_id, intent_type.value))
            
            row = await cursor.fetchone()
            if row:
                last_sent = datetime.fromisoformat(row[0])
                elapsed = (datetime.now() - last_sent).total_seconds()
                
                if elapsed < self.settings.PROACTIVE_SAME_INTENT_COOLDOWN:
                    return False, f"Intent cooldown: {int(elapsed)}s / {self.settings.PROACTIVE_SAME_INTENT_COOLDOWN}s"
                    
        return True, None
```

**Testing Strategy**:
1. Test multiplier calculation with various reaction ratios
2. Test cooldown enforcement (global, per-user, per-intent)
3. Test preference loading from empty database
4. Verify consecutive ignores reduce proactivity

### Task 3: Response Trigger Logic

**File**: `app/services/monitoring/proactive_trigger.py` (extend existing class)

**Implementation**:

```python
@dataclass
class ProactiveResponse:
    """Decision about proactive response."""
    should_respond: bool
    confidence: float
    intent: Optional[ConversationIntent]
    reason: str  # Why we should/shouldn't respond
    suggested_response: Optional[str] = None
    
class ProactiveTrigger:
    """Decides when to send proactive responses."""
    
    def __init__(
        self,
        context_store,
        gemini_client,
        settings
    ):
        self.store = context_store
        self.gemini = gemini_client
        self.settings = settings
        
        self.intent_classifier = IntentClassifier(gemini_client, settings)
        self.preference_manager = UserPreferenceManager(context_store, settings)
        
        # Stats
        self.stats = {
            "windows_analyzed": 0,
            "intents_detected": 0,
            "responses_triggered": 0,
            "responses_blocked": 0,
            "block_reasons": defaultdict(int),
        }
        
    async def should_respond_proactively(
        self,
        window: ConversationWindow,
        bot_capabilities: list[str]
    ) -> ProactiveResponse:
        """
        Decide if bot should send proactive response.
        
        This is the main decision function with multiple safety checks.
        """
        self.stats["windows_analyzed"] += 1
        
        # Safety check 1: Feature enabled?
        if not self.settings.ENABLE_PROACTIVE_RESPONSES:
            return ProactiveResponse(
                should_respond=False,
                confidence=0.0,
                intent=None,
                reason="Proactive responses disabled"
            )
            
        # Safety check 2: Minimum window size
        if len(window.messages) < self.settings.PROACTIVE_MIN_WINDOW_SIZE:
            return ProactiveResponse(
                should_respond=False,
                confidence=0.0,
                intent=None,
                reason=f"Window too small ({len(window.messages)} < {self.settings.PROACTIVE_MIN_WINDOW_SIZE})"
            )
            
        # Safety check 3: Recent activity required?
        if self.settings.PROACTIVE_REQUIRE_RECENT_ACTIVITY:
            last_message_time = window.messages[-1].timestamp
            age_seconds = (datetime.now() - last_message_time).total_seconds()
            
            if age_seconds > self.settings.PROACTIVE_RECENT_ACTIVITY_SECONDS:
                return ProactiveResponse(
                    should_respond=False,
                    confidence=0.0,
                    intent=None,
                    reason=f"Window too old ({int(age_seconds)}s > {self.settings.PROACTIVE_RECENT_ACTIVITY_SECONDS}s)"
                )
                
        # Safety check 4: Rate limits
        rate_limit_ok, rate_limit_reason = await self._check_rate_limits(window.chat_id)
        if not rate_limit_ok:
            self.stats["responses_blocked"] += 1
            self.stats["block_reasons"]["rate_limit"] += 1
            return ProactiveResponse(
                should_respond=False,
                confidence=0.0,
                intent=None,
                reason=f"Rate limit: {rate_limit_reason}"
            )
            
        # Step 1: Detect intent
        intent = await self.intent_classifier.classify_window(window, bot_capabilities)
        
        if not intent:
            return ProactiveResponse(
                should_respond=False,
                confidence=0.0,
                intent=None,
                reason="No intent detected"
            )
            
        self.stats["intents_detected"] += 1
        
        # Step 2: Check cooldowns
        cooldown_ok, cooldown_reason = await self.preference_manager.check_cooldown(
            chat_id=window.chat_id,
            intent_type=intent.intent_type
        )
        
        if not cooldown_ok:
            self.stats["responses_blocked"] += 1
            self.stats["block_reasons"]["cooldown"] += 1
            return ProactiveResponse(
                should_respond=False,
                confidence=intent.confidence,
                intent=intent,
                reason=cooldown_reason
            )
            
        # Step 3: Apply user preferences
        # Get primary participant (most active in window)
        primary_user_id = self._get_primary_participant(window)
        if primary_user_id:
            preference = await self.preference_manager.get_preference(primary_user_id)
            
            # Adjust confidence by user multiplier
            adjusted_confidence = intent.confidence * preference.proactivity_multiplier
            
            # Check for negative feedback recently
            if preference.consecutive_ignores >= self.settings.PROACTIVE_IGNORED_THRESHOLD:
                self.stats["responses_blocked"] += 1
                self.stats["block_reasons"]["user_preference"] += 1
                return ProactiveResponse(
                    should_respond=False,
                    confidence=adjusted_confidence,
                    intent=intent,
                    reason=f"User ignoring proactive responses ({preference.consecutive_ignores} consecutive)"
                )
                
            # Check if adjusted confidence still meets threshold
            if adjusted_confidence < self.settings.PROACTIVE_MIN_CONFIDENCE:
                self.stats["responses_blocked"] += 1
                self.stats["block_reasons"]["low_confidence"] += 1
                return ProactiveResponse(
                    should_respond=False,
                    confidence=adjusted_confidence,
                    intent=intent,
                    reason=f"Confidence too low after user adjustment ({adjusted_confidence:.2f} < {self.settings.PROACTIVE_MIN_CONFIDENCE})"
                )
        else:
            adjusted_confidence = intent.confidence
            
        # All checks passed!
        self.stats["responses_triggered"] += 1
        
        return ProactiveResponse(
            should_respond=True,
            confidence=adjusted_confidence,
            intent=intent,
            reason="All checks passed",
            suggested_response=intent.suggested_response
        )
        
    async def _check_rate_limits(self, chat_id: int) -> tuple[bool, Optional[str]]:
        """Check hourly and daily rate limits."""
        conn = await self.store._get_connection()
        
        # Check hourly limit
        one_hour_ago = datetime.now() - timedelta(hours=1)
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM proactive_responses
            WHERE chat_id = ? AND sent_at > ?
        """, (chat_id, one_hour_ago.isoformat()))
        
        hourly_count = (await cursor.fetchone())[0]
        if hourly_count >= self.settings.PROACTIVE_MAX_PER_HOUR:
            return False, f"Hourly limit reached ({hourly_count}/{self.settings.PROACTIVE_MAX_PER_HOUR})"
            
        # Check daily limit
        one_day_ago = datetime.now() - timedelta(days=1)
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM proactive_responses
            WHERE chat_id = ? AND sent_at > ?
        """, (chat_id, one_day_ago.isoformat()))
        
        daily_count = (await cursor.fetchone())[0]
        if daily_count >= self.settings.PROACTIVE_MAX_PER_DAY:
            return False, f"Daily limit reached ({daily_count}/{self.settings.PROACTIVE_MAX_PER_DAY})"
            
        return True, None
        
    def _get_primary_participant(self, window: ConversationWindow) -> Optional[int]:
        """Get most active participant in window (for preference lookup)."""
        if not window.messages:
            return None
            
        # Count messages per user
        message_counts = defaultdict(int)
        for msg in window.messages:
            message_counts[msg.user_id] += 1
            
        # Return user with most messages
        return max(message_counts.items(), key=lambda x: x[1])[0]
        
    async def record_proactive_response(
        self,
        chat_id: int,
        window_id: int,
        intent: ConversationIntent,
        response_text: str,
        user_id: Optional[int] = None
    ) -> int:
        """
        Record that proactive response was sent.
        
        Returns:
            response_id for later reaction tracking
        """
        conn = await self.store._get_connection()
        cursor = await conn.execute("""
            INSERT INTO proactive_responses (
                chat_id, user_id, window_id, intent_type, confidence,
                response_text, context_summary, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chat_id,
            user_id,
            window_id,
            intent.intent_type.value,
            intent.confidence,
            response_text,
            intent.context_summary,
            datetime.now().isoformat()
        ))
        
        await conn.commit()
        return cursor.lastrowid
```

**Testing Strategy**:
1. Test all safety checks block correctly
2. Test rate limits (hourly, daily)
3. Test user preference adjustment reduces confidence
4. Test consecutive ignores block responses
5. Verify primary participant detection

### Task 4: Integration with ContinuousMonitor

**File**: `app/services/monitoring/continuous_monitor.py`

**Changes**:

```python
# In _process_window() method, after fact extraction:

async def _process_window(self, window: ConversationWindow):
    """Process closed conversation window."""
    try:
        logger.info(
            f"Processing window",
            extra={
                "window_id": window.id,
                "chat_id": window.chat_id,
                "message_count": len(window.messages),
                "participant_count": window.participant_count,
                "closure_reason": window.closure_reason,
            }
        )
        
        # ... existing fact extraction code ...
        
        # NEW: Check for proactive response opportunity
        if self.settings.ENABLE_PROACTIVE_RESPONSES:
            try:
                # Define bot capabilities for intent classification
                bot_capabilities = [
                    "weather forecasts",
                    "currency conversion",
                    "calculations",
                    "web search",
                    "answering questions using conversation history"
                ]
                
                # Decide if we should respond
                decision = await self.proactive_trigger.should_respond_proactively(
                    window=window,
                    bot_capabilities=bot_capabilities
                )
                
                logger.info(
                    f"Proactive response decision",
                    extra={
                        "window_id": window.id,
                        "should_respond": decision.should_respond,
                        "confidence": decision.confidence,
                        "reason": decision.reason,
                        "intent_type": decision.intent.intent_type.value if decision.intent else None,
                    }
                )
                
                if decision.should_respond:
                    # Generate and send proactive response
                    await self._send_proactive_response(window, decision)
                    
            except Exception as e:
                logger.error(
                    f"Proactive response check failed: {e}",
                    extra={"window_id": window.id},
                    exc_info=True
                )
                
    except Exception as e:
        logger.error(
            f"Window processing failed: {e}",
            extra={"window_id": window.id},
            exc_info=True
        )

async def _send_proactive_response(
    self,
    window: ConversationWindow,
    decision: ProactiveResponse
):
    """Generate and send proactive response."""
    try:
        # Build context from window
        conversation_history = []
        for msg in window.messages[-10:]:  # Last 10 messages
            conversation_history.append({
                "role": "user",
                "content": f"{msg.username}: {msg.text}"
            })
            
        # Generate response using Gemini
        # Use suggested_response as starting point if available
        if decision.suggested_response:
            response_text = decision.suggested_response
        else:
            response_text = await self.gemini.generate(
                message=f"Context: {decision.intent.context_summary}",
                context=conversation_history,
                system_prompt="Respond naturally and helpfully to the conversation. Be brief and relevant."
            )
            
        # Send to chat via bot
        # NOTE: This requires access to bot instance - needs to be passed in __init__
        if hasattr(self, 'bot') and self.bot:
            await self.bot.send_message(
                chat_id=window.chat_id,
                text=response_text
            )
            
            # Record the response
            primary_user = self.proactive_trigger._get_primary_participant(window)
            response_id = await self.proactive_trigger.record_proactive_response(
                chat_id=window.chat_id,
                window_id=window.id,
                intent=decision.intent,
                response_text=response_text,
                user_id=primary_user
            )
            
            logger.info(
                f"Proactive response sent",
                extra={
                    "window_id": window.id,
                    "response_id": response_id,
                    "intent_type": decision.intent.intent_type.value,
                    "confidence": decision.confidence,
                }
            )
            
            # TODO: Track user reactions in next message
            # Need to add reaction detection logic
            
    except Exception as e:
        logger.error(
            f"Failed to send proactive response: {e}",
            extra={"window_id": window.id},
            exc_info=True
        )
```

## Testing Strategy

### Test 1: Intent Detection Accuracy

**Goal**: Verify intent classifier correctly identifies opportunities

**Scenarios**:
1. **Should trigger** - Unanswered question:
   ```
   User A: "What's the weather tomorrow?"
   User B: "Not sure"
   [Bot should detect QUESTION intent]
   ```

2. **Should trigger** - Request for information:
   ```
   User A: "Can someone convert 100 USD to EUR?"
   [Bot should detect REQUEST intent]
   ```

3. **Should NOT trigger** - Complete conversation:
   ```
   User A: "What's the weather?"
   User B: "It's 20°C and sunny"
   User A: "Thanks!"
   [Bot should NOT respond - already answered]
   ```

4. **Should NOT trigger** - Chitchat:
   ```
   User A: "Hey how are you?"
   User B: "Good thanks, you?"
   [Bot should NOT respond - social chat]
   ```

**Validation**:
- Check logs for intent classification results
- Verify confidence scores match expectations
- Ensure false positives <10%

### Test 2: Cooldown Enforcement

**Goal**: Verify cooldowns prevent spam

**Scenarios**:
1. Send proactive response, immediately trigger another intent
   - Expected: Blocked by global cooldown (5 min)
   
2. Send proactive to User A, trigger intent for User A again
   - Expected: Blocked by per-user cooldown (10 min)
   
3. Send "question" intent response, trigger another "question" intent
   - Expected: Blocked by same-intent cooldown (30 min)

**Validation**:
```sql
-- Check cooldown enforcement
SELECT 
    chat_id,
    intent_type,
    sent_at,
    LAG(sent_at) OVER (PARTITION BY chat_id ORDER BY sent_at) as prev_sent_at,
    (julianday(sent_at) - julianday(LAG(sent_at) OVER (PARTITION BY chat_id ORDER BY sent_at))) * 86400 as gap_seconds
FROM proactive_responses
ORDER BY sent_at DESC
LIMIT 20;

-- All gaps should be >= 300 seconds (5 minutes)
```

### Test 3: User Preference Learning

**Goal**: Verify bot adapts to user reactions

**Scenario**:
1. Send 3 proactive responses to User A
2. User A ignores all 3 (no reply within 5 minutes)
3. Trigger another intent for User A
4. Expected: Proactivity reduced (confidence lowered)

**Validation**:
```python
# Check user preference
preference = await preference_manager.get_preference(user_a_id)
assert preference.consecutive_ignores == 3
assert preference.proactivity_multiplier < 1.0
```

### Test 4: Rate Limits

**Goal**: Verify hourly/daily limits prevent excessive responses

**Scenario**:
1. Trigger 6 proactive responses in 1 hour (hourly limit)
2. Attempt 7th response
3. Expected: Blocked by rate limit

**Validation**:
```python
# Check stats
stats = proactive_trigger.stats
assert stats["responses_blocked"] > 0
assert stats["block_reasons"]["rate_limit"] > 0
```

### Test 5: Safety Checks

**Goal**: Verify all safety mechanisms work

**Test each safety check**:
1. Feature disabled → No responses
2. Window too small (< 3 messages) → Blocked
3. Window too old (> 3 minutes) → Blocked
4. User with negative feedback → Blocked
5. Low confidence after user adjustment → Blocked

## Rollout Plan

### Phase 4.1: Implementation (Week 5)
- ✅ Implement IntentClassifier
- ✅ Implement UserPreferenceManager
- ✅ Implement ResponseTrigger logic
- ✅ Add database migration for proactive_responses table
- ✅ Integrate with ContinuousMonitor

### Phase 4.2: Testing (Week 5)
- Run all 5 test scenarios
- Validate intent detection accuracy (>90%)
- Verify safety checks (0% false bypasses)
- Tune confidence thresholds

### Phase 4.3: Soft Launch (Week 6)
- Enable in single test chat (`ENABLE_PROACTIVE_RESPONSES=true`)
- Monitor for 48 hours
- Track response rate (target: 1-2 per hour max)
- Collect user feedback

### Phase 4.4: Tuning (Week 6)
- Adjust confidence thresholds based on false positive rate
- Tune cooldowns based on user feedback
- Refine intent classification prompts

### Phase 4.5: Production (Week 6)
- Enable globally after validation
- Monitor stats dashboard
- Collect user reactions
- Plan Phase 5 optimizations

## Success Metrics

### Accuracy
- **Intent detection**: >90% precision (responses are relevant)
- **False positives**: <10% (bot shouldn't have responded)
- **User satisfaction**: >70% positive/neutral reactions

### Safety
- **Spam prevention**: 0 instances of >3 consecutive proactive messages
- **Cooldown compliance**: 100% (no cooldown violations)
- **Rate limit compliance**: 100% (no limit violations)

### Engagement
- **Response rate**: 1-3 proactive responses per hour in active chats
- **User reactions**: <20% ignored, <5% negative
- **Conversation continuity**: >50% of proactive responses lead to continued conversation

## Risk Mitigation

### High Risk: Bot becomes annoying
**Mitigation**:
- Very conservative thresholds (70% confidence minimum)
- Multiple cooldowns (global, per-user, per-intent)
- User preference learning (backs off after ignores)
- Easy disable switch (`ENABLE_PROACTIVE_RESPONSES=false`)

### Medium Risk: Intent classification inaccurate
**Mitigation**:
- Extensive testing with diverse scenarios
- Tunable confidence threshold
- Fallback to silence if uncertain
- Logging all decisions for analysis

### Medium Risk: Performance impact
**Mitigation**:
- Intent classification only on window close (not every message)
- Async processing via event queue (non-blocking)
- Cached results (don't re-classify same window)
- Rate limits prevent runaway processing

### Low Risk: Database growth
**Mitigation**:
- proactive_responses table indexed properly
- Regular cleanup of old reactions (>30 days)
- Bounded by rate limits (max 40/day = 1200/month)

## Next Steps After Phase 4

### Phase 5: Optimization (Week 7-8)
1. **Caching**: Cache intent classifications, user preferences
2. **Batch Processing**: Process multiple windows in parallel
3. **Resource Monitoring**: Track CPU/memory usage, optimize bottlenecks
4. **Database Tuning**: Add indexes, optimize queries

### Phase 6: Advanced Features (Week 9+)
1. **Conversation threading**: Better understand multi-user dynamics
2. **Emotion detection**: Adjust tone based on conversation mood
3. **Topic tracking**: Learn which topics users want bot input on
4. **Personalization**: Per-user response style preferences

---

**Phase 4 Status**: Ready for implementation  
**Estimated effort**: 12-15 hours  
**Risk**: Medium-High (user-facing behavior change)  
**Value**: High (transforms bot from reactive to proactive)
