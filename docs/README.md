# Documentation Index
<!-- markdownlint-disable -->

This directory contains the repository documentation organized into subfolders. When moving or reorganizing docs, follow the rules in `AGENTS.md` and add a short summary here describing the change.

## Directory Structure

| Directory | Description |
|-----------|-------------|
| [API_DOCUMENTATION.md](API_DOCUMENTATION.md) | Comprehensive API documentation for all public APIs, functions, and components |
| [CHANGELOG.md](CHANGELOG.md) | Detailed changelog with all project changes |
| [architecture/](architecture/) | System architecture and data models |
| [features/](features/) | Feature specifications and documentation |
| [fixes/](fixes/) | Bug fix documentation |
| [guides/](guides/) | Operational guides and runbooks |
| [history/](history/) | Transient exports or archived notes |
| [other/](other/) | Miscellaneous documentation |
| [overview/](overview/) | High-level project overviews |
| [phases/](phases/) | Phase-specific writeups and status reports |
| [plans/](plans/) | Implementation plans and roadmaps |
| [rfcs/](rfcs/) | Request for comments / design proposals |

## Recent Changes

**December 2025**: Documentation cleanup — consolidated duplicate "Recent Changes" sections, removed obsolete proposals, and reorganized the docs index.

**January 2025**: **📚 Comprehensive API Documentation** — Added complete API documentation covering all public APIs, functions, and components. See [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

**November 2025**: 
- **P0 Improvements**: Context budgets, automated PostgreSQL migrations, persona plain-text enforcement, secret masking
- **Docker/Runtime**: Multi-stage Dockerfile, dev/prod compose with HTTP healthchecks, image generation via Gemini 2.5 Flash Image
- **Telegram Checkers**: User-vs-user challenges with inline controls
- **C++ Tools**: Weather, currency, polls, web/search, memory, and Gemini image tools

**October 2025** (Key highlights):
- **Gemini 2.5 Thinking Support** — Fixed detection logic for thinking mode
- **Reply Chain Context** — Bot reliably sees replied-to message content
- **Video & Sticker Context** — Fixed media visibility in conversation history
- **Image Generation** — Native text-to-image with Gemini 2.5 Flash Image
- **Compact Conversation Format** — 73.7% token reduction (Phase 6)
- **Unified Fact Storage** — Single `facts` table replacing separate tables
- **Bot Self-Learning System** — Bot learns about its own effectiveness (Phase 5)
- **System Prompt Management** — Admin commands for prompt customization
- **Universal Bot Configuration** — Multi-deployment support with personas

## Key Documentation

### For New Contributors
- [API_DOCUMENTATION.md](API_DOCUMENTATION.md) — Complete API reference
- [guides/CONTRIBUTING.md](guides/CONTRIBUTING.md) — Contribution guidelines
- [overview/MODEL_CONTEXT_PIPELINE.md](overview/MODEL_CONTEXT_PIPELINE.md) — How context is assembled

### Architecture & Design
- [architecture/FACTS_STORAGE_ARCHITECTURE.md](architecture/FACTS_STORAGE_ARCHITECTURE.md) — Fact storage data model
- [overview/CURRENT_CONVERSATION_PATTERN.md](overview/CURRENT_CONVERSATION_PATTERN.md) — Gemini API format

### Features
- [features/BOT_SELF_LEARNING.md](features/BOT_SELF_LEARNING.md) — Self-learning system
- [features/IMAGE_GENERATION.md](features/IMAGE_GENERATION.md) — Image generation
- [features/SYSTEM_PROMPT_MANAGEMENT.md](features/SYSTEM_PROMPT_MANAGEMENT.md) — Prompt management
- [features/VIDEO_STICKER_CONTEXT.md](features/VIDEO_STICKER_CONTEXT.md) — Media context handling

### Guides
- [guides/TOKEN_OPTIMIZATION.md](guides/TOKEN_OPTIMIZATION.md) — Token efficiency guide
- [guides/FACT_LIFECYCLE_VERIFICATION.md](guides/FACT_LIFECYCLE_VERIFICATION.md) — Fact extraction lifecycle

### Implementation Phases
- [phases/UNIFIED_FACT_STORAGE_COMPLETE.md](phases/UNIFIED_FACT_STORAGE_COMPLETE.md) — Unified facts migration
- [phases/UNIVERSAL_BOT_PHASE_3_COMPLETE.md](phases/UNIVERSAL_BOT_PHASE_3_COMPLETE.md) — Universal bot configuration

## Verification

When adding or moving files, update this README and run:
```bash
# Verify documentation links
grep -r "](.*\.md)" docs/README.md | head -5

# Check for broken internal links
find docs/ -name "*.md" | head -10
```
