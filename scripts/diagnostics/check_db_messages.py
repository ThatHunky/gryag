#!/usr/bin/env python3
"""Check if messages are being saved to the database."""

import sqlite3
from datetime import datetime

conn = sqlite3.connect("gryag.db")
cursor = conn.cursor()

# Total messages
cursor.execute("SELECT COUNT(*) as total, MAX(ts) as last_ts FROM messages")
result = cursor.fetchone()
total_messages = result[0]
last_ts = result[1]

print(f"Total messages in DB: {total_messages}")
if last_ts:
    last_time = datetime.fromtimestamp(last_ts)
    print(f"Last message timestamp: {last_time}")
else:
    print("No messages found")

# Recent messages
cursor.execute(
    """
    SELECT chat_id, user_id, role, 
           CASE WHEN length(text) > 60 THEN substr(text, 1, 60) || '...' ELSE text END as text_preview,
           datetime(ts, 'unixepoch', 'localtime') as time
    FROM messages 
    ORDER BY ts DESC 
    LIMIT 10
"""
)

print("\nRecent 10 messages:")
print("-" * 100)
for row in cursor.fetchall():
    chat_id, user_id, role, text_preview, time = row
    print(f"{time} | Chat:{chat_id} | User:{user_id} | {role:5s} | {text_preview}")

conn.close()
