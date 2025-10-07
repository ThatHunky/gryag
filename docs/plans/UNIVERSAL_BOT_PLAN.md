# Universal Bot Configuration Plan

## Executive Summary

This document outlines a comprehensive plan to transform the gryag bot from a hardcoded Ukrainian-specific implementation into a universal, configurable bot framework that can support multiple personalities, languages, and group chat deployments.

## Current State Analysis

### Hardcoded Elements Identified

#### 1. Bot Identity
- **Bot name**: "gryag" appears in:
  - Trigger patterns (`app/services/triggers.py`)
  - Admin commands (`/gryagban`, `/gryagreset`, etc.)
  - Redis namespace (`gryag:quota:...`)
  - Error messages and responses

#### 2. Ukrainian Persona
- **System prompt**: Hardcoded in `app/persona.py` with Ukrainian personality traits
- **Admin users**: Specific users hardcoded with names and IDs:
  - кавунева пітса (ID: 831570515) - "admin_beloved" 
  - Всеволод Добровольський (ID: 392817811) - "creator"
- **Language-specific responses**: Ukrainian error messages like "Ґеміні знову тупить..."

#### 3. Trigger Patterns
- Hardcoded regex patterns for гряг/gryag variations
- No support for custom trigger words

#### 4. Group Chat Management
- Currently operates in any chat where added
- No filtering or restriction mechanisms
- Admin commands work everywhere

### Database Schema Review

The existing database schema already includes some multi-tenancy support:
- `bot_profiles` table with `bot_id` field supports multiple bot instances
- Schema can handle different bots without modifications
- Application code doesn't currently utilize these multi-bot features

## Proposed Universal Configuration System

### Level 1: Bot Identity Configuration

```bash
# Bot Identity
BOT_NAME=gryag                          # Display name for responses
BOT_USERNAME=gryag_bot                  # Telegram username (without @)
BOT_TRIGGER_PATTERNS=гряг,gryag         # Comma-separated trigger words
REDIS_NAMESPACE=gryag                   # Redis key prefix
COMMAND_PREFIX=gryag                    # Admin command prefix
```

### Level 2: Personality Configuration

```bash
# Personality & Language
PERSONA_CONFIG=personas/ukrainian_gryag.yaml    # Path to persona file
RESPONSE_TEMPLATES=response_templates/ukrainian.json  # Localized responses
BOT_LANGUAGE=uk                         # Primary language code
ENABLE_PROFANITY=true                   # Allow strong language
```

### Level 3: Chat Management

```bash
# Chat Filtering
BOT_BEHAVIOR_MODE=global                # global, whitelist, blacklist
ALLOWED_CHAT_IDS=                       # Comma-separated chat IDs (whitelist mode)
BLOCKED_CHAT_IDS=                       # Comma-separated chat IDs (blacklist mode)  
ADMIN_CHAT_IDS=                         # Where admin commands work
IGNORE_PRIVATE_CHATS=false              # Only operate in groups
```

### Level 4: Advanced Configuration

```bash
# Admin Users (JSON format)
ADMIN_USERS='[{"user_id": 831570515, "name": "Admin", "special_status": "admin"}]'

# Feature Toggles
ENABLE_CHAT_FILTERING=false             # Enable chat restrictions
ENABLE_CUSTOM_COMMANDS=true             # Use configurable command names
ENABLE_PERSONA_TEMPLATES=true           # Use template-based responses
```

## Persona Abstraction Layer

### File Structure

```
personas/
├── ukrainian_gryag.yaml          # Current gryag persona
├── english_assistant.yaml        # Generic English assistant
├── custom_bot.yaml              # User-defined persona
└── templates/
    ├── ukrainian_gryag.txt      # System prompt template
    ├── english_assistant.txt    # English prompt template
    └── custom_bot.txt           # Custom prompt template

response_templates/
├── ukrainian.json               # Ukrainian response templates
├── english.json                 # English response templates
└── custom.json                  # Custom response templates
```

### Persona Configuration Example

```yaml
# personas/ukrainian_gryag.yaml
name: "gryag"
display_name: "гряг"
language: "uk"
system_prompt_template: "personas/templates/ukrainian_gryag.txt"

# Trigger patterns (regex)
trigger_patterns:
  - "\\b(?:гр[яи]г[аоуеєіїюяьґ]*|gr[yi]ag\\w*)\\b"

# Admin users with special status
admin_users:
  - user_id: 831570515
    name: "кавунева пітса"
    display_name: "кавунева пітса #Я_З_ТОМАТОМ_СПАЙСІ 🍻△✙➔"
    special_status: "admin_beloved"
  - user_id: 392817811
    name: "Всеволод Добровольський"
    display_name: "батько"
    special_status: "creator"

# Response templates file
response_templates: "response_templates/ukrainian.json"

# Behavior settings
allow_profanity: true
sarcasm_level: "high"
humor_style: "dark"
```

### Response Templates Example

```json
{
  "error_fallback": "Ґеміні знову тупить. Спробуй пізніше.",
  "empty_reply": "Скажи конкретніше, бо зараз з цього нічого не зробити.",
  "banned_reply": "Ти для {bot_name} в бані. Йди погуляй.",
  "snarky_reply": "Пригальмуй, балакучий...",
  "throttle_notice": "Занадто багато повідомлень. Почекай {seconds} секунд.",
  "admin_only": "Тільки адміни можуть це робити.",
  "chat_not_allowed": "Я тут не працюю. Додай мене в дозволений чат.",
  "command_help": "Доступні команди: /{command_prefix}help, /{command_prefix}profile, /{command_prefix}facts"
}
```

## Implementation Roadmap

### Phase 1: Configuration Infrastructure (2-3 days)
**Risk Level**: Low  
**Backwards Compatibility**: 100%

**Goals**:
- Add new configuration options without breaking existing functionality
- Create persona abstraction layer with backwards compatibility

**Tasks**:
1. Add new environment variables to `app/config.py`
2. Create `app/services/persona/` module with `PersonaConfig` and `PersonaLoader`
3. Create `personas/` and `response_templates/` directories
4. Migrate current persona to `personas/ukrainian_gryag.yaml`
5. Create response templates in `response_templates/ukrainian.json`
6. Add backwards compatibility layer (defaults to current hardcoded values)

**Files Modified**:
- `app/config.py` - Add new Settings fields
- `.env.example` - Document new environment variables
- Create `app/services/persona/base.py` - PersonaConfig class
- Create `app/services/persona/loader.py` - PersonaLoader class
- Create `personas/ukrainian_gryag.yaml` - Current persona migrated
- Create `response_templates/ukrainian.json` - Current responses migrated

### Phase 2: Bot Identity Abstraction (3-4 days)
**Risk Level**: Medium  
**Backwards Compatibility**: 95% (Redis keys change namespace)

**Goals**:
- Make bot name, triggers, and commands configurable
- Add chat filtering capability (disabled by default)

**Tasks**:
1. Update `triggers.py` to use configurable patterns from persona config
2. Modify `throttle.py` to use configurable Redis namespace
3. Update admin command registration to use dynamic names
4. Create chat filter middleware with configurable behavior modes
5. Add chat info command for discovering chat IDs

**Files Modified**:
- `app/services/triggers.py` - Dynamic trigger patterns from config
- `app/middlewares/throttle.py` - Configurable Redis namespace  
- `app/handlers/admin.py` - Dynamic command names based on bot config
- `app/handlers/profile_admin.py` - Dynamic command names
- Create `app/middlewares/chat_filter.py` - Chat filtering middleware
- `app/main.py` - Add chat filter to middleware stack

### Phase 3: Response Template System (2-3 days)
**Risk Level**: Medium  
**Backwards Compatibility**: 90% (response text may change)

**Goals**:
- Replace all hardcoded responses with configurable templates
- Integrate persona loader throughout the application

**Tasks**:
1. Replace hardcoded responses in handlers with template system
2. Integrate PersonaLoader in middleware injection
3. Update admin user handling to use persona configuration
4. Add template variable substitution (bot_name, seconds, etc.)
5. Migrate current `app/persona.py` to template system

**Files Modified**:
- `app/handlers/chat.py` - Use template responses instead of hardcoded strings
- `app/middlewares/chat_meta.py` - Inject persona loader instance
- `app/persona.py` - Convert to use template system or deprecate
- All handlers - Replace hardcoded response strings

### Phase 4: Migration Tools & Documentation (1-2 days)
**Risk Level**: Low  
**Backwards Compatibility**: N/A (tooling only)

**Goals**:
- Provide tools and documentation for smooth migration
- Enable easy creation of new personas

**Tasks**:
1. Create migration script for existing deployments
2. Add persona creation wizard tool
3. Create comprehensive setup documentation
4. Add configuration validation tools
5. Create example personas for different use cases

**Files Created**:
- `scripts/migrate_to_universal.py` - Automated migration script
- `docs/UNIVERSAL_BOT_SETUP.md` - Complete setup guide
- `tools/create_persona.py` - Interactive persona creation
- `tools/validate_config.py` - Configuration validation
- `personas/english_assistant.yaml` - Example English persona
- `response_templates/english.json` - English response templates

## Migration Strategy

### For Existing gryag Deployments

1. **Prepare Migration** (Before Phase 1):
   ```bash
   # Backup current database and configuration
   cp gryag.db gryag.db.backup
   cp .env .env.backup
   ```

2. **Phase 1 Migration** (After infrastructure is ready):
   ```bash
   # Run migration script to create persona files
   python scripts/migrate_to_universal.py
   
   # Add new environment variables to .env
   BOT_NAME=gryag
   PERSONA_CONFIG=personas/ukrainian_gryag.yaml
   RESPONSE_TEMPLATES=response_templates/ukrainian.json
   ```

3. **Phase 2 Migration** (After bot identity abstraction):
   ```bash
   # Optional: Change Redis namespace if needed
   REDIS_NAMESPACE=gryag_new
   
   # Enable chat filtering if desired
   BOT_BEHAVIOR_MODE=whitelist
   ALLOWED_CHAT_IDS=-100123456789
   ```

4. **Phase 3 Migration** (After response templates):
   ```bash
   # Templates automatically used, no configuration changes needed
   # Verify responses match expectations
   ```

### For New Bot Deployments

1. **Create New Persona**:
   ```bash
   python tools/create_persona.py --name mybot --language en
   ```

2. **Configure Environment**:
   ```bash
   BOT_NAME=mybot
   BOT_USERNAME=mybot_username  
   PERSONA_CONFIG=personas/mybot.yaml
   RESPONSE_TEMPLATES=response_templates/english.json
   BOT_BEHAVIOR_MODE=whitelist
   ALLOWED_CHAT_IDS=-100123456789
   ```

3. **Deploy and Test**:
   ```bash
   python tools/validate_config.py
   python -m app.main
   ```

## Testing Strategy

### Unit Tests
- Configuration loading and validation
- Persona abstraction layer functionality  
- Template variable substitution
- Chat filtering logic
- Backwards compatibility

### Integration Tests
- End-to-end message processing with different personas
- Admin command functionality with dynamic names
- Chat filtering with different behavior modes
- Redis namespace isolation

### Migration Tests
- Migration script accuracy
- Backwards compatibility verification
- Configuration file validation
- Database schema compatibility

## Benefits of Universal Bot System

### For Developers
- **Reusability**: Single codebase supports multiple bot personalities
- **Maintainability**: Centralized configuration management
- **Testability**: Easy to test different configurations
- **Scalability**: Support for multiple bot instances

### For Deployments
- **Flexibility**: Easy customization without code changes
- **Localization**: Support for multiple languages
- **Security**: Chat filtering and access control
- **Monitoring**: Instance isolation and tracking

### For Users
- **Consistency**: Predictable behavior across different bots
- **Customization**: Tailored personalities for specific communities
- **Privacy**: Chat-specific operation modes
- **Reliability**: Tested and validated configuration system

## Risk Mitigation

### Technical Risks
- **Configuration complexity**: Provide validation tools and clear documentation
- **Backwards compatibility**: Extensive testing and gradual migration path
- **Performance impact**: Optimize configuration loading and caching

### Operational Risks
- **Migration failures**: Automated backup and rollback procedures
- **Configuration errors**: Validation tools and safe defaults
- **User confusion**: Clear migration guides and examples

### Business Risks
- **Feature regression**: Comprehensive testing of existing functionality  
- **User experience changes**: Gradual rollout with monitoring
- **Maintenance overhead**: Automated tools and clear documentation

## Success Metrics

### Technical Metrics
- Configuration loading time < 100ms
- Memory overhead < 10% compared to hardcoded version
- Test coverage > 90% for new persona system
- Zero regressions in existing functionality

### User Experience Metrics
- Migration completion time < 30 minutes for existing deployments
- New bot setup time < 15 minutes
- Configuration error rate < 5%
- User satisfaction with customization options

## Conclusion

The proposed universal bot configuration system will transform gryag from a hardcoded Ukrainian bot into a flexible, reusable framework while maintaining full backwards compatibility. The phased implementation approach minimizes risk while providing clear migration paths for existing deployments and easy setup for new bot instances.

The system enables:
- Multiple bot personalities and languages
- Flexible chat filtering and access control
- Easy customization without code changes  
- Scalable multi-instance deployments
- Comprehensive testing and validation tools

This investment in universalization will pay dividends in reduced maintenance overhead, increased adoption potential, and improved user satisfaction across diverse deployment scenarios.