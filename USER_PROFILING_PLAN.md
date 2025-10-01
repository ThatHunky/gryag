# User Profiling System Implementation Plan

## Overview
Massively improve gryag's context by implementing a persistent user profiling system that learns about users over time through natural conversation.

## Goal
Transform gryag from a message-history-based bot into one that builds and maintains persistent user profiles, remembering preferences, characteristics, relationships, and personal information across conversations.

---

## Database Schema

### Table: `user_profiles`
Core profile information - one row per user per chat.

```sql
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    display_name TEXT,
    username TEXT,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    last_active_thread INTEGER,
    interaction_count INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    summary TEXT,
    profile_version INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, chat_id)
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_user ON user_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_chat ON user_profiles(chat_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_last_seen ON user_profiles(last_seen);
```

**Fields:**
- `user_id`: Telegram user ID (e.g., 831570515)
- `chat_id`: Chat context where profile exists
- `display_name`: Current display name
- `username`: Current @username
- `first_seen`: Unix timestamp of first interaction
- `last_seen`: Unix timestamp of last interaction
- `last_active_thread`: Last thread_id they were active in
- `interaction_count`: Total message count
- `message_count`: Deduplicated message count
- `summary`: AI-generated summary (200-500 chars)
- `profile_version`: Increments on summarization
- `created_at`, `updated_at`: Timestamps

### Table: `user_facts`
Granular extracted facts about users.

```sql
CREATE TABLE IF NOT EXISTS user_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    fact_type TEXT NOT NULL CHECK(fact_type IN ('personal', 'preference', 'trait', 'relationship', 'skill', 'opinion')),
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source_message_id INTEGER,
    evidence_text TEXT,
    is_active INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_mentioned INTEGER,
    FOREIGN KEY (user_id, chat_id) REFERENCES user_profiles(user_id, chat_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_facts_user_chat ON user_facts(user_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_user_facts_type ON user_facts(fact_type);
CREATE INDEX IF NOT EXISTS idx_user_facts_key ON user_facts(fact_key);
CREATE INDEX IF NOT EXISTS idx_user_facts_active ON user_facts(is_active);
CREATE INDEX IF NOT EXISTS idx_user_facts_confidence ON user_facts(confidence);
```

**Fact Types:**
- `personal`: Location, job, age, hobbies, interests
- `preference`: Likes/dislikes, favorites
- `trait`: Personality characteristics, speech patterns
- `relationship`: Connections to other users
- `skill`: Abilities, languages, expertise
- `opinion`: Views on topics

**Example facts:**
```
fact_type='personal', fact_key='location', fact_value='Kyiv, Ukraine'
fact_type='preference', fact_key='food', fact_value='loves watermelon pizza'
fact_type='trait', fact_key='personality', fact_value='sarcastic, technical'
fact_type='skill', fact_key='language', fact_value='fluent Ukrainian and English'
```

### Table: `user_relationships`
Tracks connections between users.

```sql
CREATE TABLE IF NOT EXISTS user_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    related_user_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL CHECK(relationship_type IN ('friend', 'colleague', 'family', 'adversary', 'mentioned', 'unknown')),
    relationship_label TEXT,
    strength REAL DEFAULT 0.5,
    interaction_count INTEGER DEFAULT 0,
    last_interaction INTEGER,
    sentiment TEXT DEFAULT 'neutral' CHECK(sentiment IN ('positive', 'negative', 'neutral', 'mixed')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (user_id, chat_id, related_user_id),
    FOREIGN KEY (user_id, chat_id) REFERENCES user_profiles(user_id, chat_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_relationships_user ON user_relationships(user_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_user_relationships_related ON user_relationships(related_user_id);
CREATE INDEX IF NOT EXISTS idx_user_relationships_type ON user_relationships(relationship_type);
CREATE INDEX IF NOT EXISTS idx_user_relationships_strength ON user_relationships(strength);
```

---

## Implementation Steps

### 1. Design Database Schema ✓
- Add three new tables to `db/schema.sql`
- Add appropriate indexes for query performance
- Ensure foreign key constraints and cascading deletes

### 2. Implement UserProfileStore Service
**File:** `app/services/user_profile.py`

**Core Methods:**
```python
- get_or_create_profile(user_id, chat_id, display_name, username) -> dict
- update_profile(user_id, chat_id, **kwargs) -> None
- get_profile(user_id, chat_id) -> dict | None
- add_fact(user_id, chat_id, fact_type, fact_key, fact_value, confidence, ...) -> int
- get_facts(user_id, chat_id, fact_type=None, min_confidence=0.7, active_only=True) -> list[dict]
- update_fact(fact_id, **kwargs) -> None
- deactivate_fact(fact_id) -> None
- record_relationship(user_id, chat_id, related_user_id, relationship_type, ...) -> None
- get_relationships(user_id, chat_id) -> list[dict]
- get_user_summary(user_id, chat_id, include_facts=True, include_relationships=True) -> str
- update_interaction_count(user_id, chat_id, thread_id=None) -> None
- delete_profile(user_id, chat_id) -> None
```

**Features:**
- Async/await for all DB operations
- Proper error handling and logging
- Concurrent update safety with locking
- Telemetry integration

### 3. Build Fact Extraction System
**Location:** `app/services/user_profile.py` (FactExtractor class)

**Method:** `extract_user_facts(conversation_context, user_id, username) -> list[dict]`

**Process:**
1. Analyze conversation using Gemini
2. Use structured output with JSON schema
3. Extract facts with confidence scores
4. Return list of facts to store

**Prompt Structure:**
```
Analyze this conversation and extract facts about the user.
Focus on: personal info, preferences, traits, skills, opinions.
Return JSON with confidence scores (0.0-1.0).
Be conservative - only extract clear, verifiable facts.
```

**Output Schema:**
```json
{
  "facts": [
    {
      "fact_type": "personal|preference|trait|skill|opinion",
      "fact_key": "standardized_key",
      "fact_value": "the actual fact",
      "confidence": 0.0-1.0,
      "evidence": "quote supporting this"
    }
  ]
}
```

### 4. Integrate Profile Building into Message Handlers
**File:** `app/handlers/chat.py`

**Integration Points:**
- After successful bot response in `handle_group_message`
- Make async and non-blocking (fire-and-forget with asyncio.create_task)
- Don't slow down response time

**Process:**
```python
async def _update_user_profile_async(user_id, chat_id, message, context):
    """Background task to update profile after response."""
    try:
        # Update interaction count
        await profile_store.update_interaction_count(user_id, chat_id)
        
        # Extract facts from conversation
        facts = await fact_extractor.extract_user_facts(context, user_id)
        
        # Store facts
        for fact in facts:
            await profile_store.add_fact(user_id, chat_id, **fact)
        
        # Update telemetry
        telemetry.increment_counter("facts_extracted", len(facts))
    except Exception as e:
        LOGGER.error(f"Profile update failed: {e}")
        telemetry.increment_counter("profile_update_errors")
```

### 5. Enrich Context with User Profiles
**File:** `app/handlers/chat.py`

**Before Gemini Generation:**
1. Fetch user profile and facts
2. Format into compact context string
3. Inject as additional context (not system prompt to save tokens)

**Format:**
```
[User Context]
@username (User #123456): Summary text here.
Facts: location=Kyiv, likes=pizza, speaks=Ukrainian
Relationships: friends with @other_user
```

**Token Budget:**
- Max 200 tokens per user
- Prioritize high-confidence facts
- Include relationships if mentioned in conversation

### 6. Add Periodic Profile Summarization
**File:** `app/services/user_profile.py`

**Background Task:**
```python
async def summarize_profile_task(user_id, chat_id):
    """Periodically summarize accumulated facts into coherent summary."""
    # Get all active facts
    facts = await profile_store.get_facts(user_id, chat_id, active_only=True)
    
    # Use Gemini to synthesize summary
    summary = await gemini_client.generate_summary(facts)
    
    # Update profile
    await profile_store.update_profile(
        user_id, chat_id, 
        summary=summary,
        profile_version=profile_version + 1
    )
```

**Trigger:**
- Daily background task
- When fact count exceeds threshold
- Manual trigger via admin command

### 7. Implement Admin Commands
**File:** `app/handlers/admin.py`

**Commands:**
- `/gryagprofile [user_id]` - View user profile and facts
- `/gryagforget [user_id]` - Delete all profile data for user
- `/gryagfacts [user_id]` - List all facts for user
- `/gryagremovefact [fact_id]` - Remove specific fact
- `/gryagsummarize [user_id]` - Force profile summarization

**Permissions:**
- Only admin_user_ids can execute
- Confirm destructive operations
- Log all admin actions

### 8. Add Configuration and Privacy Controls
**File:** `app/config.py`

**New Settings:**
```python
ENABLE_USER_PROFILING: bool = True
USER_PROFILE_RETENTION_DAYS: int = 365
MAX_FACTS_PER_USER: int = 100
FACT_CONFIDENCE_THRESHOLD: float = 0.7
FACT_EXTRACTION_ENABLED: bool = True
PROFILE_SUMMARIZATION_INTERVAL_HOURS: int = 24
MIN_MESSAGES_FOR_EXTRACTION: int = 5
```

**Privacy Features:**
- Automatic fact expiry after retention period
- Max fact limit per user
- Ability to delete all user data
- No PII beyond Telegram IDs

### 9. Update Persona with Profile Awareness
**File:** `app/persona.py`

**Add to SYSTEM_PERSONA:**
```
## User Memory
- You have access to user profiles with facts about people you interact with
- Reference past conversations naturally: "як ти там із тією піцою?"
- Remember preferences and use them: "знаю, що ти любиш каву"
- Acknowledge relationships: "твій друг вже питав про це"
- Don't be creepy: mention facts naturally in context, not randomly
- Don't dump all facts at once - be subtle and conversational
- If you're unsure about a fact, don't mention it
- Keep your sarcastic Ukrainian personality while showing memory
```

### 10. Add Telemetry and Monitoring
**Integration:** Throughout all services

**Metrics:**
```python
- facts_extracted: Count of facts extracted
- profiles_created: New profiles
- profiles_updated: Profile updates
- context_enrichment_tokens: Tokens used for context
- fact_extraction_errors: Extraction failures
- profile_lookup_time: Performance metric
- summarization_runs: Background task executions
```

**Logging:**
```python
- DEBUG: Fact extraction decisions
- INFO: Profile updates, summarization runs
- WARNING: Threshold violations, quota issues
- ERROR: Extraction failures, DB errors
```

---

## Data Flow Example

### Scenario: User sends "Я з Києва, обожнюю кавунову піцу!"

**Step 1: Message received**
- `user_id=831570515`, `chat_id=-1001234567890`

**Step 2: Profile lookup**
- Check if profile exists, create if not
- Update `last_seen`, `interaction_count++`

**Step 3: Context enrichment (before Gemini)**
- Fetch existing profile summary and facts
- Inject: "About @kavunevapoetessa: Admin user, 247 interactions."

**Step 4: Generate response**
- Gemini generates response with context awareness

**Step 5: Background profile update**
- Extract facts: `location=Kyiv`, `food_preference=watermelon pizza`
- Store with `confidence=0.95`
- Update telemetry

**Step 6: Next conversation**
- Context includes: "About @kavunevapoetessa: Admin from Kyiv who loves watermelon pizza. 248 interactions."
- Bot can reference: "Київ, так? Класне місто."

---

## Privacy & Security Considerations

### Data Stored
- ✅ Telegram user IDs (public)
- ✅ Usernames and display names (public)
- ✅ Facts extracted from messages
- ✅ Interaction patterns
- ❌ No phone numbers
- ❌ No email addresses
- ❌ No raw message content (stored separately)

### User Rights
- Right to be forgotten: `/gryagforget` command
- Data expiry: Automatic after retention period
- Fact deletion: Admins can remove specific facts
- Transparency: `/gryagprofile` shows what's stored

### Security
- Admin-only commands for profile access
- No external API exposure
- Database is local SQLite
- Facts limited per user (prevents abuse)

---

## Performance Considerations

### Token Usage
- Profile context: ~100-200 tokens per user
- Only include profiles for active conversation participants
- Cache profiles to avoid redundant DB queries
- Prioritize high-confidence facts

### Database Performance
- Indexes on all foreign keys
- Composite indexes for common queries
- Use `LIMIT` on fact queries
- Periodic cleanup of old facts

### Async Processing
- Profile updates run in background
- Don't block message responses
- Use asyncio.create_task for fire-and-forget
- Handle failures gracefully

### Rate Limiting
- Fact extraction: Max 1 per user per 5 messages
- Summarization: Once per day per user
- Respect Gemini API quotas
- Throttle background tasks

---

## Testing Strategy

### Manual Testing
1. Send messages with personal info
2. Verify facts extracted correctly
3. Check profile enrichment in responses
4. Test admin commands
5. Verify privacy controls

### Edge Cases
- New users (no profile)
- Users with max facts
- Conflicting facts (update vs create)
- Invalid user IDs
- Deleted users
- Profile corruption

### Performance Testing
- High-volume chats
- Many users in single chat
- Large fact databases
- Concurrent updates

---

## Rollout Plan

### Phase 1: Core Infrastructure
1. Database schema
2. UserProfileStore service
3. Basic profile CRUD operations

### Phase 2: Fact Extraction
1. Gemini integration for extraction
2. Fact storage and retrieval
3. Background processing

### Phase 3: Context Enrichment
1. Profile injection into conversations
2. Token budget management
3. Performance optimization

### Phase 4: Administration
1. Admin commands
2. Privacy controls
3. Monitoring and telemetry

### Phase 5: Polish
1. Persona updates
2. Summarization tasks
3. User testing and iteration

---

## Success Metrics

- **Memory**: Bot references past conversations naturally
- **Personalization**: Responses show awareness of user preferences
- **Accuracy**: Facts are correct and relevant (confidence > 0.7)
- **Performance**: No noticeable slowdown in response time
- **Privacy**: Users can delete their data on request
- **Usage**: Increased engagement from better context awareness

---

## Future Enhancements

- Cross-chat profile linking (same user in multiple chats)
- Semantic search over facts
- Fact verification and confidence updates
- User-initiated profile updates
- Profile export functionality
- Relationship strength auto-adjustment
- Emotion/sentiment tracking
- Topic modeling for interests
- Multi-language fact extraction
