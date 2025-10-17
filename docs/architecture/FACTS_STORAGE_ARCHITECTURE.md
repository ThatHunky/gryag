# Data Model: Facts Storage Architecture

**Status**: Living document  
**Last Updated**: October 16, 2025  
**Related Files**: `db/schema.sql`, `app/services/user_profile.py`, `app/repositories/fact_repository.py`

## Overview

This document clarifies the facts storage architecture in gryag, addressing the existence of two overlapping fact tables and the migration path forward.

## Current State: Dual Fact Tables

### 1. `user_facts` Table (Active, Primary)

**Purpose**: User-specific facts storage (currently active)  
**Schema**:
```sql
CREATE TABLE user_facts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    fact_type TEXT NOT NULL,  -- personal, preference, trait, skill, opinion, relationship
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    confidence REAL,
    source_message_id INTEGER,
    evidence_text TEXT,
    is_active INTEGER DEFAULT 1,
    created_at INTEGER,
    updated_at INTEGER,
    last_mentioned INTEGER,
    FOREIGN KEY (user_id, chat_id) REFERENCES user_profiles
)
```

**Used By**:
- `app/services/user_profile.py` (UserProfileStore)
- Fact extraction pipeline (rule-based, hybrid, Gemini)
- User profiling and summarization

**Characteristics**:
- No UNIQUE constraint (updates handled programmatically)
- Foreign key cascade to user_profiles
- Actively populated by all fact extractors

### 2. `facts` Table (Unified Schema, Underutilized)

**Purpose**: Unified storage for both user AND chat-level facts  
**Schema**:
```sql
CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,  -- 'user' or 'chat'
    entity_id INTEGER NOT NULL,  -- user_id or chat_id
    chat_context INTEGER,        -- chat_id where learned (user facts only)
    fact_category TEXT NOT NULL,  -- Expanded categories including chat-level
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    confidence REAL,
    evidence_count INTEGER DEFAULT 1,
    participant_consensus REAL,  -- For chat facts
    embedding TEXT,              -- For semantic search
    ...
    UNIQUE(entity_type, entity_id, chat_context, fact_category, fact_key)
)
```

**Intended For** (per schema comments):
- Unified storage for user facts (`entity_type='user'`)
- Chat-level facts (`entity_type='chat'`) - traditions, norms, culture
- Semantic deduplication via embeddings
- Knowledge graph construction

**Current Usage**: Minimal to none in application code

## The Problem

1. **Dual writes not implemented**: Application writes only to `user_facts`, leaving `facts` empty
2. **Schema divergence risk**: Two tables with overlapping purposes can drift
3. **Confusion**: Developers/agents uncertain which table to query
4. **Wasted indexes**: `facts` table has indexes/constraints that are never used

## Design Decision: Path Forward

### Recommended: Keep Both Tables with Clear Separation

**Rationale**:
1. `user_facts` is battle-tested and actively used
2. `facts` provides valuable unified schema for future chat-level memory
3. Chat facts (traditions, culture, norms) are a planned feature (Phase 5+)
4. Unified table enables semantic deduplication across entity types

**Implementation Plan**:

#### Phase 1: Clarify Usage (Completed)
- ✅ Document that `user_facts` is the canonical user fact storage
- ✅ Document that `facts` is reserved for future unified storage
- ✅ Add this document to `docs/architecture/`

#### Phase 2: Sync Layer (Optional, Future)
If semantic deduplication or unified querying becomes needed:
- Add optional sync: `UserProfileStore.add_fact()` also writes to `facts` table
- Use `entity_type='user'`, `entity_id=user_id`, `chat_context=chat_id`
- Map `fact_type` → `fact_category` (personal, preference, etc.)
- Compute and store embeddings for semantic search

#### Phase 3: Chat Facts (Phase 5+)
When implementing chat public memory:
- Populate `facts` with `entity_type='chat'` entries
- Use `chat_facts` table (already exists) or migrate to unified `facts`
- Leverage unified schema for cross-entity queries

## Migration Path (If Needed)

If we decide to fully migrate to `facts`:

```sql
-- Backfill user_facts into facts table
INSERT INTO facts (
    entity_type, entity_id, chat_context,
    fact_category, fact_key, fact_value,
    confidence, evidence_count, evidence_text,
    first_observed, last_reinforced, is_active,
    created_at, updated_at
)
SELECT 
    'user', user_id, chat_id,
    fact_type, fact_key, fact_value,
    confidence, 1, evidence_text,
    created_at, COALESCE(last_mentioned, updated_at), is_active,
    created_at, updated_at
FROM user_facts
ON CONFLICT DO NOTHING;
```

Then update application code to use `facts` table exclusively.

## Supporting Tables

### `fact_versions`
**Purpose**: Track changes to facts over time  
**Used By**: `UserProfileStore.add_fact()` (as of Oct 16, 2025)  
**References**: `user_facts.id` via FK  

Stores:
- Version number
- Change type (creation, reinforcement, evolution, correction, contradiction)
- Confidence delta
- Timestamp

### `fact_quality_metrics`
**Purpose**: Deduplication and conflict detection  
**Status**: Schema exists, not yet populated by application  
**Planned Use**: Semantic similarity scoring, duplicate detection

### `fact_relationships`
**Purpose**: Knowledge graph edges between facts  
**Status**: Schema exists, planned for Phase 6+

### `fact_clusters`
**Purpose**: Topic-based fact organization  
**Status**: Schema exists, planned for future

## Best Practices for Developers

### When Adding User Facts
```python
# Use UserProfileStore.add_fact() - writes to user_facts
await profile_store.add_fact(
    user_id=user_id,
    chat_id=chat_id,
    fact_type="personal",
    fact_key="location",
    fact_value="Kyiv",
    confidence=0.9,
    evidence_text="я з Києва"
)
```

### When Querying User Facts
```python
# Query user_facts table via UserProfileStore
facts = await profile_store.get_facts(
    user_id=user_id,
    chat_id=chat_id,
    fact_type="personal",
    min_confidence=0.7
)
```

### When Implementing Chat Facts (Future)
```python
# Will use unified facts table or separate chat_facts
# TBD: ChatProfileStore or unified FactRepository
```

## Performance Considerations

### Current Indexes
- `user_facts`: Indexed by (user_id, chat_id), fact_type, confidence, is_active
- `facts`: Indexed by entity_type+entity_id, category, confidence, but table is empty

### Optimization Opportunities
1. If `facts` table remains unused, consider dropping it temporarily
2. If implementing sync, use async background writes to avoid latency
3. For semantic dedup, batch embedding generation (already done via semaphore)

## Testing Implications

### Current Tests Should Cover
- [x] `UserProfileStore.add_fact()` updates/inserts correctly
- [x] `fact_versions` records are created on changes
- [ ] Deduplication with normalized values (after normalizer PR)
- [ ] Fact confidence updating logic
- [ ] Cascade deletes from user_profiles

### Future Tests When Migrating
- [ ] Dual-write consistency (user_facts ↔ facts)
- [ ] Entity type filtering (user vs chat facts)
- [ ] Semantic deduplication using embeddings

## Related Documentation
- `db/schema.sql` - Source of truth for table definitions
- `docs/features/USER_PROFILING.md` - User profiling feature overview
- `docs/phases/PHASE_2_COMPLETION_REPORT.md` - Fact extraction implementation
- `docs/plans/MEMORY_AND_CONTEXT_IMPROVEMENTS.md` - Roadmap for memory features

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| Oct 16, 2025 | Keep both tables | `user_facts` is production-tested; `facts` enables future chat memory |
| Oct 16, 2025 | No immediate sync | Wait for chat facts feature before implementing dual-write |
| Oct 16, 2025 | Add fact_versions tracking | Utilize existing schema for audit trail |

## How to Verify

Check current fact storage:
```bash
sqlite3 gryag.db "SELECT COUNT(*) FROM user_facts WHERE is_active = 1"
sqlite3 gryag.db "SELECT COUNT(*) FROM facts"  # Should be 0 or minimal
```

Inspect fact versions (post-update):
```bash
sqlite3 gryag.db "SELECT fact_id, version_number, change_type, confidence_delta FROM fact_versions ORDER BY created_at DESC LIMIT 10"
```

Check for duplicates:
```bash
sqlite3 gryag.db "SELECT user_id, chat_id, fact_type, fact_key, COUNT(*) as cnt FROM user_facts WHERE is_active=1 GROUP BY user_id, chat_id, fact_type, fact_key HAVING cnt > 1"
```
