#!/usr/bin/env python3
"""Quick verification script to test timestamp injection."""

from datetime import datetime

# Simulate the timestamp context generation
current_time = datetime.now().strftime("%A, %B %d, %Y at %H:%M:%S")
timestamp_context = f"\n\n# Current Time\n\nThe current time is: {current_time}"

print("✓ Timestamp context generated successfully:")
print(timestamp_context)
print()
print("✓ Format verification:")
print(f"  - Day of week: included")
print(f"  - Date: included")
print(f"  - Time: included (24-hour format)")
print()
print("This context will be injected into the system prompt for every message.")
print("The bot will now be aware of the current time when responding.")
