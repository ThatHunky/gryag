# Quick Start: Phase 2 Testing Guide

## Prerequisites
- Phase 1 complete (admin commands working)
- Bot running with hybrid extraction enabled
- At least one test user with accumulated facts

## Step 1: Install Dependencies

```bash
# Install APScheduler
pip install -r requirements.txt

# Or manually:
pip install apscheduler>=3.10
```

## Step 2: Configure Environment

Add to your `.env` file:

```bash
# Enable profile summarization
ENABLE_PROFILE_SUMMARIZATION=true

# Run at 3 AM (low traffic) or current hour for immediate testing
PROFILE_SUMMARIZATION_HOUR=3

# Conservative settings for i5-6500
PROFILE_SUMMARIZATION_BATCH_SIZE=30
MAX_PROFILES_PER_DAY=50
```

## Step 3: Verify Database Schema

The `summary_updated_at` column will be added automatically on first run.

To verify manually:
```bash
sqlite3 gryag.db "PRAGMA table_info(user_profiles);"
```

Should show `summary_updated_at` column.

## Step 4: Start Bot

```bash
# Start bot (will initialize scheduler)
python -m app.main
```

Look for log message:
```
INFO - Profile summarization scheduler started (runs at 03:00)
```

## Step 5: Test Manual Summarization

### Option A: Python REPL
```python
import asyncio
from app.services.profile_summarization import ProfileSummarizer
from app.services.user_profile import UserProfileStore
from app.services.gemini import GeminiClient
from app.config import get_settings

async def test():
    settings = get_settings()
    profile_store = UserProfileStore(settings.db_path)
    await profile_store.init()
    
    gemini = GeminiClient(
        settings.gemini_api_key,
        settings.gemini_model,
        settings.gemini_embed_model
    )
    
    summarizer = ProfileSummarizer(settings, profile_store, gemini)
    
    # Replace with your Telegram user ID
    summary = await summarizer.summarize_now(user_id=YOUR_USER_ID)
    print(f"Summary: {summary}")

asyncio.run(test())
```

### Option B: Add Admin Command (Quick Hack)

Add to `app/handlers/profile_admin.py`:

```python
@router.message(Command("gryagsummarize"))
async def cmd_summarize(message: Message, profile_store: UserProfileStore) -> None:
    """[Admin] Manually trigger profile summarization for a user."""
    if not await _is_admin(message):
        return
    
    target_user = await _resolve_target_user(message)
    if not target_user:
        await message.reply("Reply to a message or use /gryagsummarize @username")
        return
    
    # Import here to avoid circular dependency
    from app.services.profile_summarization import ProfileSummarizer
    from app.config import get_settings
    
    settings = get_settings()
    # Access gemini_client from middleware data
    gemini_client = message.bot.get("gemini_client")  # Passed via middleware
    
    summarizer = ProfileSummarizer(settings, profile_store, gemini_client)
    summary = await summarizer.summarize_now(target_user.id)
    
    if summary:
        await message.reply(f"✅ Summary generated ({len(summary)} chars):\n\n{summary[:500]}...")
    else:
        await message.reply("❌ Failed to generate summary")
```

## Step 6: Verify Results

### Check Profile Summary
```
/gryagprofile
```

Output should include:
```
📊 Профіль користувача

...existing stats...

📝 Резюме:
[Generated summary text here]
```

### Check Database
```bash
sqlite3 gryag.db "SELECT user_id, summary, summary_updated_at FROM user_profiles WHERE summary IS NOT NULL;"
```

### Check Telemetry
```python
from app.services.telemetry import telemetry

print(telemetry.snapshot())
# Should show:
# {'summaries_generated': 1, 'summarization_time_ms': 245, ...}
```

## Step 7: Wait for Scheduled Run

If `PROFILE_SUMMARIZATION_HOUR` is set to future hour:

1. Let bot run continuously
2. Check logs at scheduled time
3. Look for:
   ```
   INFO - Starting profile summarization task
   INFO - Found N profiles needing summarization
   INFO - Summarized profile for user 123456: 15 facts, 245ms
   INFO - Profile summarization complete: N success, 0 failed, Xms elapsed
   ```

## Expected Performance (i5-6500)

- **Latency**: 150-300ms per profile
- **Memory**: 6-8GB peak (8GB headroom)
- **CPU**: 4 cores, ~12.5s total for 50 profiles
- **Daily limit**: 50 profiles (configurable)

## Troubleshooting

### "Profile summarization disabled in config"
- Set `ENABLE_PROFILE_SUMMARIZATION=true` in .env
- Restart bot

### "No profiles need summarization"
- Ensure profiles have facts: `/gryagfacts`
- Create test facts by chatting with bot
- Check `user_profiles` table has entries

### "Import apscheduler could not be resolved"
- Run: `pip install apscheduler>=3.10`
- Or rebuild Docker: `docker-compose build bot`

### High memory usage
- Reduce `PROFILE_SUMMARIZATION_BATCH_SIZE` from 30 to 20
- Reduce `MAX_PROFILES_PER_DAY` from 50 to 30

### Slow summarization (>500ms per profile)
- Check Gemini API latency (network issue?)
- Verify not competing with other processes
- Consider running at different hour

## Success Indicators

✅ **Phase 2 is working when:**
1. Bot starts without errors
2. Scheduler logs "Profile summarization scheduler started"
3. Manual `summarize_now()` generates summary
4. `/gryagprofile` shows summary field
5. Database has `summary_updated_at` values
6. Telemetry shows `summaries_generated` > 0

## Next Steps

After verifying Phase 2 works:
- Enable for production: `ENABLE_PROFILE_SUMMARIZATION=true`
- Set optimal hour: `PROFILE_SUMMARIZATION_HOUR=3` (3 AM)
- Monitor daily runs via logs
- Track telemetry for performance trends

For Phase 3 (Optimization):
- See `NEXT_STEPS_PLAN_I5_6500.md`
- Add memory monitoring
- Implement lazy model loading
- Add graceful degradation
