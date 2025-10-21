# Image Quota Increase to 3/day

**Date**: October 19, 2025  
**Status**: Implemented  
**Related**: Image generation feature

## Problem

The original daily limit of 1 image per user per day was too restrictive:
- Users couldn't experiment with different prompts
- No room for iteration (generate → see result → refine)
- Single failed generation meant no more attempts that day
- Poor user experience for a creative feature

## Solution

**Increased daily quota from 1 to 3 images per user per day** while ensuring failed generations don't consume quota.

### Changes Made

1. **Updated default limit** in `app/config.py`:
   - Changed `IMAGE_GENERATION_DAILY_LIMIT` from 1 to 3
   - Comment: "Images per user per day (admins unlimited)"

2. **Updated service initialization** in `app/services/image_generation.py`:
   - Changed `__init__` default parameter from 1 to 3
   - Updated docstring

3. **Updated configuration example** in `.env.example`:
   - Changed from 1 to 3
   - Added comment: "Quota only consumed on successful generation (failures don't count)"

4. **Updated documentation** in `docs/features/IMAGE_GENERATION.md`:
   - Updated configuration section
   - Added "Quota behavior" explanation
   - Emphasized that failures don't count against limit

## Quota Consumption Logic (Already Correct)

The code was already correctly handling quota:

```python
# 1. Check quota BEFORE generation
has_quota, used, limit = await self.check_quota(user_id, chat_id)
if not has_quota:
    raise QuotaExceededError(...)

# 2. Try to generate image
response = await self.client.aio.models.generate_content(...)

# 3. Extract image bytes
image_bytes = part.inline_data.data

# 4. Check if extraction succeeded
if not image_bytes:
    raise ImageGenerationError(...)  # ← Quota NOT incremented

# 5. ONLY if successful, increment quota
await self.increment_quota(user_id, chat_id)  # ← Only reached if no errors
```

**Failures that DON'T consume quota:**
- API errors (timeout, rate limit, connection issues)
- Safety blocks (content policy violations)
- Empty response (no image returned)
- Parsing failures (malformed response)
- Any exception during generation

**Only successful generations consume quota** ✅

## Cost Impact

### Per User:
- **Before**: 1 image/day × $0.04 = **$0.04/day max**
- **After**: 3 images/day × $0.04 = **$0.12/day max**
- **Increase**: +$0.08/day per user (+200%)

### For 100 Active Users:
- **Before**: $0.04 × 100 = $4/day = **$120/month**
- **After**: $0.12 × 100 = $12/day = **$360/month**
- **Increase**: +$8/day = **+$240/month**

### Cost Control:
- Admins still have unlimited access (no change)
- Can adjust `IMAGE_GENERATION_DAILY_LIMIT` in `.env` (1-10 range)
- Failed attempts don't waste money (not charged by API)
- Quota resets daily at midnight UTC

## User Experience Improvements

### Before (1/day):
```
User: "намалюй кота"
Bot: *generates image*
User: "можеш зробити більш реалістичним?"
Bot: "Перевищено денний ліміт (1/1 зображень). Спробуй завтра!"
User: 😞
```

### After (3/day):
```
User: "намалюй кота"
Bot: *generates image* "Залишилось сьогодні: 2/3"
User: "можеш зробити більш реалістичним?"
Bot: *generates better image* "Залишилось сьогодні: 1/3"
User: "супер! можна ще в стилі ван гога?"
Bot: *generates artistic version* "Залишилось сьогодні: 0/3"
User: 😊
```

### Failure Handling:
```
User: "намалюй щось неприйнятне"
Bot: "Запит відхилено через політику безпеки"
*Quota NOT decremented - user can try again*
User: "намалюй кота"
Bot: *generates image* "Залишилось сьогодні: 2/3"
```

## Configuration

In `.env`:
```bash
IMAGE_GENERATION_DAILY_LIMIT=3  # Default, can be 1-10
```

To adjust for different use cases:
- **Conservative** (low cost): `IMAGE_GENERATION_DAILY_LIMIT=1`
- **Balanced** (default): `IMAGE_GENERATION_DAILY_LIMIT=3`
- **Generous** (high engagement): `IMAGE_GENERATION_DAILY_LIMIT=5`
- **Very generous**: `IMAGE_GENERATION_DAILY_LIMIT=10` (max)

## Files Changed

- `app/config.py` — default from 1 to 3
- `app/services/image_generation.py` — `__init__` default from 1 to 3
- `.env.example` — updated to 3, added failure handling comment
- `docs/features/IMAGE_GENERATION.md` — updated configuration, added quota behavior section
- `docs/README.md` — added recent changes entry
- `docs/CHANGELOG.md` — added entry
- `docs/fixes/IMAGE_QUOTA_INCREASE.md` — this document

## Verification

### Check Configuration:
```bash
# Config file
grep "IMAGE_GENERATION_DAILY_LIMIT" app/config.py
# Should show: 3, alias="IMAGE_GENERATION_DAILY_LIMIT", ge=1, le=10

# Service default
grep "daily_limit: int = " app/services/image_generation.py
# Should show: daily_limit: int = 3

# Environment example
grep "IMAGE_GENERATION_DAILY_LIMIT" .env.example
# Should show: IMAGE_GENERATION_DAILY_LIMIT=3
```

### Test Quota:
1. Enable image generation: `ENABLE_IMAGE_GENERATION=true`
2. Generate 3 images in chat
3. Try 4th image → should get quota exceeded message
4. Check database:
```sql
SELECT * FROM image_quotas WHERE generation_date = date('now');
-- Should show images_generated = 3
```

### Test Failure Handling:
1. Request inappropriate image (will be safety blocked)
2. Check quota → should NOT increment
3. Request normal image → should work and increment quota

## Benefits

1. **Better UX**: Users can iterate and refine their images
2. **More engagement**: Creative feature becomes actually useful
3. **Failure resilience**: Technical issues don't waste quota
4. **Still cost-controlled**: 3x increase is manageable for small-medium bots
5. **Configurable**: Can adjust limit based on usage patterns

## Monitoring

Track actual usage to optimize limit:
```sql
-- Average images per user per day
SELECT AVG(images_generated) as avg_daily
FROM image_quotas
WHERE generation_date >= date('now', '-7 days');

-- Users hitting the limit
SELECT COUNT(DISTINCT user_id) as users_at_limit
FROM image_quotas
WHERE images_generated >= 3
AND generation_date = date('now');

-- Total cost estimation
SELECT 
  SUM(images_generated) as total_images,
  SUM(images_generated) * 0.04 as total_cost_usd
FROM image_quotas
WHERE generation_date >= date('now', '-30 days');
```

## Future Improvements

- [ ] Add per-chat quota (in addition to per-user)
- [ ] Implement weekly/monthly quotas for power users
- [ ] Add premium tier with higher limits
- [ ] Track and optimize for cost per active user
- [ ] Consider dynamic limits based on API costs
