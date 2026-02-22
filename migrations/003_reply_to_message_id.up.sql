-- Store Telegram message_id of the message being replied to (for reply/quote context).
ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_message_id BIGINT;
