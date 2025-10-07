# Universal Bot Quick Start Guide

This guide shows how to use the new universal bot configuration system to create custom bot personalities and deploy to different group chats.

## Current Status

✅ **Phase 1 Complete** - Configuration infrastructure ready  
🚧 **Phase 2 In Progress** - Bot identity abstraction (commands, triggers, chat filtering)

You can start creating custom personas now. Full runtime integration coming in Phase 2.

## Quick Start: Use Default Configuration

No changes needed! Existing `.env` files work as-is:

```bash
TELEGRAM_TOKEN=your_token
GEMINI_API_KEY=your_key
```

Bot continues to use hardcoded Ukrainian gryag persona.

## Quick Start: Enable Persona System

To start using YAML personas and JSON response templates:

1. Update `.env`:
   ```bash
   # Enable persona templates
   ENABLE_PERSONA_TEMPLATES=true
   PERSONA_CONFIG=personas/ukrainian_gryag.yaml
   RESPONSE_TEMPLATES=response_templates/ukrainian.json
   ```

2. Restart bot:
   ```bash
   python -m app.main
   ```

Bot now loads personality from configuration files instead of hardcoded values.

## Create a Custom Persona

### Step 1: Create Persona Configuration

Copy and customize an existing persona:

```bash
cp personas/english_assistant.yaml personas/mybot.yaml
```

Edit `personas/mybot.yaml`:

```yaml
name: "mybot"
display_name: "My Bot"
language: "en"
version: "1.0"
description: "My custom bot personality"

system_prompt_template: "personas/templates/mybot.txt"

trigger_patterns:
  - "\\b(?:mybot|assistant|help)\\b"

admin_users:
  - user_id: YOUR_USER_ID
    name: "Your Name"
    display_name: "Admin"
    special_status: "admin"

response_templates: "response_templates/mybot.json"

allow_profanity: false
sarcasm_level: "low"
humor_style: "light"
```

### Step 2: Create System Prompt Template

Copy and customize:

```bash
cp personas/templates/english_assistant.txt personas/templates/mybot.txt
```

Edit `personas/templates/mybot.txt` with your bot's personality. Use variables:
- `{bot_name}` - Bot's name
- `{bot_display_name}` - Display name
- `{bot_username}` - Telegram username

### Step 3: Create Response Templates

Copy and customize:

```bash
cp response_templates/english.json response_templates/mybot.json
```

Edit `response_templates/mybot.json` with your custom responses.

### Step 4: Configure Environment

Update `.env`:

```bash
# Bot Identity
BOT_NAME=mybot
# BOT_USERNAME auto-detected from token

# Personality
PERSONA_CONFIG=personas/mybot.yaml
RESPONSE_TEMPLATES=response_templates/mybot.json
BOT_LANGUAGE=en
ENABLE_PROFANITY=false

# Enable templates
ENABLE_PERSONA_TEMPLATES=true
```

### Step 5: Deploy

```bash
python -m app.main
```

Your custom bot is now running!

## Restrict Bot to Specific Chats

### Step 1: Discover Chat IDs

Add bot to your group chat, then use a command to get the chat ID:

```bash
# In the group chat (Phase 2 feature, coming soon):
/gryagchatinfo
```

This will show:
```
Chat ID: -100123456789
Thread ID: None
Chat Type: supergroup
```

### Step 2: Configure Chat Filtering

Update `.env`:

```bash
# Enable chat filtering
ENABLE_CHAT_FILTERING=true

# Whitelist mode - only work in these chats
BOT_BEHAVIOR_MODE=whitelist
ALLOWED_CHAT_IDS=-100123456789,-100987654321

# Where admin commands work
ADMIN_CHAT_IDS=-100123456789
```

### Step 3: Restart Bot

```bash
python -m app.main
```

Bot now only operates in allowed chats!

## Common Configurations

### Professional English Assistant

```bash
BOT_NAME=assistant
PERSONA_CONFIG=personas/english_assistant.yaml
RESPONSE_TEMPLATES=response_templates/english.json
BOT_LANGUAGE=en
ENABLE_PROFANITY=false
ENABLE_PERSONA_TEMPLATES=true
```

### Ukrainian Gryag (Default)

```bash
BOT_NAME=gryag
PERSONA_CONFIG=personas/ukrainian_gryag.yaml
RESPONSE_TEMPLATES=response_templates/ukrainian.json
BOT_LANGUAGE=uk
ENABLE_PROFANITY=true
ENABLE_PERSONA_TEMPLATES=true
```

### Custom Bot with Chat Restrictions

```bash
# Identity
BOT_NAME=custombot
PERSONA_CONFIG=personas/custombot.yaml
RESPONSE_TEMPLATES=response_templates/custombot.json

# Chat filtering
ENABLE_CHAT_FILTERING=true
BOT_BEHAVIOR_MODE=whitelist
ALLOWED_CHAT_IDS=-100123456789
ADMIN_CHAT_IDS=-100123456789

# Features
ENABLE_PERSONA_TEMPLATES=true
ENABLE_CUSTOM_COMMANDS=true
```

## Validation

### Check Persona File

```bash
python3 -c "import yaml; yaml.safe_load(open('personas/mybot.yaml'))"
```

No output = valid YAML!

### Check Response Templates

```bash
python3 -c "import json; json.load(open('response_templates/mybot.json'))"
```

No output = valid JSON!

### Check Configuration Loading

```bash
python3 -c "from app.config import get_settings; s = get_settings(); print(f'Bot: {s.bot_name}'); print(f'Persona: {s.persona_config}')"
```

Should show your configuration.

## Troubleshooting

### Bot uses hardcoded persona

Check:
- `ENABLE_PERSONA_TEMPLATES=true` in `.env`
- `PERSONA_CONFIG` path is correct
- YAML file exists and is valid

### Responses in wrong language

Check:
- `RESPONSE_TEMPLATES` path is correct
- JSON file exists and is valid
- File contains all required template keys

### Chat filtering not working

Check:
- `ENABLE_CHAT_FILTERING=true` in `.env`
- Chat IDs are correct (negative numbers for groups)
- `BOT_BEHAVIOR_MODE` is set correctly

### Configuration not loading

Check:
- `.env` file exists in project root
- No syntax errors in `.env`
- Restart bot after changes

## Next Steps

See full documentation:
- `docs/plans/UNIVERSAL_BOT_PLAN.md` - Complete plan
- `docs/phases/UNIVERSAL_BOT_PHASE_1_COMPLETE.md` - Phase 1 details
- `personas/README.md` - Persona system documentation
- `response_templates/README.md` - Response template documentation

Phase 2 will add:
- Dynamic command names based on `COMMAND_PREFIX`
- Configurable trigger patterns in runtime
- Chat filtering middleware
- Chat info command for discovering IDs

Stay tuned!
