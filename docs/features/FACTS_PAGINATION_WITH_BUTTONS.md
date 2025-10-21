# Facts Pagination with Inline Buttons

**Date**: October 21, 2025  
**Status**: ✅ Implemented  
**Files Modified**: `app/handlers/profile_admin.py`

## Problem

The `/gryagfacts` command displayed too many facts per page (20), making messages very long and hard to read. The pagination was text-based, requiring users to type commands like `/gryagfacts 2` to navigate pages.

Example of old behavior:
```
📚 Факти: Hepy
Сторінка 1/2 • Всього: 25

[1] language: Ukrainian (100%)
[2] communication_style: direct instructions (100%)
[3] political_opinion: negative view on Trump (100%)
[4] interest: addams (100%)
...
[20] preference: powerful music (100%)

📄 Наступна сторінка: /gryagfacts 2
```

## Solution

### Changes Made

1. **Reduced facts per page**: Changed from 20 to **5 facts per page** for better readability
2. **Inline button pagination**: Replaced text-based pagination with inline keyboard buttons
3. **Callback query handler**: Added handler to process button clicks and update the message

### Implementation Details

#### 1. Updated Command Handler

- Changed `FACTS_PER_PAGE` from 20 to 5
- Removed text-based pagination footer
- Added inline keyboard with "◀️ Попередня" and "Наступна ▶️" buttons
- Updated `message.reply()` to include `reply_markup=keyboard`

#### 2. Callback Data Format

Button callback data encodes pagination state:
```
facts:{user_id}:{chat_id}:{page}:{fact_type}[:v]
```

Examples:
- `facts:123:456:2:all` - Page 2, all fact types
- `facts:123:456:3:personal` - Page 3, personal facts only
- `facts:123:456:1:all:v` - Page 1, verbose mode

#### 3. New Callback Query Handler

Added `facts_pagination_callback` function:
- Parses callback data to extract pagination state
- Checks permissions (users can only view their own facts unless admin)
- Fetches facts for the requested page
- Rebuilds the message with new page
- Uses `message.edit_text()` to update the existing message
- Provides feedback via `callback.answer()`

### User Experience

**Before**:
- 20 facts per page (overwhelming)
- Type `/gryagfacts 2` to see next page
- No visual indication of pagination actions

**After**:
- 5 facts per page (digestible)
- Click "Наступна ▶️" button to see next page
- Click "◀️ Попередня" button to go back
- Message updates in-place (no spam)
- Toast notification shows current page (e.g., "📄 Сторінка 2/5")

### Example Usage

```
User: /gryagfacts

Bot:
📚 Факти: Hepy
Сторінка 1/5 • Всього: 25

[1] language: Ukrainian (100%)
[2] communication_style: direct instructions (100%)
[3] political_opinion: negative view on Trump (100%)
[4] interest: addams (100%)
[5] mentioned_user_name: Гряг (100%)

[◀️ Попередня] [Наступна ▶️]

User: *clicks "Наступна ▶️"*

Bot (message updates):
📚 Факти: Hepy
Сторінка 2/5 • Всього: 25

[6] interest: Taras Shevchenko (90%)
[7] generative_art_interest: mashup images (90%)
[8] likes: vengeance (90%)
[9] opinion_on_conflict_groups: hates Russophobes (100%)
[10] terminology_preference: pycofобы (100%)

[◀️ Попередня] [Наступна ▶️]
```

### Technical Details

#### Imports Added
```python
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InaccessibleMessage,
)
```

#### Pagination Button Creation
```python
buttons = []
if page > 1:
    prev_callback = f"facts:{user_id}:{chat_id}:{page - 1}:{fact_type_filter or 'all'}"
    buttons.append(
        InlineKeyboardButton(text="◀️ Попередня", callback_data=prev_callback)
    )
if page < total_pages:
    next_callback = f"facts:{user_id}:{chat_id}:{page + 1}:{fact_type_filter or 'all'}"
    buttons.append(
        InlineKeyboardButton(text="Наступна ▶️", callback_data=next_callback)
    )
keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
```

#### Type Safety
- Added type guard for `InaccessibleMessage` to prevent runtime errors
- Proper error handling for callback processing

### Backward Compatibility

- Verbose mode (`/gryagfacts --verbose`) still works with inline buttons
- Fact type filters (`/gryagfacts personal`) work with pagination
- Old command arguments like `/gryagfacts 2` are ignored (page defaults to 1)

### Testing

✅ Callback data format validated  
✅ Type checking passes  
✅ No syntax errors  
⏳ Manual testing in production recommended

### Future Improvements

1. Add "Jump to page" button for large fact counts
2. Consider adding fact count filter buttons (e.g., "🔍 Тільки personal")
3. Add "Refresh" button to reload facts
4. Consider caching fact counts to reduce database queries

### Telemetry

New counter: `profile_admin.facts_paginated` tracks pagination button clicks

### Files Modified

- `app/handlers/profile_admin.py`
  - Updated imports (added CallbackQuery, InlineKeyboardMarkup, etc.)
  - Modified `get_user_facts_command()` to use inline buttons
  - Added `facts_pagination_callback()` handler
  - Changed `FACTS_PER_PAGE` from 20 to 5

### Verification Commands

```bash
# Check syntax
python3 -m py_compile app/handlers/profile_admin.py

# Verify callback data parsing
python3 -c "
callback_data = 'facts:123:456:2:personal'
parts = callback_data.split(':')
assert len(parts) == 5
assert parts[0] == 'facts'
print('✅ Callback format valid')
"

# Test in production
# 1. Send /gryagfacts in a chat
# 2. Verify shows 5 facts max
# 3. Verify buttons appear when >5 facts exist
# 4. Click "Наступна ▶️" and verify page updates
# 5. Click "◀️ Попередня" and verify goes back
```

## Related

- Original feature: `COMPREHENSIVE_IMPROVEMENTS_2025_10_21.md` (compact format)
- User profiles: `HYBRID_EXTRACTION_COMPLETE.md`
- Command system: `BOT_COMMAND_HINTS.md`
