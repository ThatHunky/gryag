# Contributing to Gryag

Thank you for your interest in contributing to Gryag! This guide will help you get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Development Workflow](#development-workflow)
- [Testing Guidelines](#testing-guidelines)
- [Code Style](#code-style)
- [Pull Request Process](#pull-request-process)
- [Documentation](#documentation)

## Code of Conduct

This project follows a professional and inclusive code of conduct. Be respectful, constructive, and collaborative.

## Getting Started

### Prerequisites

- **Python 3.11+** (3.12 recommended)
- **Docker** and **Docker Compose** (for containerized development)
- **Telegram Bot Token** (get from [@BotFather](https://t.me/BotFather))
- **Google Gemini API Key** (get from [AI Studio](https://aistudio.google.com/app/apikey))

### Quick Start

1. **Fork and Clone**
   ```bash
   git clone https://github.com/YOUR_USERNAME/gryag.git
   cd gryag
   ```

2. **Set Up Environment**
   ```bash
   # Copy minimal config
   cp .env.minimal .env

   # Edit .env and add your tokens
   nano .env  # or vim, code, etc.
   ```

3. **Choose Your Setup Method**

   **Option A: Docker (Recommended)**
   ```bash
   docker-compose up --build
   ```

   **Option B: Local Python**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   python -m app.main
   ```

## Development Setup

### Local Development with Python

```bash
# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies (including dev tools)
pip install -r requirements.txt

# Install the package in editable mode
pip install -e ".[dev]"

# Verify installation
python -c "import app; print('Setup successful!')"
```

### Database Setup

The database schema is automatically created on first run. To manually apply the schema:

```bash
sqlite3 gryag.db < db/schema.sql
```

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run specific test categories
pytest tests/unit/  # Unit tests only
pytest tests/integration/  # Integration tests only
pytest -m "not slow"  # Skip slow tests

# Run with verbose output
pytest tests/ -v
```

### Code Quality Checks

```bash
# Format code with black
black app/ tests/

# Sort imports
isort app/ tests/

# Lint with ruff
ruff check app/ tests/

# Type checking
mypy app/
```

## Project Structure

```
gryag/
├── app/                      # Main application code
│   ├── handlers/             # Telegram message handlers
│   ├── services/             # Business logic & external services
│   │   ├── context/          # Context & memory management
│   │   ├── fact_extractors/  # Fact extraction logic
│   │   ├── monitoring/       # Continuous monitoring
│   │   └── tools/            # Memory tools (function calling)
│   ├── repositories/         # Data access layer
│   ├── middlewares/          # Bot middleware
│   ├── core/                 # Core utilities (logging, exceptions)
│   └── infrastructure/       # Database & migrations
├── db/                       # Database schema
├── docs/                     # Documentation
│   ├── guides/               # Operational guides
│   ├── phases/               # Implementation phase docs
│   ├── plans/                # Architecture & planning docs
│   └── fixes/                # Bug fix documentation
├── tests/                    # Test suite
│   ├── unit/                 # Unit tests
│   └── integration/          # Integration tests
└── scripts/                  # Utility scripts
    ├── diagnostics/          # Diagnostic tools
    ├── migrations/           # Database migrations
    └── verification/         # Verification scripts
```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/issue-description
```

### 2. Make Your Changes

- **Write tests first** (TDD recommended)
- **Keep commits atomic** (one logical change per commit)
- **Write clear commit messages** (see commit message guidelines below)

### 3. Test Your Changes

```bash
# Run tests
pytest tests/

# Check code quality
black app/ tests/
ruff check app/
mypy app/
```

### 4. Update Documentation

- Update relevant docs in `docs/`
- Add docstrings to new functions/classes
- Update `docs/CHANGELOG.md` if user-facing changes

### 5. Submit Pull Request

See [Pull Request Process](#pull-request-process) below.

## Testing Guidelines

### Writing Tests

- **Place tests in appropriate directories**:
  - `tests/unit/` for isolated unit tests
  - `tests/integration/` for integration tests

- **Follow naming conventions**:
  - Test files: `test_<module_name>.py`
  - Test functions: `test_<what_it_tests>()`
  - Test classes: `Test<ClassName>`

- **Use pytest fixtures** for common setup:
  ```python
  import pytest

  @pytest.fixture
  async def mock_gemini_client():
      """Fixture for mocked Gemini client."""
      # Setup
      client = MockGeminiClient()
      yield client
      # Teardown
      await client.cleanup()
  ```

- **Test async code properly**:
  ```python
  import pytest

  @pytest.mark.asyncio
  async def test_async_function():
      result = await some_async_function()
      assert result == expected_value
  ```

### Test Coverage Goals

- **Minimum**: 70% overall coverage
- **Target**: 80%+ for core services
- **Critical paths**: 90%+ (context assembly, memory operations)

## Code Style

### Python Style Guide

We follow **PEP 8** with some modifications (see `pyproject.toml`):

- **Line length**: 88 characters (Black's default)
- **Imports**: Sorted with `isort` (black-compatible profile)
- **Type hints**: Encouraged for public APIs
- **Docstrings**: Google style for functions/classes

### Example Code Style

```python
"""Module docstring explaining the module's purpose."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.gemini import GeminiClient
from app.config import Settings

logger = logging.getLogger(__name__)


class ExampleService:
    """Brief description of the service.

    More detailed explanation if needed.

    Args:
        client: Gemini API client
        settings: Application settings
    """

    def __init__(self, client: GeminiClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def process_message(
        self,
        message: str,
        chat_id: int,
    ) -> str:
        """Process a user message and return a response.

        Args:
            message: User's message text
            chat_id: Telegram chat ID

        Returns:
            Generated response text

        Raises:
            GeminiError: If API call fails
        """
        logger.debug("Processing message for chat %d", chat_id)

        try:
            response = await self._client.generate(message)
            return response
        except Exception as e:
            logger.error("Failed to process message: %s", e, exc_info=True)
            raise
```

### Commit Message Guidelines

Follow the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <short summary>

<detailed description>

<footer>
```

**Types**:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Formatting, missing semicolons, etc. (no code change)
- `refactor:` Code refactoring
- `test:` Adding tests
- `chore:` Maintenance tasks

**Examples**:
```bash
feat(memory): add semantic deduplication for facts

Implements cosine similarity comparison to detect and merge
duplicate facts with 85% similarity threshold.

Closes #123

---

fix(chat): handle media context in reply messages

Fixes issue where media from replied-to messages was not
visible in conversation context.

Fixes #456
```

## Pull Request Process

### Before Submitting

1. **Update your branch** with latest main:
   ```bash
   git fetch origin
   git rebase origin/main
   ```

2. **Run all checks**:
   ```bash
   # Format code
   black app/ tests/
   isort app/ tests/

   # Run tests
   pytest tests/ --cov=app

   # Lint
   ruff check app/
   ```

3. **Update documentation**:
   - Add entry to `docs/CHANGELOG.md`
   - Update relevant docs in `docs/`
   - Add docstrings to new code

### Submitting a PR

1. **Push your branch**:
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Create PR on GitHub** with:
   - **Clear title**: Following conventional commits format
   - **Description**: Explain what and why
   - **Tests**: Describe how you tested
   - **Checklist**: Use PR template (if available)

3. **PR Description Template**:
   ```markdown
   ## Description
   Brief summary of changes and motivation.

   ## Changes Made
   - Change 1
   - Change 2

   ## Testing
   - [ ] Unit tests added/updated
   - [ ] Integration tests pass
   - [ ] Manual testing completed

   ## Documentation
   - [ ] Updated relevant docs
   - [ ] Added docstrings
   - [ ] Updated CHANGELOG.md

   ## Checklist
   - [ ] Code follows style guidelines
   - [ ] Tests pass locally
   - [ ] No new warnings
   - [ ] Branch is up to date with main

   Closes #issue_number
   ```

### Review Process

- **Maintainer reviews** within 3-5 business days
- **Address feedback** by pushing new commits
- **CI checks** must pass (when available)
- **Squash merge** for feature branches (maintainer handles this)

## Documentation

### When to Update Docs

- **New features**: Create feature doc in `docs/features/`
- **Bug fixes**: Document in `docs/fixes/` if complex
- **Configuration changes**: Update `.env.example` and docs
- **API changes**: Update docstrings and relevant guides

### Documentation Style

- **Clear and concise**: Get to the point quickly
- **Code examples**: Show, don't just tell
- **Verification steps**: Include commands to verify setup
- **Markdown formatting**: Use headers, code blocks, lists effectively

### Example Documentation Structure

```markdown
# Feature Name

Brief one-line description.

## Overview

Detailed explanation of what the feature does and why it exists.

## Usage

### Basic Example

\```python
# Code example showing basic usage
\```

### Advanced Usage

\```python
# More complex example
\```

## Configuration

Required settings in `.env`:

\```bash
FEATURE_ENABLED=true
FEATURE_OPTION=value
\```

## Testing

How to test the feature:

\```bash
pytest tests/unit/test_feature.py -v
\```

## Verification

How to verify it's working:

\```bash
# Command to verify
\```

## Troubleshooting

Common issues and solutions.
```

## Getting Help

- **Documentation**: Check `docs/` directory first
- **Issues**: Search existing GitHub issues
- **Questions**: Open a GitHub issue with `question` label
- **Chat**: [If you have a Discord/Slack/etc.]

## Recognition

Contributors are recognized in:
- `CONTRIBUTORS.md` (if created)
- Release notes
- Git commit history

Thank you for contributing to Gryag! 🚀
