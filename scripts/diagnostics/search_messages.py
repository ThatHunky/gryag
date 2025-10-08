#!/usr/bin/env python3
"""Search for messages containing specific text from the screenshot."""

import sqlite3

conn = sqlite3.connect("gryag.db")
cursor = conn.cursor()

# Search for the "правила чату" message
search_terms = [
    "правила чату",
    "кавунову пітсу",
    "Ще навіть зробіть",
    "Vsevalod Dobrovol",
]

for term in search_terms:
    print(f'\nSearching for: "{term}"')
    print("-" * 100)
    cursor.execute(
        """
        SELECT chat_id, user_id, role, text,
               datetime(ts, 'unixepoch', 'localtime') as time
        FROM messages 
        WHERE text LIKE ?
        ORDER BY ts DESC
        LIMIT 5
    """,
        (f"%{term}%",),
    )

    results = cursor.fetchall()
    if results:
        for row in results:
            chat_id, user_id, role, text, time = row
            text_preview = text[:100] if text else "[no text]"
            print(f"{time} | User:{user_id} | {role:5s} | {text_preview}")
    else:
        print("No results found")

conn.close()
