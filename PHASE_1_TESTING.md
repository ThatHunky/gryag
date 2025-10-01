# Phase 1 Testing Guide

Quick guide to verify Phase 1 implementation is working correctly.

## 🚀 Quick Start

### 1. Update Dependencies (if needed)

```bash
pip install -r requirements.txt
```

### 2. Check Configuration

Your `.env` file should have (defaults are safe):

```bash
# Continuous monitoring enabled but not filtering
ENABLE_CONTINUOUS_MONITORING=true
ENABLE_MESSAGE_FILTERING=false
ENABLE_ASYNC_PROCESSING=false
```

### 3. Start Bot

```bash
python -m app.main
```

Expected startup log:
```
INFO - ContinuousMonitor initialized
  enable_monitoring: True
  enable_filtering: False
  enable_async_processing: False
INFO - Continuous monitoring initialized
  enabled: True
  filtering: False
  async_processing: False
```

## ✅ Test Scenarios

### Test 1: Noise Classification

Send in chat:
1. A sticker
2. Just emojis: "😂😂😂"
3. A photo without caption

**Expected**: 
- DEBUG logs show classification as "noise"
- Bot behavior unchanged (ignores these)

### Test 2: Low-Value Messages

Send in chat:
1. "привіт"
2. "ok"
3. "ок"

**Expected**:
- DEBUG logs show classification as "low"
- Bot behavior unchanged

### Test 3: Medium-Value Messages

Send in chat:
1. "що нового?"
2. "ну давай"

**Expected**:
- DEBUG logs show classification as "medium"
- Still ignored (not addressed)

### Test 4: High-Value Messages

Send in chat:
1. "Що ти думаєш про це?"
2. Any 10+ word message

**Expected**:
- DEBUG logs show classification as "high"
- Still ignored (not addressed)

### Test 5: Addressed Messages

Send in chat:
1. "@gryag привіт"
2. Reply to bot's message

**Expected**:
- DEBUG logs show classification as "high" (addressed = always high)
- Bot responds normally (behavior unchanged)

### Test 6: Conversation Windows

Send 8-10 messages quickly in chat:

**Expected**:
```
DEBUG - Created new conversation window for chat=...
...
INFO - Conversation window closed: Max size 8 reached
  message_count: 8
  participant_count: X
  dominant_value: medium/high/low
INFO - Window would be processed (async processing disabled)
```

### Test 7: Window Timeout

Send a message, wait 4 minutes, send another:

**Expected**:
```
INFO - Conversation window closed: Timeout 180s exceeded
```

## 🐛 Troubleshooting

### "No logs appearing"

Set debug logging in `.env`:
```bash
LOGLEVEL=DEBUG
```

### "Module not found: monitoring"

Restart the bot - lazy imports may not have loaded yet.

### "Circuit breaker errors"

This is normal if something fails. Circuit will auto-recover after 60s.

### "Bot behavior changed"

Phase 1 should cause **zero** behavior changes. If you see different responses or filtering, check:
```bash
ENABLE_MESSAGE_FILTERING=false
ENABLE_ASYNC_PROCESSING=false
```

## 📊 Check Statistics

You can check stats programmatically (in Python REPL):

```python
from app.main import ...
# Access continuous_monitor.get_stats()
```

Or add a debug handler in `app/handlers/admin.py`:

```python
@router.message(Command("stats"))
async def show_stats(message: Message, continuous_monitor: Any):
    if continuous_monitor:
        stats = continuous_monitor.get_stats()
        await message.reply(f"<pre>{json.dumps(stats, indent=2)}</pre>")
```

## ✅ Success Criteria

Phase 1 is working correctly if:

1. ✅ Bot starts without errors
2. ✅ Classification logs appear for all messages
3. ✅ Conversation windows are created and closed
4. ✅ **Bot behavior is exactly the same** as before
5. ✅ No filtering is happening
6. ✅ No new fact extraction is happening

## 🎯 What's NOT Working Yet (Expected)

- ❌ Message filtering (Phase 3)
- ❌ Async event processing (Phase 3)
- ❌ Window-based fact extraction (Phase 3)
- ❌ Fact deduplication (Phase 2)
- ❌ Proactive responses (Phase 4)

These are all **stubs** or **disabled** in Phase 1.

## 📞 Support

If you encounter issues:

1. Check logs with `LOGLEVEL=DEBUG`
2. Verify configuration in `.env`
3. Ensure all files were created correctly
4. Review `PHASE_1_COMPLETE.md` for details

## 🚦 Next Steps

Once Phase 1 is verified:
1. Observe logs for a few days
2. Tune window size/timeout if needed
3. Proceed to Phase 2: Fact Quality Management

---

**Happy Testing! 🎉**
