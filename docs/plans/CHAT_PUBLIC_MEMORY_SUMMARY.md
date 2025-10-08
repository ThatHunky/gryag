# Chat Public Memory - Executive Summary

**Created**: October 8, 2025  
**Status**: Planning Complete - Ready for Implementation  
**Estimated Effort**: 4 weeks  
**Impact**: Medium-High (improves group awareness without bloating context)

---

## What is Chat Public Memory?

A **shared memory system** that allows the bot to remember **group-level facts** about the chat, separate from individual user facts.

### Examples

| Current (User Facts Only) | With Chat Public Memory |
|---------------------------|-------------------------|
| Bot knows: "Alice is vegetarian" | Bot knows: "This chat prefers Ukrainian language" |
| Bot knows: "Bob likes AI" | Bot knows: "We have Friday recap tradition" |
| Bot knows: "Carol is from Kyiv" | Bot knows: "Group rule: no politics" |

---

## The Problem

**Currently, the bot only remembers individual users, missing critical group context:**

```
❌ User: "Should we do this like last time?"
   Bot: "Що за 'last time'?" (doesn't remember group decisions)

❌ Chat has running joke about pineapple pizza
   Bot: Generic responses (seems out of touch with group culture)

❌ Group always discusses AI on Fridays
   Bot: No awareness of group patterns
```

---

## The Solution

### Architecture

Extends existing **multi-level context system** with a new layer:

```
BACKGROUND CONTEXT
├─ User Profile (60% of budget)
│  ├─ User facts: "Alice is vegetarian"
│  └─ User preferences: "prefers dark humor"
│
└─ Chat Profile (40% of budget) ← NEW!
   ├─ Chat facts: "Group prefers Ukrainian"
   ├─ Traditions: "Friday recap"
   ├─ Rules: "No politics"
   └─ Culture: "Sarcastic, supportive"
```

### What Gets Stored

**8 fact categories** for comprehensive group understanding:

1. **preference** - "likes dark humor", "prefers text over voice"
2. **tradition** - "Friday recaps", "Monday motivation"
3. **rule** - "no politics", "Ukrainian only"
4. **norm** - "lots of emoji", "formal communication"
5. **topic** - "AI discussions", "crypto focus"
6. **culture** - "sarcastic", "supportive", "competitive"
7. **event** - "planning trip", "birthday next week"
8. **shared_knowledge** - "discussed movie X", "researched topic Y"

---

## How It Works

### 1. Extraction (3 methods)

**Pattern-based (fast, 70% coverage)**:
- Regex for "we like", "we prefer", "every Friday"
- Instant, no API calls

**Statistical (behavior analysis)**:
- High emoji usage → norm fact
- Long messages → communication style fact
- Formal language → culture fact

**LLM-based (complex cases)**:
- Gemini analyzes conversation window
- Extracts nuanced group dynamics
- Only when patterns fail

### 2. Storage

**New database tables**:
```sql
chat_profiles (one per chat)
  ├─ chat_id, chat_title, participant_count
  └─ culture_summary (AI-generated)

chat_facts (group-level facts)
  ├─ category, fact_key, fact_value
  ├─ confidence, evidence_count
  ├─ participant_consensus (what % agree)
  └─ temporal tracking (first_observed, last_reinforced)

chat_fact_versions (track changes)
  └─ Like user facts: creation, reinforcement, evolution
```

### 3. Retrieval

**Top 8 most relevant chat facts** included in context:

**Ranking algorithm**:
```
score = base_confidence 
        × category_weight (rules > preferences > norms)
        × temporal_factor (recent facts weighted higher)
        × evidence_boost (more reinforcement = better)
```

**Example context addition**:
```
Chat Profile:
- Rules: No politics, Ukrainian preferred but English OK
- Preferences: Dark humor, technical discussions, lots of emoji
- Traditions: Friday recap of the week
- Culture: Supportive but sarcastic, active participation
```

---

## Context Budget Impact

**Strict limits to avoid bloat**:

```
Total Background Budget: 1200 tokens (15% of 8000 total)

User Profile:  720 tokens (60%)
Chat Profile:  480 tokens (40%) ← NEW
              ──────────────────
Total:        1200 tokens

Chat Profile breakdown:
  - Summary:     ~200 tokens
  - Top 8 facts: ~280 tokens (35 each)
  ──────────────────────────────
  Total:          480 tokens
```

**Maximum overhead**: 400 tokens (5% of total context)

---

## Quality Management

### Deduplication

```python
if new_fact.similarity(existing_fact) > 0.85:
    # Merge: boost confidence, update evidence count
    existing_fact.confidence = (old * 0.7) + (new * 0.3)
    existing_fact.evidence_count += 1
```

### Versioning

```python
if fact_value_changed:
    # Create new version, deprecate old
    create_fact_version(
        previous=old_fact,
        change_type='evolution',
        evidence='3 users mentioned change'
    )
```

### Temporal Decay

```python
# Facts decay over time (half-life = 30 days)
temporal_factor = exp(-age_days / 30)
score *= (0.5 + 0.5 * temporal_factor)
```

---

## Admin Controls

### New Commands

**`/gryadchatfacts`** - Show all chat facts
```
📊 Факти про чат:

Preferences:
  • Dark humor (▰▰▰▰▰ 100%, 5x)
  • Technical discussions (▰▰▰▰ 85%, 3x)

Rules:
  • No politics (▰▰▰▰▰ 95%, 8x)

Traditions:
  • Friday recap (▰▰▰▰ 80%, 12x)
```

**`/gryadchatreset`** - Delete all chat facts (admin only)

---

## Implementation Phases

### Phase 1: Schema & Repository (Week 1)
- Database tables
- ChatProfileRepository
- Migration scripts
- Tests

### Phase 2: Extraction (Week 2)
- ChatFactExtractor class
- Pattern/statistical/LLM methods
- Deduplication
- Tests

### Phase 3: Integration (Week 3)
- ContinuousMonitor integration
- MultiLevelContextManager updates
- Context formatting
- End-to-end tests

### Phase 4: Quality & Polish (Week 4)
- Quality management
- Admin commands
- Performance optimization
- Documentation

---

## Benefits

### For Users

✅ **Better group awareness**: Bot understands chat culture and norms  
✅ **Reduced repetition**: Remembers group decisions and preferences  
✅ **Improved relevance**: Responses aligned with group expectations  
✅ **Personalized experience**: Each chat develops unique bot personality

### For System

✅ **Minimal overhead**: 400 tokens max (5% of context budget)  
✅ **Quality managed**: Deduplication, versioning, decay  
✅ **Reuses infrastructure**: Parallel to existing user fact system  
✅ **Optional feature**: Can be disabled via config

---

## Configuration

**New settings in `.env`**:

```bash
# Chat Public Memory
ENABLE_CHAT_MEMORY=true
CHAT_FACT_MIN_CONFIDENCE=0.6
CHAT_FACT_EXTRACTION_METHOD=hybrid  # pattern, statistical, llm, hybrid
MAX_CHAT_FACTS_IN_CONTEXT=8
CHAT_CONTEXT_TOKEN_BUDGET=480
```

---

## Example Scenarios

### Scenario 1: Language Preference

**Conversation**:
```
User1: "Хлопці, давайте більше українською спілкуватися"
User2: "Підтримую!"
User3: "+1, українська краща"
```

**Extracted Fact**:
```json
{
  "category": "preference",
  "fact_key": "language_preference",
  "fact_value": "ukrainian",
  "fact_description": "Group prefers Ukrainian language",
  "confidence": 0.85,
  "participant_consensus": 1.0
}
```

**Bot Response** (in future conversations):
*Responds in Ukrainian by default, even if addressed in English*

---

### Scenario 2: Weekly Tradition

**Conversation**:
```
User1: "Як завжди, в п'ятницю підіб'ємо підсумки"
User2: "Так, це вже традиція :)"
```

**Extracted Fact**:
```json
{
  "category": "tradition",
  "fact_key": "weekly_recap",
  "fact_value": "friday",
  "fact_description": "Friday recap tradition",
  "confidence": 0.9
}
```

**Bot Response** (on Fridays):
*Proactively: "Час для п'ятничного recap?"*

---

### Scenario 3: Chat Rule

**Conversation**:
```
Admin: "Нагадую: ніякої політики в чаті!"
User: "Зрозуміло"
```

**Extracted Fact**:
```json
{
  "category": "rule",
  "fact_key": "forbidden_topics",
  "fact_value": "politics",
  "fact_description": "No politics rule",
  "confidence": 0.95
}
```

**Bot Response** (if politics mentioned):
*"Згадайте: у нас правило - ніякої політики"*

---

## Success Metrics

### Extraction Quality
- [ ] Accuracy >75%
- [ ] Deduplication >80%
- [ ] False positives <10%

### Context Quality
- [ ] Facts appear when relevant
- [ ] Token budget maintained
- [ ] Retrieval <50ms

### User Experience
- [ ] Bot shows group awareness
- [ ] Fewer repetitive questions
- [ ] Better cultural fit

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Noisy extraction | Min confidence 0.6, deduplication, quality scoring |
| Context bloat | Strict 8 fact limit, 480 token budget |
| Privacy | Admins can reset, 90-day expiry default |
| Performance | Async processing, pattern-first extraction |

---

## Next Steps

1. **Review** this plan
2. **Approve** schema changes
3. **Begin Phase 1** (database + repository)
4. **Test** with small group first
5. **Rollout** gradually

---

## Full Documentation

See complete technical design: `docs/plans/CHAT_PUBLIC_MEMORY.md`

**Verification after implementation**:
```bash
# Check schema
sqlite3 gryag.db ".schema chat_facts"

# Test extraction
# (Have conversation with clear group preference)
/gryadchatfacts

# Verify context
# (Enable debug logging, check system prompt includes chat profile)
```

---

**Questions?** See full plan or ask for clarification on specific sections.
