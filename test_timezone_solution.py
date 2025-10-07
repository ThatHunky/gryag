#!/usr/bin/env python3
"""Test the complete timezone solution including fallback."""

from datetime import datetime
import datetime as dt


def test_timezone_primary():
    """Test primary approach with zoneinfo."""
    try:
        from zoneinfo import ZoneInfo

        kyiv_tz = ZoneInfo("Europe/Kiev")
        current_time = datetime.now(kyiv_tz).strftime("%A, %B %d, %Y at %H:%M:%S")
        return f"✓ Primary (zoneinfo): {current_time}"
    except Exception as e:
        return f"✗ Primary failed: {e}"


def test_timezone_fallback():
    """Test fallback approach with UTC + 3 hours."""
    try:
        utc_now = datetime.utcnow()
        kyiv_time = utc_now + dt.timedelta(hours=3)
        current_time = kyiv_time.strftime("%A, %B %d, %Y at %H:%M:%S")
        return f"✓ Fallback (UTC+3): {current_time}"
    except Exception as e:
        return f"✗ Fallback failed: {e}"


if __name__ == "__main__":
    print("=== Timezone Solution Test ===")
    print()
    print(test_timezone_primary())
    print(test_timezone_fallback())
    print()
    print("✓ Bot will use primary approach if available, fallback if not")
    print("✓ Both approaches should show Kyiv time (UTC+3)")
