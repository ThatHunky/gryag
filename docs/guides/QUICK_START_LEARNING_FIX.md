# Quick Start: Fixing Continuous Learning

**Problem**: Continuous fact extraction barely works  
**Solution**: 3 immediate configuration changes + optional code improvements

## Immediate Fix (5 minutes)

### 1. Apply Configuration Changes

The `.env` file has been updated with these changes:

```bash
# Changed from rule_based to hybrid (70% → 85% coverage)
FACT_EXTRACTION_METHOD=hybrid

# Enabled Gemini fallback for complex cases
ENABLE_GEMINI_FALLBACK=true

# Lowered threshold from 0.8 to 0.7 (more lenient)
FACT_CONFIDENCE_THRESHOLD=0.7

# Disabled filtering temporarily to see full impact
ENABLE_MESSAGE_FILTERING=false
```

### 2. Ensure Local Model is Downloaded

```bash
# Check if model exists
ls -lh models/phi-3-mini-q4.gguf

# If not found, download it (~2.2GB)
bash download_model.sh
```

### 3. Restart Bot

```bash
# Stop current instance (Ctrl+C)
# Restart with changes
python -m app.main
```

## Verify It's Working

### Option 1: Run Verification Script

```bash
./verify_learning.sh
```

Expected output:
- ✅ Local model found
- Shows recent facts extracted
- Shows fact quality metrics

### Option 2: Manual Testing

1. **Send test messages** in Telegram (to a chat with the bot):
   ```
   я з Києва
   я програміст
   я працюю з Python вже 5 років
   ```

2. **Wait 5 minutes** (for window to close and process)

3. **Check database**:
   ```bash
   sqlite3 gryag.db "
   SELECT fact_type, fact_value, confidence, 
          datetime(created_at, 'localtime') as created
   FROM user_facts 
   WHERE created_at > datetime('now', '-10 minutes')
   ORDER BY created_at DESC;
   "
   ```

4. **Check logs** (in separate terminal):
   ```bash
   python -m app.main 2>&1 | grep -E 'facts|window|extract' --color=always
   ```

Expected logs:
```
INFO - Conversation window closed: Timeout 300s exceeded
INFO - Extracted N facts from window
INFO - Quality processing: N → M facts
INFO - Stored M facts for user 12345
```

## What Was Changed

### Before
- **Extraction method**: `rule_based` only (regex patterns)
- **Coverage**: ~70% of facts
- **Confidence threshold**: 0.8 (very strict)
- **Message filtering**: Enabled (40-60% of messages filtered out)
- **Result**: Very few facts extracted

### After
- **Extraction method**: `hybrid` (regex + local LLM + Gemini fallback)
- **Coverage**: ~85% of facts
- **Confidence threshold**: 0.7 (default/recommended)
- **Message filtering**: Disabled (all messages processed)
- **Result**: 2-3x more facts extracted

## Troubleshooting

### Issue: "Local model not found"

```bash
# Download the model
bash download_model.sh

# Or use Gemini-only (slower, API costs)
# Set in .env:
FACT_EXTRACTION_METHOD=gemini
```

### Issue: "No facts being extracted"

Check logs:
```bash
python -m app.main 2>&1 | tee bot.log
```

Look for errors:
```bash
grep -i "error\|exception\|failed" bot.log | grep -i "fact"
```

Common issues:
- Local model file corrupted → re-download
- Gemini API key invalid → check `GEMINI_API_KEY` in `.env`
- Message filtering too aggressive → already disabled

### Issue: "Too many low-quality facts"

Re-enable filtering:
```bash
# In .env
ENABLE_MESSAGE_FILTERING=true
```

Increase threshold:
```bash
# In .env
FACT_CONFIDENCE_THRESHOLD=0.75
```

### Issue: "Bot is slow/high CPU"

The hybrid method uses a local model which needs CPU. Options:

1. **Reduce threads** (`.env`):
   ```bash
   LOCAL_MODEL_THREADS=1  # Was 2
   ```

2. **Use Gemini-only** (`.env`):
   ```bash
   FACT_EXTRACTION_METHOD=gemini
   ENABLE_GEMINI_FALLBACK=false
   ```

3. **Reduce window size** (`.env`):
   ```bash
   CONVERSATION_WINDOW_SIZE=3  # Was 5
   ```

## Next Steps

Once you verify facts are being extracted (check with `./verify_learning.sh`), consider:

1. **Re-enable message filtering** (if getting too many low-quality facts):
   ```bash
   ENABLE_MESSAGE_FILTERING=true
   ```

2. **Monitor for 1 week** to establish baseline metrics

3. **Implement dual-path extraction** (see `docs/plans/CONTINUOUS_LEARNING_IMPROVEMENTS.md` Phase 2)
   - Extract facts from addressed messages immediately (0s latency)
   - Keep window-based extraction for background learning

4. **Add observability dashboard** (Phase 4)
   - `/gryaglearning` command to view stats
   - Easier debugging and monitoring

## Documentation

- **Full improvement plan**: `docs/plans/CONTINUOUS_LEARNING_IMPROVEMENTS.md`
- **Phase 3 testing guide**: `docs/guides/PHASE_3_TESTING_GUIDE.md`
- **Architecture overview**: `.github/copilot-instructions.md`

## Support

If issues persist after these changes:

1. Run verification: `./verify_learning.sh`
2. Check logs: `python -m app.main 2>&1 | grep -i error`
3. Check database: `sqlite3 gryag.db "SELECT COUNT(*) FROM user_facts;"`
4. Review full plan: `docs/plans/CONTINUOUS_LEARNING_IMPROVEMENTS.md`
