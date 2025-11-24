# Broadcast Command - Quick Usage Guide

## How to Use

1. **Send or find** the message you want to broadcast (text, image, video, document, etc.)
2. **Reply** to that message with `/broadcast`
3. **Confirm** by sending `/broadcast confirm` or replying "так"
4. **Wait** for the broadcast to complete

## Examples

### Text Broadcast
```
Admin: Important announcement! 📢
Admin: /broadcast ← (reply)
Bot: [Confirmation prompt]
Admin: /broadcast confirm
Bot: ✅ Sent to 42/45 chats
```

### Image Broadcast
```
Admin: [Sends photo with caption]
Admin: /broadcast ← (reply)
Bot: [Shows "фото" in confirmation]
Admin: так ← (reply to bot)
Bot: ✅ Broadcast complete
```

## Requirements

- Must be an admin (in `ADMIN_USER_IDS`)
- Must use in private chat with bot
- Must reply to the message you want to broadcast

## Confirmation Options

- `/broadcast confirm`
- `/broadcast yes`  
- Reply "так" to the confirmation message

## What Gets Broadcast

The **exact message** you replied to, including:
- Text formatting (bold, italic, links)
- Media (photos, videos, documents)
- Captions
- Stickers, GIFs, voice messages

## Rate Limiting

- ~5 messages per second (conservative)
- Progress logged every 10 chats
- Failed sends are tracked and reported
