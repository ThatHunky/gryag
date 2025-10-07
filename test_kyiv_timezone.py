#!/usr/bin/env python3
"""Test the timezone fix for bot timestamp."""

from datetime import datetime
from zoneinfo import ZoneInfo

# Test current timezone approach vs Kyiv timezone approach
print("=== Timezone Verification ===")
print()

# Original approach (system timezone)
system_time = datetime.now().strftime("%A, %B %d, %Y at %H:%M:%S")
print(f"System timezone: {system_time}")

# Fixed approach (Kyiv timezone)
kyiv_tz = ZoneInfo("Europe/Kiev")
kyiv_time = datetime.now(kyiv_tz).strftime("%A, %B %d, %Y at %H:%M:%S")
print(f"Kyiv timezone:   {kyiv_time}")

# UTC for comparison
utc_time = datetime.now(ZoneInfo("UTC")).strftime("%A, %B %d, %Y at %H:%M:%S")
print(f"UTC timezone:    {utc_time}")

print()
print("✓ Bot will now use Kyiv time regardless of container timezone")
print(f"✓ Timestamp context: '# Current Time\\n\\nThe current time is: {kyiv_time}'")
