#!/usr/bin/env python3
"""Check for specific messages from the screenshot."""

import sqlite3
from datetime import datetime

conn = sqlite3.connect("gryag.db")
cursor = conn.cursor()

# Look for messages around 10:10 (which is 13:10 local time based on the last check)
cursor.execute(
    """
    SELECT chat_id, user_id, role, text,
           datetime(ts, 'unixepoch', 'localtime') as time
    FROM messages 
    WHERE ts >= 1728381000 AND ts <= 1728382000
    ORDER BY ts ASC
"""
)

print("Messages from 10:10-10:33 timeframe:")
print("-" * 120)
count = 0
for row in cursor.fetchall():
    chat_id, user_id, role, text, time = row
    text_preview = text[:80] if text else "[no text]"
    print(f"{time} | User:{user_id} | {role:5s} | {text_preview}")
    count += 1

print(f"\nTotal messages in this timeframe: {count}")

# Also check for bot messages specifically
cursor.execute(
    """
    SELECT COUNT(*) 
    FROM messages 
    WHERE role = 'model'
"""
)
bot_message_count = cursor.fetchone()[0]
print(f"\nTotal bot (model) messages in DB: {bot_message_count}")

# Check for user messages
cursor.execute(
    """
    SELECT COUNT(*) 
    FROM messages 
    WHERE role = 'user'
"""
)
user_message_count = cursor.fetchone()[0]
print(f"Total user messages in DB: {user_message_count}")

conn.close()
