# Chat Facts Not Showing in /gryagchatfacts

**Date:** 2025-10-08  
**Status:** Identified  
**Severity:** High (core feature broken)

## Problem

When the bot "remembers" a chat-level fact (like chat rules), it confirms storage but the fact doesn't appear when using `/gryagchatfacts` command.

### Example
```
User: правила чату
Правила:
1. Любити кавунову пітсу
2. Російська мова заборонена

Bot: О, батько! Я це запам'ятав. "Любити кавунову пітсу" і щоб руснявого лайна тут не було.

User: /gryagchatfacts
Bot: 📭 Ще немає фактів про цей чат.
```

## Root Cause

There are **two separate fact storage systems** in the database that are not integrated:

### 1. User Facts System (`user_facts` table)
- Used by memory tools: `remember_fact`, `recall_facts`, `update_fact`, `forget_fact`
- Accessed via `UserProfileStore` 
- Stores individual user facts
- Columns: `user_id`, `chat_id`, `fact_type` (personal/preference/skill/trait/opinion/relationship)

### 2. Chat Facts System (`chat_facts` table)  
- Used by `/gryagchatfacts` command
- Accessed via `ChatProfileRepository`
- Stores group-level facts
- Columns: `chat_id`, `fact_category` (preference/tradition/rule/norm/topic/culture/event/shared_knowledge)

### What's Happening

1. Gemini calls `remember_fact(user_id=-1002604868951, fact_type='trait', fact_key='chat_rule', ...)`
2. The tool stores to `user_facts` table with `user_id = chat_id`
3. The `/gryagchatfacts` command queries the `chat_facts` table
4. Result: Fact is stored but not visible

### Database Evidence

```sql
-- Fact IS stored in user_facts (wrong table)
SELECT * FROM user_facts WHERE user_id = -1002604868951;
-- Result: 1 row - ('trait', 'chat_rule', 'любити кавунову пітсу', 0.95)

-- chat_facts table is empty (correct table)
SELECT COUNT(*) FROM chat_facts;
-- Result: 0
```

## Impact

- Chat memory feature appears broken to users
- Facts are stored but inaccessible via commands
- Data is split across two incompatible tables
- Migration will be needed to consolidate existing data

## Solution Options

### Option 1: Add Chat Fact Detection to Memory Tools (Quick Fix)
Modify `remember_fact_tool()` to:
1. Detect when `user_id` is negative (chat ID)
2. Route to `ChatProfileRepository.add_chat_fact()` instead of `UserProfileStore.add_fact()`
3. Map fact types to appropriate chat categories:
   - `trait` → `rule` or `culture`
   - `preference` → `preference`
   - etc.

**Pros:**
- No changes to Gemini tool definitions
- Works with existing calls
- Minimal code changes

**Cons:**
- Hacky detection logic
- Still mixing user/chat concepts in one tool

### Option 2: Create Separate Chat Memory Tools (Clean Solution)
Add new tools:
- `remember_chat_fact` - for group-level facts
- `recall_chat_facts` - query chat facts
- `update_chat_fact` - modify chat facts
- `forget_chat_fact` - remove chat facts

With proper `fact_category` enum (preference/tradition/rule/norm/topic/culture/event/shared_knowledge)

**Pros:**
- Clean separation of concerns
- Better tool descriptions for Gemini
- Proper category types
- Matches database schema

**Cons:**
- More tools for Gemini to learn
- Need to update system prompts
- More code to maintain

### Option 3: Unify Tables (Major Refactor)
Merge `user_facts` and `chat_facts` into single `facts` table with:
- `entity_type` (user/chat)
- `entity_id` (user_id or chat_id)
- Unified fact taxonomy

**Pros:**
- Single source of truth
- Simpler codebase long-term

**Cons:**
- Requires schema migration
- Breaking change
- Need to update all queries
- Risk of data loss

## Recommended Approach

**Phase 1 (Immediate):** Option 1 - Add detection logic
- Quick fix to restore functionality
- Migrate existing chat facts from `user_facts` to `chat_facts`
- Document the workaround

**Phase 2 (Next sprint):** Option 2 - Proper chat memory tools  
- Add dedicated chat fact tools
- Update system prompts
- Deprecate using `remember_fact` for chat facts

**Phase 3 (Future):** Consider Option 3 if pain points emerge
- Only if we see significant duplication/confusion
- Requires careful planning and testing

## Migration Script Needed

```python
# Move existing chat facts from user_facts to chat_facts
# WHERE user_id < 0 (negative = chat ID)
# Map fact_type → fact_category
# Generate fact_description from fact_key + fact_value
```

## Files Involved

- `app/services/tools/memory_tools.py` - Tool implementations
- `app/services/tools/memory_definitions.py` - Gemini tool definitions
- `app/handlers/chat_admin.py` - `/gryagchatfacts` command
- `app/repositories/chat_profile.py` - ChatProfileRepository
- `app/services/user_profile.py` - UserProfileStore
- `db/schema.sql` - Table definitions

## How to Verify

After fix:
1. Clear test data: `DELETE FROM chat_facts; DELETE FROM user_facts WHERE user_id < 0;`
2. Send chat rule: "правила чату: любити кавунову пітсу"
3. Check storage: `SELECT * FROM chat_facts;` (should have 1 row)
4. Check command: `/gryagchatfacts` (should show the fact)
5. Verify category mapping is correct (trait.chat_rule → rule category)

## Related Issues

- Chat memory system introduced in Phase 4
- User memory system existed since Phase 1
- Systems developed independently without integration plan
- Need architectural review of fact storage strategy
