#!/usr/bin/env python3
"""
Verification script for command throttle middleware fix.

This script verifies that the CommandThrottleMiddleware correctly handles
commands addressed to different bots and only throttles commands that are
registered to gryag.

Bug fix: The bot was throttling ALL commands (including those for other bots),
which caused it to send throttle messages to users even when they were using
commands for a different bot.

Expected behavior:
- /gryag -> throttle (gryag's command)
- /gryagban -> throttle (gryag's command)
- /dban -> pass through (unknown command, likely for another bot)
- /start -> pass through (not a gryag command)
- /gryag@this_bot -> throttle (command for this bot)
- /gryag@other_bot -> pass through (command for different bot)
"""



# All commands registered to gryag
KNOWN_COMMANDS = {
    "gryag",
    "gryagban",
    "gryagunban",
    "gryagreset",
    "gryagchatinfo",
    "gryagprofile",
    "gryagfacts",
    "gryagremovefact",
    "gryagforget",
    "gryagexport",
    "gryagusers",
    "gryagself",
    "gryaginsights",
    "gryagchatfacts",
    "gryagchatreset",
    "gryagprompt",
    "gryagsetprompt",
    "gryagresetprompt",
    "gryagprompthistory",
    "gryagactivateprompt",
}


def is_command_for_this_bot(command_text: str, bot_username: str) -> bool:
    """
    Check if a command is addressed to this bot or should be throttled.

    Args:
        command_text: The message text (e.g., "/start@bot_name")
        bot_username: This bot's username (e.g., "gryag_bot")

    Returns:
        True if command should be throttled, False if it's for another bot or unknown
    """
    if not command_text.startswith("/"):
        return False

    # Extract command name (without @ mention if present)
    command_with_args = (
        command_text.split()[0] if command_text.split() else command_text
    )
    command_base = command_with_args.split("@")[0].lstrip("/").lower()

    # Check if this command belongs to this bot
    if command_base not in KNOWN_COMMANDS:
        return False

    # Check if command has bot mention
    if "@" in command_with_args:
        # Extract the bot mention from the command
        command_parts = command_with_args.split("@", 1)
        if len(command_parts) == 2:
            mentioned_bot = command_parts[1]
            # If command is for a different bot, don't throttle
            if mentioned_bot.lower() != bot_username.lower():
                return False

    # It's a known command for this bot (or generic)
    return True


def test_command_throttling():
    """Test various command scenarios."""
    bot_username = "gryag_bot"

    test_cases = [
        # (command_text, should_throttle, description)
        ("/gryag", True, "Gryag command (no bot mention)"),
        ("/gryagban", True, "Gryag admin command"),
        ("/gryagfacts", True, "Gryag profile command"),
        ("/gryag@gryag_bot", True, "Gryag command for this bot"),
        ("/gryagban@gryag_bot", True, "Gryag command for this bot"),
        ("/gryag@GRYAG_BOT", True, "Gryag command (case insensitive)"),
        ("/gryag@other_bot", False, "Gryag command for different bot"),
        ("/gryagban@another_bot", False, "Gryag command for different bot"),
        ("/start", False, "Generic command (not gryag's)"),
        ("/help", False, "Generic command (not gryag's)"),
        ("/dban", False, "Unknown command (likely another bot)"),
        ("/ban", False, "Unknown command (not gryag's)"),
        ("/admincommand", False, "Unknown command (not gryag's)"),
        ("/start@other_bot", False, "Command for different bot"),
        ("/dban@some_bot", False, "Unknown command for different bot"),
        ("/gryagprofile param1", True, "Gryag command with params"),
        ("/gryag@other_bot param1", False, "Gryag command with params for other bot"),
        ("/dban param1 param2", False, "Unknown command with params"),
        ("Hello bot", False, "Not a command"),
        ("/", False, "Just slash (unknown command)"),
    ]

    print("Testing command throttle logic:")
    print("=" * 80)

    all_passed = True
    for command_text, expected_throttle, description in test_cases:
        result = is_command_for_this_bot(command_text, bot_username)

        status = "✓" if result == expected_throttle else "✗"
        if result != expected_throttle:
            all_passed = False

        print(
            f"{status} {description:<50} | Command: {command_text:<30} | "
            f"Expected: {'throttle' if expected_throttle else 'pass':<8} | "
            f"Got: {'throttle' if result else 'pass':<8}"
        )

    print("=" * 80)
    if all_passed:
        print("✓ All tests passed! Command throttle logic is correct.")
        print("\n📌 Key improvements:")
        print("  • Only throttles gryag's registered commands")
        print("  • Ignores commands for other bots (/dban, /start, etc.)")
        print("  • Handles @bot mentions correctly")
        print("  • Case-insensitive bot username matching")
        return 0
    else:
        print("✗ Some tests failed! Review the logic.")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(test_command_throttling())
