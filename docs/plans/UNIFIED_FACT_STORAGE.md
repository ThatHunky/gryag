# Unified Fact Storage Architecture

**Date:** 2025-10-08  
**Status:** Planning  
**Priority:** High  

## Goal

Replace separate `user_facts` and `chat_facts` tables with a single unified `facts` table that handles both user-level and chat-level facts cleanly.

## Current Problem

- Two incompatible fact tables with different schemas
- Facts stored in wrong table (chat facts in user_facts)
- Duplicate code in UserProfileStore and ChatProfileRepository
- Confusion about which system to use

## Unified Schema Design

### New `facts` table

```sql
CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Entity identification
    entity_type TEXT NOT NULL CHECK(entity_type IN ('user', 'chat')),
    entity_id INTEGER NOT NULL,  -- user_id or chat_id
    chat_context INTEGER,  -- chat_id where this was learned (for user facts)
    
    -- Fact taxonomy (unified categories)
    fact_category TEXT NOT NULL CHECK(fact_category IN (
        -- User-level categories
        'personal',      -- name, age, location, job
        'preference',    -- likes, dislikes, habits
        'skill',         -- programming, languages, abilities
        'trait',         -- personality, characteristics
        'opinion',       -- beliefs, stances, views
        'relationship',  -- connections to others
        
        -- Chat-level categories (from old chat_facts)
        'tradition',     -- recurring events, rituals
        'rule',          -- explicit rules, norms
        'norm',          -- implicit behaviors, patterns
        'topic',         -- common discussion topics
        'culture',       -- group personality, vibe
        'event',         -- planned events, milestones
        'shared_knowledge'  -- common references, inside jokes
    )),
    
    -- Fact content
    fact_key TEXT NOT NULL,           -- standardized identifier
    fact_value TEXT NOT NULL,         -- the actual content
    fact_description TEXT,            -- human-readable summary
    
    -- Confidence and evidence
    confidence REAL DEFAULT 0.7 CHECK(confidence >= 0 AND confidence <= 1),
    evidence_count INTEGER DEFAULT 1, -- times reinforced
    evidence_text TEXT,               -- supporting quotes
    source_message_id INTEGER,        -- where first learned
    
    -- Consensus (for chat facts)
    participant_consensus REAL,  -- % of chat members who agree (0-1)
    participant_ids TEXT,        -- JSON array of user_ids who reinforced
    
    -- Lifecycle
    first_observed INTEGER NOT NULL,  -- timestamp
    last_reinforced INTEGER NOT NULL, -- timestamp
    is_active INTEGER DEFAULT 1,      -- soft delete flag
    decay_rate REAL DEFAULT 0.0,      -- importance decay
    
    -- Metadata
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    
    -- Embedding for semantic search
    embedding TEXT,  -- JSON array
    
    -- Composite unique constraint
    UNIQUE(entity_type, entity_id, chat_context, fact_category, fact_key)
);

-- Indexes for performance
CREATE INDEX idx_facts_entity ON facts(entity_type, entity_id);
CREATE INDEX idx_facts_chat_context ON facts(chat_context) WHERE entity_type = 'user';
CREATE INDEX idx_facts_category ON facts(fact_category);
CREATE INDEX idx_facts_active ON facts(is_active) WHERE is_active = 1;
CREATE INDEX idx_facts_confidence ON facts(confidence);
```

### Companion tables (keep as-is)

- `fact_versions` - Track changes over time
- `fact_quality_metrics` - Deduplication and quality
- `fact_relationships` - Connections between facts
- `chat_fact_quality_metrics` - Chat-specific metrics (can merge later)
- `chat_fact_versions` - Chat-specific versions (can merge later)

## Migration Strategy

### Phase 1: Create new table structure

```sql
-- Create new facts table
-- Create indexes
-- Keep old tables for rollback
```

### Phase 2: Migrate existing data

```python
# Migrate user_facts
INSERT INTO facts (
    entity_type, entity_id, chat_context, fact_category,
    fact_key, fact_value, confidence, evidence_text,
    source_message_id, first_observed, last_reinforced,
    is_active, created_at, updated_at, embedding
)
SELECT 
    CASE 
        WHEN user_id < 0 THEN 'chat'  -- Fix misplaced chat facts
        ELSE 'user'
    END as entity_type,
    CASE 
        WHEN user_id < 0 THEN user_id  -- Keep negative chat_id
        ELSE user_id
    END as entity_id,
    CASE 
        WHEN user_id < 0 THEN NULL  -- Chat facts have no chat_context
        ELSE chat_id
    END as chat_context,
    fact_type as fact_category,  -- Map directly
    fact_key,
    fact_value,
    confidence,
    evidence_text,
    source_message_id,
    created_at as first_observed,
    COALESCE(last_mentioned, updated_at) as last_reinforced,
    is_active,
    created_at,
    updated_at,
    embedding
FROM user_facts;

# Migrate chat_facts
INSERT INTO facts (
    entity_type, entity_id, chat_context, fact_category,
    fact_key, fact_value, fact_description, confidence,
    evidence_count, participant_consensus, first_observed,
    last_reinforced, is_active, decay_rate, created_at, updated_at
)
SELECT 
    'chat' as entity_type,
    chat_id as entity_id,
    NULL as chat_context,  -- Chat facts don't have context
    fact_category,
    fact_key,
    fact_value,
    fact_description,
    confidence,
    evidence_count,
    participant_consensus,
    first_observed,
    last_reinforced,
    is_active,
    decay_rate,
    created_at,
    updated_at
FROM chat_facts;
```

### Phase 3: Create unified repository

```python
class UnifiedFactRepository:
    """Single repository for all fact operations."""
    
    async def add_fact(
        self,
        entity_type: Literal['user', 'chat'],
        entity_id: int,
        chat_context: int | None,
        fact_category: str,
        fact_key: str,
        fact_value: str,
        **kwargs
    ) -> int:
        """Store a fact (user or chat)."""
        
    async def get_facts(
        self,
        entity_type: Literal['user', 'chat'],
        entity_id: int,
        categories: list[str] | None = None,
        **kwargs
    ) -> list[dict]:
        """Retrieve facts."""
        
    async def update_fact(self, fact_id: int, **updates) -> None:
        """Update existing fact."""
        
    async def delete_fact(self, fact_id: int, soft: bool = True) -> None:
        """Delete or archive fact."""
```

### Phase 4: Update memory tools

```python
# Update remember_fact_tool to detect entity type
async def remember_fact_tool(
    entity_id: int,  # Can be user_id or chat_id
    fact_category: str,  # Unified taxonomy
    fact_key: str,
    fact_value: str,
    confidence: float,
    **kwargs
) -> str:
    # Auto-detect entity_type
    entity_type = 'chat' if entity_id < 0 else 'user'
    
    # Route to unified repository
    await unified_fact_repo.add_fact(
        entity_type=entity_type,
        entity_id=entity_id,
        ...
    )
```

### Phase 5: Update commands

```python
# /gryagchatfacts uses same backend
async def chatfacts_command(message: Message):
    facts = await unified_fact_repo.get_facts(
        entity_type='chat',
        entity_id=message.chat.id,
        categories=['rule', 'tradition', 'norm', 'culture', ...]
    )
```

## Benefits

1. **Single source of truth** - One table, one API, no confusion
2. **Fixes current bug** - Chat facts stored correctly
3. **Simpler codebase** - Eliminate duplicate logic
4. **Better queries** - Can find related user/chat facts
5. **Unified versioning** - Single fact_versions table works for all
6. **Flexible taxonomy** - Easy to add new categories

## Risks

1. **Data migration complexity** - Must not lose data
2. **Breaking changes** - All fact access code must update
3. **Testing burden** - Need comprehensive tests
4. **Rollback difficulty** - Hard to revert if issues found

## Mitigation

1. **Keep old tables** - Rename to `user_facts_old`, `chat_facts_old` for rollback
2. **Phased rollout** - Migrate in steps with verification
3. **Comprehensive tests** - Unit + integration tests before deploying
4. **Data validation** - Verify counts match after migration

## Implementation Plan

1. ✅ Create planning document (this file)
2. ⬜ Design unified repository API
3. ⬜ Write migration script with rollback
4. ⬜ Create UnifiedFactRepository class
5. ⬜ Update memory tools
6. ⬜ Update chat admin commands
7. ⬜ Write tests
8. ⬜ Run migration on copy of production DB
9. ⬜ Deploy to production
10. ⬜ Monitor for issues
11. ⬜ Remove old tables after 30 days

## Testing Checklist

- [ ] All user facts migrated correctly
- [ ] All chat facts migrated correctly  
- [ ] Misplaced chat facts (user_id < 0) fixed
- [ ] remember_fact tool works for users
- [ ] remember_fact tool works for chats (auto-detect)
- [ ] recall_facts tool works
- [ ] update_fact tool works
- [ ] forget_fact tool works
- [ ] /gryagchatfacts shows facts
- [ ] /gryagfacts shows user facts (if exists)
- [ ] No data loss (row counts match)
- [ ] Rollback works if needed

## Files to Modify

- `db/schema.sql` - Add new facts table
- `scripts/migrations/migrate_to_unified_facts.py` - Migration script
- `app/repositories/fact_repository.py` - New unified repo
- `app/services/tools/memory_tools.py` - Update to use unified repo
- `app/handlers/chat_admin.py` - Update commands
- `app/services/user_profile.py` - Deprecate or wrap unified repo
- `app/repositories/chat_profile.py` - Deprecate or wrap unified repo
- `tests/integration/test_unified_facts.py` - Comprehensive tests

## Timeline

- **Day 1**: Schema design + migration script
- **Day 2**: UnifiedFactRepository implementation
- **Day 3**: Update memory tools + tests
- **Day 4**: Update commands + integration tests
- **Day 5**: Testing + deployment

## Success Criteria

1. Chat facts appear in `/gryagchatfacts` ✅
2. User facts work as before ✅
3. Zero data loss ✅
4. All tests pass ✅
5. Performance same or better ✅
