# Dynamic System Instructions Redesign Plan

**Date**: 2025-01-XX  
**Status**: Planning  
**Priority**: High

## Overview

Complete redesign of the bot's system instruction architecture to enable:
1. **Fully dynamic system instructions** that evolve from chat data
2. **Hybrid search** for messages and users (semantic + keyword)
3. **YouTube video and link processing** using Gemini API native features
4. **One-year chat history** storage and retrieval
5. **Continuous learning** from bot and user messages

## Goals

- **Zero static instructions**: Everything evolves from chat data
- **Message fragments in instructions**: Bot and user message excerpts become part of system instructions
- **Hybrid search**: Enhanced semantic + keyword search for messages and users
- **YouTube processing**: Native Gemini API support for YouTube URLs
- **Long-term memory**: 1 year of chat history accessible in text format
- **Pattern learning**: Automatic extraction of behavioral patterns and preferences

---

## 1. Dynamic System Instructions Architecture

### 1.1 Current State

- Static system prompt in `app/persona.py` and `personas/templates/ukrainian_gryag.txt`
- Fixed instructions loaded once at startup
- No learning or adaptation from chat data
- User memories injected separately (not part of core instructions)

### 1.2 New Architecture: Layered Dynamic Instructions

#### Layer 1: Base Core (Immutable Foundation)
- Minimal core identity: "You're gryag, a Ukrainian guy in group chat"
- Critical safety boundaries (if any)
- Core communication rules (language, formatting)
- Stored in code/config, rarely changes

#### Layer 2: Learned Instructions (Dynamic, Updated Periodically)
- Extracted from chat history using Gemini
- Updated daily/weekly via background jobs
- Stored in database: `system_instruction_fragments` table
- Examples:
  - "Bot always responds with sarcasm when users mention X"
  - "Users prefer short responses in this chat"
  - "Chat has established rule: Y"

#### Layer 3: Contextual Instructions (Per-Request)
- Relevant message excerpts from recent conversations
- User-specific learned behaviors
- Chat-specific norms and patterns
- Assembled dynamically for each request

### 1.3 Database Schema

```sql
-- System instruction fragments (learned patterns)
CREATE TABLE IF NOT EXISTS system_instruction_fragments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fragment_type TEXT NOT NULL CHECK(fragment_type IN (
        'behavior',      -- How bot should behave
        'preference',    -- User/chat preferences
        'rule',         -- Chat rules or norms
        'pattern',      -- Conversation patterns
        'style',        -- Response style preferences
        'relationship'  -- User relationship patterns
    )),
    source_type TEXT NOT NULL CHECK(source_type IN (
        'user_message',     -- Extracted from user message
        'bot_response',     -- Extracted from bot response
        'extracted',        -- AI-extracted pattern
        'explicit'          -- Explicitly added by admin
    )),
    source_chat_id INTEGER,
    source_message_id INTEGER,
    source_user_id INTEGER,
    fragment_text TEXT NOT NULL,
    relevance_score REAL DEFAULT 0.5,
    usage_count INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0, -- Higher = more important
    created_at INTEGER NOT NULL,
    last_used INTEGER,
    expires_at INTEGER, -- Auto-expire old fragments (NULL = never)
    metadata TEXT -- JSON for additional context
);

CREATE INDEX IF NOT EXISTS idx_fragments_type_chat
    ON system_instruction_fragments(fragment_type, source_chat_id);
CREATE INDEX IF NOT EXISTS idx_fragments_relevance
    ON system_instruction_fragments(relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_fragments_expires
    ON system_instruction_fragments(expires_at) WHERE expires_at IS NOT NULL;

-- Learning events (track what was learned when)
CREATE TABLE IF NOT EXISTS instruction_learning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER,
    extraction_type TEXT NOT NULL, -- 'pattern', 'behavior', 'rule', etc.
    extracted_fragments TEXT NOT NULL, -- JSON array of fragment IDs
    learning_model_version TEXT,
    confidence_score REAL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_events_chat
    ON instruction_learning_events(chat_id, created_at DESC);

-- Message excerpts for instruction context
CREATE TABLE IF NOT EXISTS instruction_message_excerpts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fragment_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    excerpt_text TEXT NOT NULL,
    excerpt_start INTEGER, -- Character position in original message
    excerpt_end INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (fragment_id) REFERENCES system_instruction_fragments(id) ON DELETE CASCADE
);
```

### 1.4 Implementation Components

#### A. DynamicInstructionManager

```python
# app/services/instruction/dynamic_instruction_manager.py

class DynamicInstructionManager:
    """
    Manages dynamic system instruction assembly and learning.
    """
    
    async def build_system_instruction(
        self,
        chat_id: int,
        user_id: int,
        base_persona: str,
        max_tokens: int = 2000
    ) -> str:
        """
        Build complete system instruction from:
        1. Base persona (immutable core)
        2. Learned fragments (top N by relevance)
        3. User-specific patterns
        4. Chat-specific patterns
        5. Recent message excerpts (if space allows)
        """
        
    async def learn_from_messages(
        self,
        chat_id: int,
        message_batch: list[Message],
        gemini_client: GeminiClient
    ) -> list[InstructionFragment]:
        """
        Extract instruction-worthy patterns from message batch.
        Uses Gemini to analyze and extract:
        - Behavioral patterns
        - Preference signals
        - Rule establishment
        - Style preferences
        """
        
    async def extract_fragments(
        self,
        messages: list[dict],
        gemini_client: GeminiClient
    ) -> list[dict]:
        """
        Use Gemini with structured output to extract instruction fragments.
        Returns list of fragments with types and confidence scores.
        """
```

#### B. Instruction Learning Job

```python
# app/services/instruction/learning_job.py

class InstructionLearningJob:
    """
    Background job that periodically analyzes chat history
    and extracts new instruction fragments.
    """
    
    async def run_daily_learning(self):
        """
        Daily job:
        1. Analyze last 7 days of messages per chat
        2. Extract patterns using Gemini
        3. Store new fragments
        4. Update relevance scores
        5. Expire old fragments
        """
        
    async def run_weekly_evolution(self):
        """
        Weekly job:
        1. Review all fragments
        2. Merge similar fragments
        3. Promote high-usage fragments
        4. Demote unused fragments
        5. Generate chat summaries for long-term learning
        """
```

#### C. Fragment Extraction Prompt

```python
EXTRACTION_PROMPT = """
Analyze the following chat messages and extract instruction-worthy patterns.

Extract:
1. Behavioral patterns: How the bot responds in specific situations
2. User preferences: What users like/dislike about responses
3. Chat rules: Established norms or rules in the conversation
4. Style patterns: Preferred response formats, length, tone
5. Relationship patterns: How bot interacts with specific users

For each pattern found, provide:
- fragment_type: behavior|preference|rule|pattern|style|relationship
- fragment_text: Clear instruction text (1-2 sentences)
- confidence: 0.0-1.0
- source_message_ids: Which messages support this pattern

Return as JSON array.
"""
```

### 1.5 Fragment Selection Algorithm

```python
async def select_fragments(
    chat_id: int,
    user_id: int | None,
    max_tokens: int
) -> list[InstructionFragment]:
    """
    Select top fragments for instruction assembly:
    
    1. Base fragments (priority > 8, never expire)
    2. Chat-specific fragments (source_chat_id = chat_id)
    3. User-specific fragments (if user_id provided)
    4. Recent high-relevance fragments
    5. Fill remaining space with general patterns
    
    Prioritize by:
    - priority (higher first)
    - relevance_score (higher first)
    - usage_count (higher first)
    - recency (more recent first)
    """
```

---

## 2. Hybrid Search Enhancement

### 2.1 Current State

- `HybridSearchEngine` exists in `app/services/context/hybrid_search.py`
- Combines: semantic (embeddings), keyword (FTS5), temporal, importance
- Only searches messages, not users
- Limited cross-modal capabilities

### 2.2 Enhancements

#### A. User Search Integration

```python
# Extend HybridSearchEngine

async def search_users(
    self,
    query: str,
    chat_id: int,
    limit: int = 10,
    time_range_days: int | None = None
) -> list[UserSearchResult]:
    """
    Hybrid search for users combining:
    - Username/display name (keyword match)
    - Message content patterns (semantic similarity)
    - Interaction history (temporal recency)
    - Mention frequency (importance weighting)
    - User profile embeddings (if available)
    """
    # 1. Keyword search: username, display_name in user_profiles
    # 2. Semantic search: user profile summaries, recent messages
    # 3. Temporal: recent activity, last_seen
    # 4. Importance: message_count, interaction_count
    # 5. Combine scores and rank
```

#### B. Cross-Modal Search

```python
async def search_messages_and_users(
    self,
    query: str,
    chat_id: int,
    search_type: str = 'both',  # 'messages', 'users', 'both'
    limit: int = 10
) -> dict[str, list]:
    """
    Unified search returning both messages and users.
    """
    results = {
        'messages': [],
        'users': []
    }
    
    if search_type in ('messages', 'both'):
        results['messages'] = await self.search(...)
    
    if search_type in ('users', 'both'):
        results['users'] = await self.search_users(...)
    
    return results
```

#### C. User Profile Embeddings

```sql
-- Add embedding column to user_profiles
ALTER TABLE user_profiles ADD COLUMN profile_embedding TEXT;

-- Index for semantic user search
CREATE INDEX IF NOT EXISTS idx_user_profiles_embedding
    ON user_profiles(profile_embedding) WHERE profile_embedding IS NOT NULL;
```

```python
# Generate embeddings for user profiles
async def update_user_profile_embedding(
    user_id: int,
    chat_id: int,
    gemini_client: GeminiClient
):
    """
    Generate embedding from user profile summary.
    Update when profile changes significantly.
    """
    profile = await profile_store.get_user_profile(user_id, chat_id)
    summary = build_profile_summary(profile)  # Name, facts, recent activity
    embedding = await gemini_client.embed_text(summary)
    await profile_store.update_embedding(user_id, chat_id, embedding)
```

### 2.3 Enhanced Search Features

- **Topic-based search**: Search by conversation topics
- **Time-range + semantic**: "Find messages about X in last month"
- **User + topic**: "What did user Y say about topic Z"
- **Media-aware search**: Search messages with specific media types

---

## 3. YouTube Video & Link Processing

### 3.1 Current State

- `build_media_parts()` in `app/services/gemini.py` handles `file_uri`
- YouTube URL detection not implemented
- Regular links use `fetch_web_content_tool` (HTML parsing)

### 3.2 Gemini API Native YouTube Support

Gemini API supports YouTube URLs directly via `file_data.file_uri`:

```python
# In app/services/gemini.py

def _is_youtube_url(self, url: str) -> bool:
    """Check if URL is a YouTube video."""
    patterns = [
        r'youtube\.com/watch\?v=([\w-]+)',
        r'youtu\.be/([\w-]+)',
        r'youtube\.com/embed/([\w-]+)',
        r'youtube\.com/v/([\w-]+)'
    ]
    for pattern in patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False

def _normalize_youtube_url(self, url: str) -> str:
    """Normalize YouTube URL to standard format."""
    # Extract video ID and return: https://www.youtube.com/watch?v=VIDEO_ID
    # Gemini accepts various formats but normalize for consistency
    pass

def build_media_parts(
    self,
    media_items: Iterable[dict[str, Any]],
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """
    Enhanced to detect and process YouTube URLs.
    """
    parts: list[dict[str, Any]] = []
    
    for item in media_items:
        # Check for YouTube URL in file_uri or text
        url = item.get("file_uri") or item.get("url") or ""
        
        if url and self._is_youtube_url(url):
            normalized_url = self._normalize_youtube_url(url)
            parts.append({
                "file_data": {
                    "file_uri": normalized_url
                },
                "mime": "video/mp4",  # Gemini handles YouTube as video
                "kind": "video"
            })
            if logger:
                logger.info(f"Added YouTube video: {normalized_url}")
            continue
        
        # Existing inline data handling...
        # ...
```

### 3.3 YouTube URL Detection in Messages

```python
# In app/handlers/chat.py or message processing

YOUTUBE_PATTERN = re.compile(
    r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([\w-]+)',
    re.IGNORECASE
)

async def extract_youtube_urls(text: str) -> list[str]:
    """Extract YouTube URLs from message text."""
    matches = YOUTUBE_PATTERN.findall(text)
    return [f"https://www.youtube.com/watch?v={vid}" for vid in matches]

# When processing messages:
youtube_urls = extract_youtube_urls(message.text or "")
if youtube_urls:
    for url in youtube_urls:
        media_parts.append({
            "file_uri": url,
            "kind": "video",
            "mime": "video/mp4"
        })
```

### 3.4 YouTube Metadata Storage

```sql
-- Add YouTube metadata to messages table
-- (or extend media JSON field)

-- Store in messages.media JSON:
{
    "youtube_videos": [
        {
            "url": "https://www.youtube.com/watch?v=...",
            "video_id": "...",
            "title": "...",  -- Extracted if possible
            "duration": 123, -- If available
            "processed_at": 1234567890
        }
    ]
}
```

### 3.5 Enhanced Link Processing

For non-YouTube links, enhance `fetch_web_content_tool`:

```python
# Use Gemini Grounding API if available
# Or improve HTML parsing with better content extraction

async def fetch_web_content_enhanced(
    url: str,
    gemini_client: GeminiClient | None = None
) -> dict:
    """
    Enhanced web content fetching:
    1. Try Gemini Grounding API (if available)
    2. Fallback to HTML parsing
    3. Extract main content, title, metadata
    """
    # If Gemini Grounding available:
    #   Use grounding API for better content extraction
    # Else:
    #   Use existing HTML parsing
    pass
```

---

## 4. One-Year Chat History Storage

### 4.1 Current State

- Messages stored in `messages` table
- `retention_days` setting controls retention
- Embeddings stored for semantic search
- No archive mechanism for old messages

### 4.2 Long-Term Storage Strategy

#### A. Archive Table

```sql
-- Archive table for messages older than 1 year
CREATE TABLE IF NOT EXISTS messages_archive (
    -- Same structure as messages table
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    thread_id INTEGER,
    user_id INTEGER,
    external_message_id TEXT,
    external_user_id TEXT,
    reply_to_external_message_id TEXT,
    reply_to_external_user_id TEXT,
    sender_role TEXT,
    sender_name TEXT,
    sender_username TEXT,
    sender_is_bot INTEGER DEFAULT 0,
    role TEXT NOT NULL,
    text TEXT,
    media TEXT,
    embedding TEXT,
    ts INTEGER NOT NULL,
    archived_at INTEGER NOT NULL
);

-- Partition by year/month for performance
CREATE INDEX IF NOT EXISTS idx_archive_chat_year
    ON messages_archive(chat_id, ts);
CREATE INDEX IF NOT EXISTS idx_archive_year_month
    ON messages_archive(ts) WHERE ts >= ? AND ts < ?;
```

#### B. Migration Job

```python
# app/services/archive/message_archiver.py

class MessageArchiver:
    """
    Handles archiving of old messages.
    """
    
    async def archive_old_messages(
        self,
        older_than_days: int = 365
    ):
        """
        Move messages older than 1 year to archive table.
        Run monthly.
        """
        cutoff_ts = int(time.time()) - (older_than_days * 86400)
        
        # Move messages in batches
        # Preserve all data including embeddings
        # Update indexes after migration
        pass
    
    async def restore_from_archive(
        self,
        chat_id: int,
        start_ts: int,
        end_ts: int
    ) -> list[dict]:
        """
        Restore messages from archive for search/analysis.
        """
        pass
```

#### C. Text-Based History Export

```sql
CREATE TABLE IF NOT EXISTS chat_history_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    export_type TEXT NOT NULL, -- 'full', 'yearly', 'monthly'
    start_ts INTEGER,
    end_ts INTEGER,
    file_path TEXT, -- Path to exported text file
    file_size INTEGER,
    message_count INTEGER,
    created_at INTEGER NOT NULL
);
```

```python
# app/services/archive/history_exporter.py

class ChatHistoryExporter:
    """
    Exports chat history to text files for long-term storage.
    """
    
    async def export_chat_history(
        self,
        chat_id: int,
        start_ts: int | None = None,
        end_ts: int | None = None,
        format: str = 'text'  # 'text', 'json', 'markdown'
    ) -> str:
        """
        Export chat history to text file.
        Format:
        [2024-01-15 10:30:45] @username: Message text
        [2024-01-15 10:31:12] @bot_username: Bot response
        
        Returns file path.
        """
        pass
    
    async def export_yearly_history(
        self,
        chat_id: int,
        year: int
    ) -> str:
        """Export specific year's history."""
        start_ts = datetime(year, 1, 1).timestamp()
        end_ts = datetime(year + 1, 1, 1).timestamp()
        return await self.export_chat_history(chat_id, int(start_ts), int(end_ts))
```

#### D. Summarization for Long History

```sql
CREATE TABLE IF NOT EXISTS chat_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    summary_type TEXT NOT NULL, -- 'weekly', 'monthly', 'yearly'
    period_start INTEGER NOT NULL,
    period_end INTEGER NOT NULL,
    summary_text TEXT NOT NULL,
    key_topics TEXT, -- JSON array
    message_count INTEGER,
    created_at INTEGER NOT NULL,
    model_version TEXT
);

CREATE INDEX IF NOT EXISTS idx_summaries_chat_period
    ON chat_summaries(chat_id, period_start, period_end);
```

```python
# app/services/archive/history_summarizer.py

class ChatHistorySummarizer:
    """
    Creates summaries of chat history for long-term context.
    """
    
    async def summarize_period(
        self,
        chat_id: int,
        start_ts: int,
        end_ts: int,
        gemini_client: GeminiClient
    ) -> dict:
        """
        Use Gemini to summarize a time period:
        - Key topics discussed
        - Important events
        - User activity patterns
        - Notable conversations
        """
        # Fetch messages in period
        # Use Gemini to generate summary
        # Store in chat_summaries table
        pass
```

### 4.3 History Retrieval for Instructions

When building dynamic instructions, include summaries:

```python
async def get_chat_context_for_instructions(
    chat_id: int,
    months_back: int = 12
) -> str:
    """
    Get summarized chat history for instruction context.
    Returns text combining:
    - Recent summaries (last N months)
    - Key patterns from full history
    - Important events
    """
    summaries = await get_summaries(chat_id, months_back)
    return "\n\n".join([s.summary_text for s in summaries])
```

---

## 5. Learning from Chat Data

### 5.1 Multi-Layer Learning System

#### Layer 1: Immediate Learning (Real-time)
- Extract facts from current conversation
- Update user memories (already implemented)
- Store chat-level facts
- **No changes needed** - already working

#### Layer 2: Pattern Learning (Daily/Weekly)
- Analyze message patterns using Gemini
- Extract behavioral patterns
- Store as instruction fragments

```python
# app/services/instruction/pattern_learner.py

class PatternLearner:
    """
    Analyzes chat history to extract behavioral patterns.
    """
    
    async def analyze_message_patterns(
        self,
        chat_id: int,
        days_back: int = 7,
        gemini_client: GeminiClient
    ) -> list[InstructionFragment]:
        """
        Analyze last N days of messages:
        1. Fetch messages
        2. Use Gemini to extract patterns
        3. Return instruction fragments
        """
        messages = await store.get_messages_since(
            chat_id,
            days_back=days_back
        )
        
        # Build analysis prompt
        prompt = build_pattern_analysis_prompt(messages)
        
        # Use Gemini with structured output
        response = await gemini_client.generate(
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            history=[],
            user_parts=[{"text": prompt}],
            tools=None  # Or use JSON schema for structured output
        )
        
        # Parse fragments from response
        fragments = parse_fragments(response)
        return fragments
```

#### Layer 3: Instruction Evolution (Weekly/Monthly)
- Review learned patterns
- Generate instruction fragments
- Update system instruction pool
- Remove outdated fragments

```python
# app/services/instruction/evolution_manager.py

class InstructionEvolutionManager:
    """
    Manages evolution of instruction fragments over time.
    """
    
    async def evolve_instructions(
        self,
        chat_id: int
    ):
        """
        Weekly evolution process:
        1. Review all fragments for chat
        2. Merge similar fragments
        3. Promote high-usage fragments (increase priority)
        4. Demote unused fragments (decrease relevance)
        5. Expire old fragments (set expires_at)
        6. Generate new fragments from recent patterns
        """
        pass
    
    async def merge_similar_fragments(
        self,
        fragments: list[InstructionFragment],
        similarity_threshold: float = 0.8
    ) -> list[InstructionFragment]:
        """
        Use embeddings to find similar fragments and merge them.
        """
        pass
```

### 5.2 Learning Prompts

#### Pattern Extraction Prompt

```python
PATTERN_EXTRACTION_PROMPT = """
Analyze the following chat messages from the last {days} days.

Extract instruction-worthy patterns in these categories:

1. **Behavioral Patterns**: How the bot responds in specific situations
   - Example: "Bot always uses sarcasm when users mention topic X"
   - Example: "Bot responds with one-word answers to simple questions"

2. **User Preferences**: What users like/dislike about responses
   - Example: "Users prefer short, direct responses"
   - Example: "Users appreciate when bot references past conversations"

3. **Chat Rules**: Established norms or rules in the conversation
   - Example: "Chat has rule: No Russian language allowed"
   - Example: "Users expect bot to moderate spam automatically"

4. **Style Patterns**: Preferred response formats, length, tone
   - Example: "Bot uses more profanity in this chat than others"
   - Example: "Responses should be 1-2 sentences maximum"

5. **Relationship Patterns**: How bot interacts with specific users
   - Example: "Bot is more formal with user X"
   - Example: "Bot makes jokes with user Y"

For each pattern found, provide:
- fragment_type: behavior|preference|rule|pattern|style|relationship
- fragment_text: Clear instruction text (1-2 sentences, actionable)
- confidence: 0.0-1.0 (how certain you are this is a real pattern)
- source_message_ids: Array of message IDs that support this pattern
- reasoning: Brief explanation of why this pattern was identified

Return as JSON array of pattern objects.
"""
```

#### Evolution Review Prompt

```python
EVOLUTION_REVIEW_PROMPT = """
Review the following instruction fragments for chat {chat_id}.

Current fragments:
{existing_fragments}

Recent chat activity (last 30 days):
{recent_activity_summary}

Tasks:
1. Identify fragments that are no longer relevant (expire them)
2. Find similar fragments that should be merged
3. Identify high-value fragments that should be promoted (increase priority)
4. Suggest new fragments based on recent patterns

Return JSON with:
- fragments_to_expire: [fragment_ids]
- fragments_to_merge: [[fragment_id1, fragment_id2], ...]
- fragments_to_promote: [fragment_ids]
- new_fragments: [new fragment objects]
"""
```

### 5.3 Learning Schedule

```python
# Background jobs in app/services/instruction/jobs.py

@schedule.every(1).days.at("02:00")  # 2 AM daily
async def daily_pattern_learning():
    """
    Daily: Analyze last 7 days, extract new patterns.
    """
    for chat_id in active_chats:
        learner = PatternLearner()
        fragments = await learner.analyze_message_patterns(
            chat_id,
            days_back=7
        )
        await instruction_manager.store_fragments(fragments)

@schedule.every(7).days.at("03:00")  # 3 AM weekly
async def weekly_instruction_evolution():
    """
    Weekly: Evolve instructions, merge, promote, expire.
    """
    for chat_id in active_chats:
        evolution = InstructionEvolutionManager()
        await evolution.evolve_instructions(chat_id)

@schedule.every(30).days.at("04:00")  # 4 AM monthly
async def monthly_history_summarization():
    """
    Monthly: Summarize chat history, archive old messages.
    """
    summarizer = ChatHistorySummarizer()
    archiver = MessageArchiver()
    
    for chat_id in active_chats:
        # Summarize last month
        await summarizer.summarize_period(chat_id, ...)
        
        # Archive messages older than 1 year
        await archiver.archive_old_messages(older_than_days=365)
```

---

## 6. Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Create database tables for instruction fragments
- [ ] Implement `DynamicInstructionManager` class
- [ ] Create fragment extraction using Gemini
- [ ] Modify system instruction builder to use fragments
- [ ] Test with small chat history

### Phase 2: YouTube & Links (Week 2-3)
- [ ] Add YouTube URL detection in message processing
- [ ] Enhance `build_media_parts()` for YouTube URLs
- [ ] Test YouTube processing with Gemini API
- [ ] Store YouTube metadata for search
- [ ] Enhance link processing (if needed)

### Phase 3: Enhanced Search (Week 3-4)
- [ ] Add user search to `HybridSearchEngine`
- [ ] Implement user profile embeddings
- [ ] Add cross-modal search (messages + users)
- [ ] Test search performance

### Phase 4: Long-Term History (Week 4-5)
- [ ] Implement archive table and migration
- [ ] Create message archiver job
- [ ] Implement text export functionality
- [ ] Add summarization pipeline
- [ ] Test with large chat history

### Phase 5: Learning Pipeline (Week 5-6)
- [ ] Implement pattern extraction job
- [ ] Create instruction evolution system
- [ ] Add fragment relevance scoring
- [ ] Implement auto-expiration
- [ ] Set up background job scheduling

### Phase 6: Integration & Testing (Week 6-7)
- [ ] Integrate all components
- [ ] End-to-end testing
- [ ] Performance optimization
- [ ] Monitor learning quality
- [ ] Adjust thresholds and parameters

---

## 7. Technical Considerations

### 7.1 Token Budget Management

- Dynamic instructions must fit within token limits
- Prioritize fragments by: priority > relevance > usage > recency
- Use summarization for long fragments
- Cache frequently used instruction combinations

```python
async def assemble_instructions_within_budget(
    base_persona: str,
    fragments: list[InstructionFragment],
    max_tokens: int
) -> str:
    """
    Assemble instructions staying within token budget.
    """
    # 1. Start with base persona
    # 2. Add fragments in priority order until budget reached
    # 3. Summarize remaining fragments if needed
    # 4. Return complete instruction
    pass
```

### 7.2 Performance Optimization

- Cache instruction assemblies per (chat_id, user_id) combination
- Use background jobs for learning (don't block requests)
- Index instruction fragments for fast retrieval
- Batch process learning jobs

```python
# Cache key: (chat_id, user_id, fragment_hash)
INSTRUCTION_CACHE_TTL = 3600  # 1 hour

async def get_cached_instruction(
    chat_id: int,
    user_id: int,
    fragment_hash: str
) -> str | None:
    """Get cached instruction if available."""
    pass
```

### 7.3 Quality Control

- Validate extracted fragments before storing
- Monitor instruction quality metrics
- Track fragment usage and effectiveness
- Alert on unusual patterns

```python
class FragmentValidator:
    """
    Validates instruction fragments before storage.
    """
    
    def validate_fragment(
        self,
        fragment: InstructionFragment
    ) -> tuple[bool, str]:
        """
        Returns (is_valid, error_message).
        Checks:
        - Fragment text is not empty
        - Confidence score is reasonable
        - Fragment type matches content
        - No harmful content
        """
        pass
```

### 7.4 Monitoring & Metrics

Track:
- Number of fragments per chat
- Fragment usage frequency
- Instruction assembly time
- Learning job success rate
- YouTube processing success rate
- Search performance

---

## 8. Configuration

### New Settings

```python
# app/config.py

class Settings(BaseSettings):
    # ... existing settings ...
    
    # Dynamic instructions
    enable_dynamic_instructions: bool = True
    max_instruction_fragments: int = 20
    instruction_token_budget: int = 2000
    fragment_relevance_threshold: float = 0.6
    fragment_expiry_days: int = 90  # Expire unused fragments after 90 days
    
    # Learning
    enable_instruction_learning: bool = True
    learning_analysis_days: int = 7  # Analyze last N days
    learning_confidence_threshold: float = 0.7
    
    # YouTube
    enable_youtube_processing: bool = True
    max_youtube_videos_per_message: int = 5
    
    # History
    chat_history_retention_years: int = 1
    enable_history_archiving: bool = True
    enable_history_summarization: bool = True
    summary_period_days: int = 30  # Summarize every N days
```

---

## 9. Testing Strategy

### Unit Tests
- Fragment extraction logic
- Instruction assembly
- YouTube URL detection
- Search enhancements

### Integration Tests
- End-to-end instruction building
- Learning job execution
- Archive and restore
- Search across messages and users

### Performance Tests
- Instruction assembly time
- Learning job duration
- Search query performance
- Large history handling

---

## 10. Migration Plan

### Existing Data
- No migration needed for existing messages
- Existing user memories remain unchanged
- Static persona can coexist during transition

### Rollout
1. Deploy database schema changes
2. Enable learning jobs (read-only initially)
3. Gradually enable dynamic instructions
4. Monitor and adjust
5. Disable static persona once stable

---

## 11. Open Questions / Decisions Needed

1. **Fragment Priority System**: How to determine initial priority for fragments?
   - Suggestion: Admin-set, or based on confidence + source type

2. **Learning Frequency**: Daily vs weekly for pattern extraction?
   - Suggestion: Daily for active chats, weekly for others

3. **Fragment Limits**: Max fragments per chat?
   - Suggestion: 50-100 fragments per chat, top 20 used per request

4. **YouTube Processing**: Process all YouTube URLs or only when mentioned?
   - Suggestion: Process when explicitly shared or mentioned

5. **History Export Format**: Text, JSON, or both?
   - Suggestion: Both, with text as primary for readability

6. **Summarization Granularity**: Weekly, monthly, or both?
   - Suggestion: Monthly summaries, weekly for very active chats

---

## 12. Success Metrics

- **Instruction Quality**: Fragments are relevant and useful
- **Learning Rate**: New patterns discovered regularly
- **Performance**: Instruction assembly < 100ms
- **Search**: Hybrid search finds relevant results
- **YouTube**: Videos processed successfully
- **History**: 1 year of history accessible and searchable

---

## Notes

- All groups are private, so privacy considerations are minimal
- Focus on functionality and learning quality
- Monitor for any performance issues with large chat histories
- Be prepared to adjust thresholds based on real-world usage

