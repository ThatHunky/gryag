# Bot Personas

This directory contains bot personality configurations that define how the bot behaves, its name, language, trigger patterns, and admin users.

## Structure

```
personas/
├── ukrainian_gryag.yaml      # Default Ukrainian persona (current gryag)
├── english_assistant.yaml    # Example English assistant persona
└── templates/
    ├── ukrainian_gryag.txt   # System prompt template for Ukrainian gryag
    └── english_assistant.txt # System prompt template for English assistant
```

## Using a Persona

Set the `PERSONA_CONFIG` environment variable to the path of your persona file:

```bash
# Use Ukrainian gryag persona
PERSONA_CONFIG=personas/ukrainian_gryag.yaml

# Use English assistant persona
PERSONA_CONFIG=personas/english_assistant.yaml

# Use custom persona
PERSONA_CONFIG=personas/my_custom_bot.yaml
```

If `PERSONA_CONFIG` is empty or not set, the bot uses the default hardcoded Ukrainian gryag persona for backwards compatibility.

## Persona File Format

Persona files are in YAML format with the following structure:

```yaml
# Basic identity
name: "bot_name"                    # Internal name (used in code)
display_name: "Display Name"        # Name shown to users
language: "uk"                      # Language code (uk, en, etc.)
version: "1.0"
description: "Bot description"

# System prompt
system_prompt_template: "personas/templates/your_template.txt"

# Trigger patterns (regex)
trigger_patterns:
  - "\\b(?:bot|assistant)\\b"       # Regex patterns to trigger bot responses

# Admin users
admin_users:
  - user_id: 123456789
    name: "Admin Name"
    display_name: "Admin Display Name"
    special_status: "admin"         # admin, creator, admin_beloved, etc.

# Response templates
response_templates: "response_templates/your_templates.json"

# Behavior settings
allow_profanity: false              # Allow strong language
sarcasm_level: "low"                # low, medium, high
humor_style: "light"                # light, dark, dry, sarcastic
```

## System Prompt Templates

System prompt templates support variable substitution using Python's `.format()` syntax:

- `{bot_name}` - Bot's internal name
- `{bot_display_name}` - Bot's display name
- `{bot_username}` - Bot's Telegram username

Example:
```
You're {bot_name} ("{bot_display_name}", @{bot_username}) - a helpful assistant.
```

## Creating a Custom Persona

1. Copy an existing persona file as a starting point:
   ```bash
   cp personas/english_assistant.yaml personas/my_bot.yaml
   ```

2. Edit the YAML file with your bot's configuration

3. Create a system prompt template in `personas/templates/`:
   ```bash
   cp personas/templates/english_assistant.txt personas/templates/my_bot.txt
   ```

4. Edit the system prompt template with your bot's personality

5. Create response templates (see `response_templates/README.md`)

6. Set environment variables:
   ```bash
   BOT_NAME=mybot
   PERSONA_CONFIG=personas/my_bot.yaml
   RESPONSE_TEMPLATES=response_templates/my_bot.json
   ```

## Verification

Validate your persona file:

```bash
python3 -c "import yaml; yaml.safe_load(open('personas/my_bot.yaml'))"
```

If no errors, your YAML is valid!

## See Also

- `response_templates/` - Localized response templates
- `docs/plans/UNIVERSAL_BOT_PLAN.md` - Universal bot configuration plan
- `.env.example` - All available configuration options
