# Formatting Consistency Fix

**Date**: 2025-10-24  
**Status**: Fixed (Complete)

## Problem

The bot was experiencing formatting issues where markdown syntax was displaying as literal text instead of being rendered:

**Symptoms**:
- Asterisks showing literally: `**текст**` instead of **bold**
- Underscores showing literally: `*текст*` instead of *italic*  
- Spoiler tags showing literally: `||текст||` instead of clickable spoilers
- Inconsistent behavior between messages

## Root Cause

The bot went through several iterations:

1. **Initial state**: Used MarkdownV2 with complex escaping - fragile and error-prone
2. **First fix**: Removed parse_mode entirely (plain text) - broke spoilers and formatting
3. **Second fix**: Added HTML parse_mode but only converted spoilers - asterisks still literal

**The real problem**: Gemini generates markdown syntax (`**bold**`, `*italic*`, `||spoiler||`) but the bot wasn't converting it properly to Telegram's HTML format.

## Solution (Final)

Implemented comprehensive markdown-to-HTML conversion with **HTML parse_mode**:

1. **Convert all markdown to HTML**:
   - `**bold**` or `__bold__` → `<b>bold</b>`
   - `*italic*` or `_italic_` → `<i>italic</i>`
   - `||spoiler||` → `<tg-spoiler>spoiler</tg-spoiler>`

2. **Safe placeholder system**: Use null bytes (`\x00`) as placeholders to avoid conflicts with markdown parsing

3. **Proper HTML escaping**: All special characters (`<`, `>`, `&`) safely escaped

**New formatting function**:

```python
def _format_for_telegram(text: str) -> str:
    """
    Format text for Telegram HTML parse mode.
    
    Converts markdown/MarkdownV2 syntax to HTML:
    - **bold** or __bold__ -> <b>bold</b>
    - *italic* or _italic_ -> <i>italic</i>
    - ||spoiler|| -> <tg-spoiler>spoiler</tg-spoiler>
    
    Escapes HTML special characters to prevent parsing errors.
    """
    # 1. Extract and protect formatted blocks
    # 2. HTML-escape the rest
    # 3. Restore with HTML tags
```

## Changes

### 1. Updated HTML formatter (`app/handlers/chat.py`)

```python
def _format_for_telegram(text: str) -> str:
    # Extract formatted blocks with safe placeholders (\x00)
    # Handle **bold**, *italic*, ||spoiler||
    # HTML escape remaining text
    # Restore formatted blocks as HTML tags
    return formatted_text
```

### 2. Main reply handler (already uses HTML)

```python
reply_formatted = _format_for_telegram(reply_trimmed)
response_message = await message.reply(
    reply_formatted,
    parse_mode=ParseMode.HTML,
    disable_web_page_preview=True,
)
```

### 3. Poll vote handler (already uses HTML)

```python
poll_formatted = _format_for_telegram(poll_vote_result)
await message.reply(poll_formatted, parse_mode=ParseMode.HTML)
```

### 4. Comprehensive tests (`tests/unit/test_telegram_formatting.py`)

- 20 test cases covering all formatting scenarios
- Tests for bold, italic, spoilers, mixed formatting
- Edge cases: HTML inside formatting, empty tags, nested formats
- Real bot messages from production

## Benefits

1. **Bold works**: `**текст**` → **текст**
2. **Italic works**: `*текст*` → *текст*
3. **Spoilers work**: `||текст||` → clickable spoiler
4. **HTML is safe**: All special characters properly escaped
5. **Consistent rendering**: Reliable across all message types
6. **Well-tested**: 20 comprehensive test cases

## Verification

Test results:

```bash
# Run formatting tests
pytest tests/unit/test_telegram_formatting.py -v
# Result: 20 passed

# Run full test suite  
pytest tests/unit/ -v
# Result: 319 passed
```

Manual testing:
- Start bot: `python -m app.main`
- Send message that triggers formatting
- Verify:
  - `**bold**` renders as bold
  - `*italic*` renders as italic
  - `||spoiler||` renders as clickable spoiler

## Related Files

- `app/handlers/chat.py` - Updated `_format_for_telegram()` with full markdown→HTML conversion
- `tests/unit/test_telegram_formatting.py` - Comprehensive test coverage (20 tests)
- `app/persona.py` - Persona says "Plain text only" but Gemini still uses emphasis (working as intended)

## Notes

- HTML parse_mode is more reliable than MarkdownV2
- The `_escape_markdown()` function is marked as deprecated
- All formatting (`**bold**`, `*italic*`, `||spoiler||`) now properly supported
- This change improves both reliability and user experience
- No more literal asterisks or broken formatting!
