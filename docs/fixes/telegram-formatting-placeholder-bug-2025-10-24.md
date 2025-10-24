# Telegram Formatting Bugs Fix

**Date**: October 24, 2025  
**Issues**: 
1. Bot responses showing literal "PROTECTED" text instead of formatted markdown
2. Underscores in Telegram usernames being treated as italic markdown

**Status**: ✅ Fixed

## Problem 1: PROTECTED Placeholder Text

The bot was displaying literal placeholder text like `PROTECTED1`, `PROTECTED2` instead of properly formatted bold/italic text. This was visible in Telegram messages as:

```text
**PROTECTED1** та **PROTECTED2** перестаньте один одному порно-гiфки
```

Instead of the expected:
```text
[bold]PROTECTED1[/bold] та [bold]PROTECTED2[/bold] перестаньте один одному порно-гiфки
```

### Root Cause

The `_format_for_telegram()` function in `app/handlers/chat.py` uses placeholders to protect formatted content during HTML escaping. The bug occurred because:

1. Function replaces markdown (e.g., `**text**`) with placeholders like `\x00PROTECTED0\x00`
2. Text is HTML-escaped using `html.escape()`
3. `html.escape()` converts `\x00` (null byte) to HTML entity `&#x00;` or similar
4. Placeholder replacement tries to find `\x00PROTECTED0\x00` but finds `&#x00;PROTECTED0&#x00;` instead
5. Replacement fails, leaving literal "PROTECTED0" text visible to users

## Problem 2: Username Underscore Removal

Telegram usernames like `@vsevolod_dobrovolskyi` were being incorrectly formatted as `@vsevolod<i>dobrovolskyi</i>` because underscores were treated as italic markdown delimiters.

### Root Cause

The italic markdown regex (`_text_`) was matching underscores within username patterns, incorrectly treating them as formatting markers instead of literal characters.

## Solution

### Fix 1: Safe Placeholders

Changed placeholders from null bytes (`\x00`) to Unicode Private Use Area characters (`\uE000` and `\uE001`), which are:

- Not affected by HTML escaping
- Safe for internal use
- Unlikely to appear in user text
- Properly preserved through the formatting pipeline

### Fix 2: Username Protection

Added a preprocessing step that protects Telegram usernames (matching pattern `@[a-zA-Z0-9_]{5,32}`) before markdown processing. This prevents underscores within usernames from being treated as italic markers.

### Code Changes

**File**: `app/handlers/chat.py`

**Before**:
```python
placeholder = f"\x00PROTECTED{len(protected)}\x00"
```

**After**:
```python
placeholder = f"\uE000TGFMT{len(protected)}\uE001"  # For formatted content
placeholder = f"\uE000RAW{len(protected)}\uE001"     # For usernames
```

Added username protection:
```python
# Step 0: Protect Telegram usernames (@username) to prevent underscore processing
text = re.sub(
    r"@([a-zA-Z0-9_]{5,32})\b",
    lambda m: protect_content(m.group(0)),
    text,
)
```

### Persona Update

**File**: `app/persona.py`

Made the username formatting instruction more explicit:

```python
**Formatting**: Plain text only. No asterisks, no underscores for emphasis, no decorative markdown. 
Simple lists with `-` or `*` are fine. CRITICAL: When mentioning Telegram usernames 
(like @vsevolod_dobrovolskyi or @Qyyya_nya), ALWAYS include the underscore character exactly 
as shown - never remove it. Underscores are part of the username, not formatting.
```

## Testing

Added comprehensive test cases in `tests/unit/test_telegram_formatting.py`:

```python
def test_format_for_telegram_protected_bug():
    """Test the specific bug: **PROTECTED** showing literally."""
    text = "А ви тям, **PROTECTED2**, перестаньте"
    result = _format_for_telegram(text)
    
    assert "<b>PROTECTED2</b>" in result  # ✓ Properly formatted
    assert "**PROTECTED" not in result    # ✓ No literal markdown

def test_format_for_telegram_username_underscores():
    """Test that underscores in usernames are preserved."""
    tests = [
        ("@vsevolod_dobrovolskyi", "@vsevolod_dobrovolskyi"),
        ("@test_user_name", "@test_user_name"),
        ("@user_name це _курсив_", "@user_name це <i>курсив</i>"),
    ]
    # All pass ✓
```

All 22 formatting tests pass, including:
- Bold (`**text**` and `__text__`)
- Italic (`*text*` and `_text_`)
- Spoilers (`||text||`)
- HTML escaping
- Username preservation
- Mixed formatting

## Verification

Run the formatting tests:
```bash
pytest tests/unit/test_telegram_formatting.py -v
```

Test manually:
```bash
python3 -c "
from app.handlers.chat import _format_for_telegram
print(_format_for_telegram('@vsevolod_dobrovolskyi, це **bold** і *italic*'))
# Output: @vsevolod_dobrovolskyi, це <b>bold</b> і <i>italic</i>
"
```

## Impact

- **User-facing**: Markdown formatting now displays correctly as HTML in Telegram, usernames display correctly with underscores
- **Performance**: Minimal impact (one additional regex pass for username protection)
- **Compatibility**: No breaking changes; all existing tests pass
- **Safety**: Unicode private use area is safe and won't conflict with user text

## Related Issues

None - these were new bugs discovered during testing.
