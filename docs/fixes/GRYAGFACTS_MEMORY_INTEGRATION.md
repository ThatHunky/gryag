# /gryagfacts Memory Integration Fix

**Date**: 2025-10-26  
**Status**: ✅ Completed

## Problem

User reported that memory storage was working (bot replied "Запам'ятав" after user said "запам'ятай що я живу в Пролісках"), but `/gryagfacts` command returned "📭 Фактів не знайдено."

### Root Cause

The repository has **two parallel memory systems**:

1. **Old system** (`UserProfileStore`): Stores structured facts in `user_facts` table with fields like `fact_key`, `fact_value`, `confidence`, `evidence_text`
2. **New system** (`MemoryRepository`): Stores simple text memories in `user_memories` table with just `memory_text`, `created_at`, `updated_at`

The `/gryagfacts` command only queried the **old** `user_facts` table, so memories stored via the new tool-based system were invisible.

## Solution

Modified `/gryagfacts` command (`app/handlers/profile_admin.py`) to query **BOTH** tables and display unified results:

### Changes Made

1. **Import addition**:
   ```python
   from app.repositories.memory_repository import MemoryRepository
   ```

2. **Function signature update**:
   ```python
   async def get_user_facts_command(
       message: Message,
       settings: Settings,
       profile_store: UserProfileStore,
       store: ContextStore,
       memory_repo: MemoryRepository | None = None,  # NEW
   ) -> None:
   ```

3. **Data fetching logic** (lines 414-466):
   - Query old facts via `profile_store.get_user_facts()`
   - Query new memories via `memory_repo.get_memories_for_user()`
   - Combine into unified `all_items` list with type discriminator: `{"type": "fact"|"memory", ...}`
   - Calculate total count and pagination across both sources

4. **Compact format rendering** (lines 468-495):
   - Loop over `items` and check `item["type"]`
   - Facts: Display as `[ID] key: value (confidence%)`
   - Memories: Display as `[MID] 💭 memory text`

5. **Verbose format rendering** (lines 531+):
   - Facts: Show with `fact_key`, `fact_value`, confidence, evidence
   - Memories: Show with 💭 emoji, timestamp, and creation date

### Display Format

**Compact mode** (default):
```
📚 Факти: User Name
Сторінка 1/1 • Всього: 3

[1] name: John (85%)
[2] location: Kyiv (90%)
[M3] 💭 я живу в Пролісках, Бориспільський район, гряг
```

**Verbose mode** (`--verbose` flag):
```
📚 Факти: User Name (детальний режим)
Сторінка 1/1 • Всього: 3

👤 [1] name: John
   ├ Впевненість: 85%
   └ «User said: my name is John»

💭 [M3] я живу в Пролісках, Бориспільський район, гряг
   └ Створено: 2025-10-26 15:30
```

## Verification Steps

1. **Test memory storage**:
   ```
   User: запам'ятай що я живу в Пролісках
   Bot: Запам'ятав.
   ```

2. **Verify retrieval**:
   ```
   User: /gryagfacts
   Bot: Shows memory with 💭 emoji
   ```

3. **Test pagination** (if user has >5 items):
   - Should show first 5 items
   - Inline buttons: "◀️ Назад" | "1/3" | "Вперед ▶️"
   - Navigation updates displayed page

4. **Test both systems together**:
   - User with both old facts and new memories
   - `/gryagfacts` should show unified list

## Technical Details

- **Middleware injection**: `memory_repo` is injected by `ChatMetaMiddleware` (registered in `app/main.py`)
- **Memory limit**: New system enforces 15-memory FIFO limit per user
- **Pagination**: 5 items per page (configurable)
- **Type safety**: Using `item["type"]` discriminator to handle both data structures

## Files Modified

- `app/handlers/profile_admin.py`: Lines 28, 360, 414-495, 531-571

## Related Issues

- Memory storage implementation: See `docs/features/MEMORY_TOOLS.md`
- Deterministic intercept: See `docs/fixes/DETERMINISTIC_REMEMBER_INTERCEPT.md`
- Parameter filtering: See internal `_filter_internal_params` helper in `app/handlers/chat_tools.py`

## Testing

Deployed to production on 2025-10-26 17:58:34 UTC. User reported successful storage but retrieval was failing. After this fix, bot restart completed at 17:58:34, ready for user testing.

**Next step**: User should test with `/gryagfacts` command to verify memories are now visible.
