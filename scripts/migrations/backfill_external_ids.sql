-- Backfill external ID columns from JSON metadata
-- Safe to run multiple times (idempotent)

-- Backfill external_message_id from media.meta.message_id
UPDATE messages 
SET external_message_id = json_extract(media, '$.meta.message_id')
WHERE external_message_id IS NULL 
  AND json_extract(media, '$.meta.message_id') IS NOT NULL;

-- Backfill external_user_id from media.meta.user_id
UPDATE messages 
SET external_user_id = json_extract(media, '$.meta.user_id')
WHERE external_user_id IS NULL 
  AND json_extract(media, '$.meta.user_id') IS NOT NULL;

-- Backfill reply_to_external_message_id
UPDATE messages 
SET reply_to_external_message_id = json_extract(media, '$.meta.reply_to_message_id')
WHERE reply_to_external_message_id IS NULL 
  AND json_extract(media, '$.meta.reply_to_message_id') IS NOT NULL;

-- Backfill reply_to_external_user_id
UPDATE messages 
SET reply_to_external_user_id = json_extract(media, '$.meta.reply_to_user_id')
WHERE reply_to_external_user_id IS NULL 
  AND json_extract(media, '$.meta.reply_to_user_id') IS NOT NULL;

-- Verify counts after backfill
SELECT 
  COUNT(*) AS total,
  SUM(CASE WHEN external_message_id IS NOT NULL THEN 1 ELSE 0 END) AS filled_ext_msg,
  SUM(CASE WHEN external_user_id IS NOT NULL THEN 1 ELSE 0 END) AS filled_ext_user
FROM messages;

