# Response Templates

This directory contains localized response templates for bot messages. Templates support variable substitution for dynamic content.

## Structure

```
response_templates/
├── ukrainian.json    # Ukrainian responses (default for gryag)
└── english.json      # English responses (example)
```

## Using Response Templates

Set the `RESPONSE_TEMPLATES` environment variable:

```bash
# Use Ukrainian responses
RESPONSE_TEMPLATES=response_templates/ukrainian.json

# Use English responses
RESPONSE_TEMPLATES=response_templates/english.json

# Use custom responses
RESPONSE_TEMPLATES=response_templates/my_responses.json
```

If `RESPONSE_TEMPLATES` is empty or not set, the bot uses default hardcoded Ukrainian responses.

## Template File Format

Response templates are in JSON format:

```json
{
  "_comment": "Description of this template file",
  
  "error_fallback": "Error message when AI service fails",
  "empty_reply": "Message when bot can't understand the request",
  "banned_reply": "Message for banned users (supports {bot_name} variable)",
  "throttle_notice": "Rate limit message (supports {seconds} variable)",
  "admin_only": "Message when non-admin tries admin command",
  "chat_not_allowed": "Message when bot used in non-allowed chat",
  "command_help": "Help message (supports {command_prefix} variable)"
}
```

## Available Variables

Templates support these variables using Python `.format()` syntax:

- `{bot_name}` - Bot's name
- `{user_name}` - User's name
- `{chat_id}` - Chat ID
- `{thread_id}` - Thread ID
- `{chat_type}` - Chat type (group, private, etc.)
- `{seconds}` - Number of seconds (for throttle messages)
- `{command_prefix}` - Command prefix (e.g., "gryag" for /gryagban)

Example:
```json
{
  "banned_reply": "Ти для {bot_name} в бані. Йди погуляй.",
  "throttle_notice": "Почекай {seconds} секунд."
}
```

## Standard Response Keys

These keys are used throughout the bot:

- `error_fallback` - Generic error message
- `empty_reply` - Can't process request
- `banned_reply` - User is banned
- `snarky_reply` - Throttle warning (brief)
- `throttle_notice` - Throttle with time
- `admin_only` - Admin command access denied
- `chat_not_allowed` - Bot not allowed in chat
- `command_help` - Command help text
- `profile_not_found` - User profile not found
- `facts_empty` - No facts for user
- `ban_success` - User banned successfully
- `unban_success` - User unbanned
- `reset_success` - History reset
- `chat_info` - Chat information display

## Creating Custom Templates

1. Copy an existing template file:
   ```bash
   cp response_templates/english.json response_templates/my_responses.json
   ```

2. Edit the JSON file with your responses

3. Validate JSON syntax:
   ```bash
   python3 -c "import json; json.load(open('response_templates/my_responses.json'))"
   ```

4. Set environment variable:
   ```bash
   RESPONSE_TEMPLATES=response_templates/my_responses.json
   ```

## Tips

- Keep responses concise and natural
- Match the tone to your persona (sarcastic, professional, friendly, etc.)
- Test variable substitution with all possible values
- Use `_comment` keys for documentation (ignored by bot)
- Maintain consistency across all response keys

## See Also

- `personas/` - Bot personality configurations
- `docs/plans/UNIVERSAL_BOT_PLAN.md` - Universal bot configuration plan
- `.env.example` - All available configuration options
