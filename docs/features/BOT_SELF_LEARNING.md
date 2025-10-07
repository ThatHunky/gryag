# Bot Self-Learning System - Phase 5

**Status**: ✅ Implemented (October 6, 2025)

## Overview

The bot now learns about **itself** over time, tracking effectiveness patterns, communication styles that work, knowledge gaps, and adapting its persona dynamically based on accumulated experience. This is parallel to the user profiling system but focused on self-improvement.

## Key Features

### 1. **Self-Awareness Tracking**
- Bot maintains its own profile (global + per-chat)
- Tracks interaction outcomes: positive, negative, corrected, ignored, praised
- Records performance metrics: response time, token usage, sentiment scores
- Monitors tool effectiveness and success rates

### 2. **Learned Fact Categories**
The bot learns facts about itself across multiple dimensions:

#### `communication_style`
- Which tone/approach works best in different contexts
- Response length preferences (short, medium, long)
- Response types that get positive feedback (brief, detailed, clarification, tool_usage)

#### `knowledge_domain`
- Topics where bot performs well
- Areas where bot struggles (knowledge gaps)
- Subjects that frequently require corrections

#### `tool_effectiveness`
- Which tools (search, weather, calculator, currency, polls) work well when
- Tool usage patterns that correlate with positive outcomes
- Tool failures and their contexts

#### `user_interaction`
- Patterns in user responses and engagement
- High-value conversation characteristics
- Emotional valence patterns (positive/negative/mixed conversations)

#### `persona_adjustment`
- Context-based personality tweaks
- Chat-specific communication preferences
- Time-of-day behavioral adaptations

#### `mistake_pattern`
- Common errors to avoid
- Frequently corrected responses
- Patterns that lead to negative feedback

#### `temporal_pattern`
- Time-based behavior (morning vs evening vs night)
- Weekend vs weekday patterns
- Quick vs delayed user engagement indicators

#### `performance_metric`
- Response time patterns that correlate with outcomes
- Token usage efficiency
- Cache hit rates

### 3. **Enhanced Features**

#### **Semantic Deduplication**
- Uses embeddings (like user facts) to detect similar learned patterns
- Avoids storing duplicate facts with different wording
- Reinforces existing facts when patterns repeat (increases confidence + evidence count)

#### **Temporal Decay**
- Facts can have `decay_rate` (0.0 = no decay, higher = faster decay)
- Outdated mistakes fade over time (bot improves)
- Effective confidence calculated as: `confidence * exp(-decay_rate * age_days)`

#### **Episode-Aware Learning**
- Integrates with episodic memory
- Learns from full conversation arcs, not just individual messages
- Tracks high-importance episodes (importance >= 0.8)

#### **Gemini-Powered Self-Reflection**
- Periodic insights generated via Gemini (weekly by default)
- Analyzes accumulated data to produce actionable recommendations
- Insight types: effectiveness_trend, communication_pattern, knowledge_gap, temporal_insight, improvement_suggestion

#### **Self-Query Tools** (for Gemini)
Two new tools the bot can use during generation:

1. **`query_bot_self`**
   - Bot queries its own learned facts mid-conversation
   - Can filter by category, context tags, confidence threshold
   - Returns top facts + recent insights
   - Example: "Before responding about weather, let me check my tool effectiveness for weather queries..."

2. **`get_bot_effectiveness`**
   - Bot checks its own performance metrics
   - Returns effectiveness scores, outcome distribution, performance stats
   - Example: "My recent effectiveness is 78%, so I should be more careful..."

### 4. **Automatic Learning Sources**

#### **User Sentiment Analysis** (pattern-based)
Detects user reactions via regex patterns:
- **Positive**: thanks, helpful, good, exactly, 👍, ❤️, etc.
- **Negative**: wrong, confus*, bad, 👎, 😡, etc.
- **Corrections**: actually, no, you're wrong, that's not, etc.
- **Praise**: brilliant, genius, love it, 🔥, ⭐, etc.

#### **Performance Metrics**
Automatically tracked:
- Response time (ms) - learns if <1s correlates with positive feedback
- Token count - tracks efficiency
- Tool usage - which tools succeed/fail
- Reaction delay - how quickly users respond

#### **Episode Learning**
When episodes are created:
- High-importance episodes (>0.8) teach conversation success patterns
- Emotional valence tracked (positive/negative/mixed)
- Learns what types of conversations the bot navigates well

### 5. **Dynamic Persona Adaptation** (Future)
Planned feature (not yet active):
- `bot_persona_rules` table stores dynamic modifications
- Rules triggered by context (time, chat type, user preferences)
- Appends learned patterns to system prompt
- Example: "In this chat, users prefer concise responses in the evening"

## Database Schema

### `bot_profiles`
- One global profile + per-chat profiles
- Tracks: `effectiveness_score`, `total_interactions`, `positive/negative_interactions`
- `last_self_reflection`: timestamp of last Gemini insight generation

### `bot_facts`
- Stores learned facts (parallel to `user_facts`)
- Includes: `fact_embedding` (768-dim for semantic dedup), `decay_rate`, `context_tags`
- Confidence reinforced via `evidence_count` (multiple observations)

### `bot_interaction_outcomes`
- Records every interaction with detailed metadata
- Links to episodes (`episode_id`) for conversation-level learning
- Stores: `sentiment_score`, `response_time_ms`, `token_count`, `tools_used`, `user_reaction`

### `bot_insights`
- Gemini-generated self-reflection insights
- Types: effectiveness_trend, communication_pattern, knowledge_gap, temporal_insight, improvement_suggestion
- `actionable` flag indicates if insight should trigger changes

### `bot_persona_rules` (future use)
- Dynamic persona modification rules
- Condition-based activation (JSON: `{"time_of_day": "evening", "chat_type": "technical"}`)
- Success rate tracked

### `bot_performance_metrics`
- Time-series performance data
- Metric types: response_time, token_usage, tool_success_rate, error_rate, user_satisfaction, embedding_cache_hit

## Configuration (.env)

```bash
# Bot Self-Learning
ENABLE_BOT_SELF_LEARNING=true              # Master switch
BOT_LEARNING_CONFIDENCE_THRESHOLD=0.5      # Min confidence for fact retrieval
BOT_LEARNING_MIN_EVIDENCE=3                # Min observations before high confidence
ENABLE_BOT_PERSONA_ADAPTATION=true         # Dynamic persona (future)
ENABLE_TEMPORAL_DECAY=true                 # Outdated facts lose confidence
ENABLE_SEMANTIC_DEDUP=true                 # Use embeddings for dedup
ENABLE_GEMINI_INSIGHTS=true                # Self-reflection via Gemini
BOT_INSIGHT_INTERVAL_HOURS=168             # How often to generate insights (weekly)
BOT_REACTION_TIMEOUT_SECONDS=300           # Wait time for user reaction (5 min)
```

## Admin Commands

### `/gryagself`
View bot's self-learning profile for current chat.

**Output**:
- Effectiveness score (7-day rolling)
- Total/positive/negative interactions
- Performance metrics (avg response time, tokens, sentiment)
- Top 3 facts per category (communication_style, knowledge_domain, tool_effectiveness, etc.)

**Example**:
```
🤖 Bot Self-Learning Profile

📊 Effectiveness (last 7 days)
• Overall score: 78.5%
• Recent score: 82.3%
• Total interactions: 142
• Positive: 98 (69.0%)
• Negative: 12 (8.5%)

⚡ Performance
• Avg response time: 1247ms
• Avg tokens: 342
• Avg sentiment: 0.54

💬 Communication Style
• effective_conversational_response: Response type 'conversational' received positive feedback
  └ confidence: 0.82, evidence: 15
• preferred_length: medium
  └ confidence: 0.71, evidence: 12
```

### `/gryaginsights`
Generate Gemini-powered self-reflection insights.

**Output**:
- 3-5 actionable insights from accumulated data
- Each insight includes: type, text, confidence, actionable flag
- Takes 10-30 seconds to generate

**Example**:
```
🧠 Bot Self-Reflection Insights

📈 Insight 1
Users respond more positively to responses under 200 characters during evening hours (18:00-22:00). Consider adapting brevity based on time of day.
• Confidence: 0.85
• Actionable: ✅ Yes

💬 Insight 2
Tool usage for weather queries has 92% success rate, but currency conversions show 68%. Investigate currency API reliability.
• Confidence: 0.78
• Actionable: ✅ Yes
```

## Learning Flow

### 1. **Message Generation**
```python
# In handle_group_message()
start_time = time.time()
response = await gemini_client.generate(...)
response_time_ms = int((time.time() - start_time) * 1000)

# Record outcome (happens in background)
asyncio.create_task(_track_bot_response_outcome(...))
```

### 2. **Reaction Analysis** (background task)
```python
async def _track_bot_response_outcome(...):
    # Wait for user reaction (5 min timeout)
    await asyncio.sleep(settings.bot_reaction_timeout_seconds)
    
    # Check for reply/reaction from user
    # (simplified - full implementation would poll for replies)
    
    # Analyze sentiment
    sentiment, confidence = bot_learning.detect_user_sentiment(user_reply)
    sentiment_score = bot_learning.calculate_sentiment_score(sentiment)
    
    # Record outcome
    await bot_profile.record_interaction_outcome(
        outcome=sentiment,
        sentiment_score=sentiment_score,
        response_time_ms=response_time_ms,
        token_count=token_count,
        tools_used=tools_used,
        ...
    )
    
    # Extract learning
    await bot_learning.learn_from_user_reaction(
        user_message=user_reply,
        bot_previous_response=bot_response,
        chat_id=chat_id,
        context_tags=bot_learning.get_context_tags(hour_of_day, is_weekend),
    )
```

### 3. **Fact Reinforcement**
```python
# When same pattern observed multiple times
# Example: User says "thanks" after brief response
await bot_profile.add_fact(
    category="communication_style",
    key="effective_brief_response",
    value="Brief responses receive positive feedback",
    confidence=0.7,
    source_type="reaction_analysis",
    chat_id=chat_id,
    context_tags=["evening", "weekday"],
)

# If similar fact exists (via embedding similarity):
# - evidence_count += 1
# - confidence = weighted_average(old_confidence, new_confidence)
# - last_reinforced = now
```

### 4. **Periodic Insights** (weekly background task)
```python
# Runs once per week (configurable)
insights = await bot_learning.generate_gemini_insights(
    chat_id=chat_id,
    days=7,
)

# Stores insights in bot_insights table
# Admins can view via /gryaginsights
```

## Integration Points

### With User Profiling
- Bot learns about itself **while** learning about users
- User reactions trigger bot self-learning
- Both use same embedding infrastructure for semantic dedup

### With Episodic Memory
- Episodes track conversation-level outcomes
- `bot_interaction_outcomes.episode_id` links to `episodes.id`
- High-importance episodes teach macro-patterns

### With Continuous Monitor
- Message classification feeds into outcome tracking
- Proactive responses (future) could use bot_facts to decide when to interject

### With Gemini Tools
- `query_bot_self` and `get_bot_effectiveness` available during generation
- Bot can self-reflect mid-conversation
- Example: "Let me check my past performance with similar queries..."

## Performance Considerations

### Embedding Rate Limiting
- `_embed_semaphore = asyncio.Semaphore(4)` limits concurrent embeddings
- Fact deduplication requires embeddings, but it's async and non-blocking
- Uses same Gemini embed client as user facts

### Storage Impact
- Each fact: ~1-2KB (including embedding JSON)
- Per chat: expect ~50-200 facts after 1 month
- Global profile: ~500-1000 facts after 6 months
- Performance metrics: ~100-500 rows/day (pruned after 30 days)

### Query Efficiency
- Indexed by: `profile_id`, `fact_category`, `confidence`, `is_active`
- Temporal decay calculated on-the-fly (no background jobs)
- Effectiveness summary uses aggregation (fast with indexes)

## Future Enhancements

### 1. **Active Persona Adaptation**
Currently, facts are stored but not yet dynamically applied to system prompt. Future:
```python
# In handle_group_message()
persona = await get_adaptive_persona(
    bot_profile=bot_profile,
    chat_id=chat_id,
    context_tags=["evening", "technical"],
)
# Appends learned communication preferences to base SYSTEM_PERSONA
```

### 2. **Proactive Improvement**
Bot could:
- Detect knowledge gaps and suggest admin should add tools/data
- Auto-adjust response length based on chat preferences
- Learn optimal times to use Search Grounding

### 3. **Cross-Chat Learning**
Currently, learning is per-chat. Could add:
- Global patterns that apply across all chats
- Transfer learning from high-performing chats to new ones

### 4. **A/B Testing**
Bot could:
- Try different approaches and measure outcomes
- Store variants in `bot_persona_rules` with success_rate
- Gradually favor high-performing strategies

## How to Verify

### Check Database Tables Created
```bash
sqlite3 gryag.db ".tables" | grep bot_
# Should show: bot_profiles, bot_facts, bot_interaction_outcomes, 
#              bot_insights, bot_persona_rules, bot_performance_metrics
```

### Check Bot Learns from Interaction
```bash
# In Telegram, talk to bot, then say "thanks" or give feedback
# Check facts were learned:
sqlite3 gryag.db "
SELECT fact_category, fact_key, fact_value, confidence, evidence_count 
FROM bot_facts 
ORDER BY updated_at DESC 
LIMIT 10;
"
```

### Check Effectiveness Tracking
```bash
sqlite3 gryag.db "
SELECT outcome, COUNT(*) as count 
FROM bot_interaction_outcomes 
GROUP BY outcome;
"
# Should show: positive, negative, neutral, etc.
```

### Admin Commands
```bash
# In Telegram (as admin):
/gryagself          # View bot's learned profile
/gryaginsights      # Generate self-reflection insights
```

### Check Gemini Tools Available
```python
# In app/handlers/chat.py, tool_definitions should include:
from app.services.tools.bot_self_tools import (
    QUERY_BOT_SELF_TOOL_DEFINITION,
    GET_BOT_EFFECTIVENESS_TOOL_DEFINITION,
)
# Bot can now query_bot_self() during generation
```

## Troubleshooting

### Bot not learning anything
1. Check `ENABLE_BOT_SELF_LEARNING=true` in `.env`
2. Verify bot_profile initialized in logs: `Bot self-learning initialized`
3. Check middleware injection: `bot_profile` should be in handler data
4. Ensure user reactions are being detected (check sentiment patterns in `bot_learning.py`)

### Insights failing
1. Check `ENABLE_GEMINI_INSIGHTS=true`
2. Verify Gemini API key valid and quota available
3. Check logs for `generate_gemini_insights` errors
4. Ensure sufficient interaction data (needs ~20+ outcomes for meaningful insights)

### Performance degradation
1. Check `bot_performance_metrics` table size (prune old data)
2. Verify embedding semaphore not bottlenecking (increase if needed)
3. Disable temporal decay if CPU-bound: `ENABLE_TEMPORAL_DECAY=false`
4. Disable semantic dedup if memory-bound: `ENABLE_SEMANTIC_DEDUP=false`

## Code Locations

- **Schema**: `db/schema.sql` (lines after "Phase 5" comment)
- **BotProfileStore**: `app/services/bot_profile.py`
- **BotLearningEngine**: `app/services/bot_learning.py`
- **Gemini Tools**: `app/services/tools/bot_self_tools.py`
- **Admin Commands**: `app/handlers/profile_admin.py` (cmd_bot_self_profile, cmd_generate_insights)
- **Middleware**: `app/middlewares/chat_meta.py` (injection)
- **Main Init**: `app/main.py` (Phase 5 section)
- **Config**: `app/config.py` (Bot Self-Learning section)

---

**Implementation Date**: October 6, 2025  
**Phase**: 5 (Memory and Context Improvements)  
**Status**: Core functionality complete, persona adaptation pending
