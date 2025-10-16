# Development Setup Guide

Complete guide for setting up a local development environment for the Gryag bot.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Detailed Setup](#detailed-setup)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### Required Software

- **Python 3.11 or 3.12** ([Download](https://www.python.org/downloads/))
- **Git** ([Download](https://git-scm.com/downloads))
- **Telegram Bot Token** (get from [@BotFather](https://t.me/BotFather))
- **Google Gemini API Key** (get from [AI Studio](https://aistudio.google.com/app/apikey))

### Optional Software

- **Docker & Docker Compose** (for containerized development)
- **VS Code** or **PyCharm** (recommended IDEs)
- **SQLite Browser** (for database inspection)

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/gryag.git
cd gryag

# 2. Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.minimal .env
# Edit .env and add your TELEGRAM_TOKEN and GEMINI_API_KEY

# 5. Run tests
pytest tests/unit/ -v

# 6. Start the bot
python -m app.main
```

## Detailed Setup

### 1. Python Environment Setup

#### Option A: Using venv (Recommended)

```bash
# Create virtual environment
python3.12 -m venv venv

# Activate (Linux/Mac)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

# Verify Python version
python --version  # Should be 3.11+ or 3.12+

# Upgrade pip
python -m pip install --upgrade pip
```

#### Option B: Using pyenv (For multiple Python versions)

```bash
# Install pyenv (Linux/Mac)
curl https://pyenv.run | bash

# Install Python 3.12
pyenv install 3.12.0
pyenv local 3.12.0

# Create venv
python -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
# Install all dependencies (runtime + development)
pip install -r requirements.txt

# Verify installation
python -c "import aiogram, aiosqlite, pydantic; print('Core dependencies OK')"
python -c "import pytest, black, ruff; print('Dev dependencies OK')"
```

### 3. Configuration

#### Create .env File

```bash
# Copy minimal template
cp .env.minimal .env

# Or copy full example
cp .env.example .env
```

#### Configure Required Settings

Edit `.env` and set:

```bash
# Required
TELEGRAM_TOKEN=your_telegram_bot_token_here
GEMINI_API_KEY=your_gemini_api_key_here

# Optional (for testing)
ADMIN_USER_IDS=your_telegram_user_id

# Optional (for weather/currency)
OPENWEATHER_API_KEY=your_openweather_key
EXCHANGE_RATE_API_KEY=your_exchange_rate_key
```

**How to get your tokens:**

1. **Telegram Bot Token**:
   - Message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow instructions
   - Copy the token (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

2. **Gemini API Key**:
   - Visit [Google AI Studio](https://aistudio.google.com/app/apikey)
   - Click "Create API Key"
   - Copy the key (format: `AIzaSy...`)

3. **Your Telegram User ID** (for admin commands):
   - Message [@userinfobot](https://t.me/userinfobot)
   - It will reply with your user ID (e.g., `123456789`)

#### Validate Configuration

```bash
# Test configuration loading
python -c "
from app.config import Settings
s = Settings()
warnings = s.validate_startup()
print('Configuration valid!')
if warnings:
    print('Warnings:')
    for w in warnings:
        print(f'  - {w}')
"
```

### 4. Database Setup

The database is automatically created on first run. To manually initialize:

```bash
# Create database directory
mkdir -p ./

# Apply schema
sqlite3 gryag.db < db/schema.sql

# Verify tables
sqlite3 gryag.db ".tables"
# Should show: bans, bot_facts, bot_interaction_outcomes, bot_insights, ...
```

### 5. IDE Setup

#### VS Code

Install recommended extensions:
- Python (Microsoft)
- Pylance
- Python Test Explorer
- SQLite Viewer

Create `.vscode/settings.json`:

```json
{
    "python.linting.enabled": true,
    "python.linting.ruffEnabled": true,
    "python.formatting.provider": "black",
    "python.testing.pytestEnabled": true,
    "python.testing.unittestEnabled": false,
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
        "source.organizeImports": true
    }
}
```

#### PyCharm

1. Open project in PyCharm
2. Configure interpreter:
   - File → Settings → Project → Python Interpreter
   - Add interpreter → Existing environment
   - Select `venv/bin/python`
3. Enable pytest:
   - Settings → Tools → Python Integrated Tools
   - Testing → Default test runner → pytest

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/my-awesome-feature
```

### 2. Make Changes

Edit code, following the [style guide](../../CONTRIBUTING.md#code-style).

### 3. Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/unit/test_config.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# View coverage report
open htmlcov/index.html  # Mac/Linux
start htmlcov/index.html  # Windows
```

### 4. Format and Lint Code

```bash
# Format with black
black app/ tests/

# Sort imports
isort app/ tests/

# Lint with ruff
ruff check app/ tests/

# Fix auto-fixable issues
ruff check --fix app/ tests/

# Type check (optional)
mypy app/
```

### 5. Run the Bot Locally

```bash
# Start bot
python -m app.main

# With debug logging
LOG_LEVEL=DEBUG python -m app.main

# With specific configuration
cp .env .env.backup
cp .env.development .env
python -m app.main
```

### 6. Test with Telegram

1. Find your bot on Telegram (username from BotFather)
2. Send `/start` to initialize
3. Test features:
   - Send a message to test basic response
   - Tag bot with `@your_bot_name` in groups
   - Try commands like `/gryag` or `/gryaghelp`

## Testing

### Running Tests

```bash
# All tests
pytest tests/

# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# Specific test
pytest tests/unit/test_config.py::test_settings_validation -v

# With coverage
pytest tests/ --cov=app --cov-report=term-missing

# Parallel execution (faster)
pytest tests/ -n auto  # Requires pytest-xdist
```

### Writing Tests

Place tests in appropriate directories:
- `tests/unit/` - Fast, isolated tests
- `tests/integration/` - Tests with external dependencies

Example test:

```python
import pytest
from app.config import Settings

def test_settings_validation():
    """Test that Settings validates required fields."""
    # This will raise ValueError because tokens are missing
    with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
        s = Settings()
        s.validate_startup()

@pytest.mark.asyncio
async def test_async_function():
    """Test async code."""
    result = await some_async_function()
    assert result == expected_value
```

### Test Coverage Goals

- **Minimum**: 70% overall
- **Target**: 80%+ for core services
- **Critical**: 90%+ for context assembly, memory operations

## Debugging

### Using VS Code Debugger

Create `.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Bot",
            "type": "python",
            "request": "launch",
            "module": "app.main",
            "console": "integratedTerminal",
            "env": {
                "LOG_LEVEL": "DEBUG"
            }
        },
        {
            "name": "Python: Current Test File",
            "type": "python",
            "request": "launch",
            "module": "pytest",
            "args": [
                "${file}",
                "-v"
            ],
            "console": "integratedTerminal"
        }
    ]
}
```

Set breakpoints and press F5 to start debugging.

### Using pdb (Python Debugger)

```python
# Add breakpoint in code
import pdb; pdb.set_trace()

# Or use breakpoint() (Python 3.7+)
breakpoint()
```

### Logging

```python
import logging

logger = logging.getLogger(__name__)

# Different log levels
logger.debug("Detailed debugging information")
logger.info("General information")
logger.warning("Warning message")
logger.error("Error occurred", exc_info=True)  # Include traceback
```

View logs:

```bash
# Real-time logs
tail -f logs/gryag.log

# Search logs
grep "ERROR" logs/gryag.log

# Last 100 lines
tail -n 100 logs/gryag.log
```

### Database Inspection

```bash
# Open database
sqlite3 gryag.db

# Common queries
.schema messages
SELECT COUNT(*) FROM messages;
SELECT * FROM user_profiles LIMIT 10;
SELECT * FROM facts WHERE entity_type='user' LIMIT 10;

# Or use DB Browser for SQLite (GUI)
# Download: https://sqlitebrowser.org/
```

## Troubleshooting

### Common Issues

#### 1. ImportError: No module named 'app'

**Solution**: Run from project root with `-m` flag:
```bash
python -m app.main  # ✓ Correct
python app/main.py  # ✗ Wrong
```

#### 2. Configuration validation fails

**Error**: `ValueError: TELEGRAM_TOKEN is required`

**Solution**: Check `.env` file exists and contains tokens:
```bash
cat .env | grep TELEGRAM_TOKEN
# Should show: TELEGRAM_TOKEN=your_token_here
```

#### 3. Tests fail with "No module named pytest"

**Solution**: Install dev dependencies:
```bash
pip install pytest pytest-asyncio pytest-cov
# Or
pip install -r requirements.txt
```

#### 4. Database locked error

**Error**: `sqlite3.OperationalError: database is locked`

**Solution**:
- Close other connections to database
- Check if bot is already running
- Delete lock file: `rm gryag.db-wal gryag.db-shm`

#### 5. Rate limit errors from Gemini API

**Error**: `GeminiError: Rate limit exceeded`

**Solution**:
- Reduce `MAX_TURNS` in `.env` (default: 50 → try 20)
- Reduce `CONTEXT_TOKEN_BUDGET` (default: 8000 → try 4000)
- Add delay between messages
- Upgrade Gemini API plan

#### 6. Bot not responding in groups

**Possible causes**:
- Bot not added to group
- Privacy mode enabled (bot only sees commands)
- Chat filtering enabled with wrong whitelist

**Solution**:
```bash
# Check bot settings in .env
cat .env | grep BOT_BEHAVIOR_MODE
# Should be: BOT_BEHAVIOR_MODE=global

# Disable privacy mode in BotFather:
# 1. Message @BotFather
# 2. /mybots → Select bot → Bot Settings → Group Privacy → Turn off
```

### Getting Help

1. Check logs: `tail -f logs/gryag.log`
2. Enable debug logging: `LOG_LEVEL=DEBUG python -m app.main`
3. Search issues: Check GitHub issues for similar problems
4. Ask for help: Open a new issue with:
   - Error message
   - Steps to reproduce
   - Python version (`python --version`)
   - OS and version

## Docker Development (Alternative)

For containerized development:

```bash
# Build and start
docker-compose up --build

# Run tests in container
docker-compose run bot pytest tests/ -v

# Shell access
docker-compose run bot bash

# View logs
docker-compose logs -f bot

# Stop
docker-compose down
```

## Next Steps

After setting up:
1. Read [CONTRIBUTING.md](../../CONTRIBUTING.md) for contribution guidelines
2. Check [SYSTEM_OVERVIEW.md](../architecture/SYSTEM_OVERVIEW.md) for architecture
3. Browse [docs/](../) for feature documentation
4. Join development discussions (if available)

---

**Questions?** Open an issue or check existing documentation in `docs/`.
