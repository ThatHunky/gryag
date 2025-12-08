# Features Overview

This directory contains documentation for all gryag bot features. Below is an index organized by category.

## 🤖 Core AI Features

| Feature | Description | Doc |
|---------|-------------|-----|
| **Gemini Thinking Mode** | Chain-of-thought reasoning (hidden from users) | [comprehensive-model-capability-detection.md](comprehensive-model-capability-detection.md) |
| **Time Awareness** | Bot knows current date/time | [TIME_AWARENESS.md](TIME_AWARENESS.md) |
| **Function Calling** | Model uses tools automatically | [function-calling-support-detection.md](function-calling-support-detection.md) |

## 🧠 Memory & Context

| Feature | Description | Doc |
|---------|-------------|-----|
| **Reply Chain Context** | Bot sees replied-to message content | [REPLY_CHAIN_CONTEXT.md](REPLY_CHAIN_CONTEXT.md) |
| **Video/Sticker Context** | Media visible in conversation history | [VIDEO_STICKER_CONTEXT.md](VIDEO_STICKER_CONTEXT.md) |
| **Bot Self-Learning** | Bot learns about its own effectiveness | [BOT_SELF_LEARNING.md](BOT_SELF_LEARNING.md) |
| **Facts Pagination** | Paginated fact display with buttons | [FACTS_PAGINATION_WITH_BUTTONS.md](FACTS_PAGINATION_WITH_BUTTONS.md) |
| **Forget Fact** | Soft delete facts on request | [FORGET_FACT_IMPLEMENTATION.md](FORGET_FACT_IMPLEMENTATION.md) |
| **Forget All Facts** | Bulk delete all user facts | [FORGET_ALL_FACTS_BULK_DELETE.md](FORGET_ALL_FACTS_BULK_DELETE.md) |
| **Hybrid Extraction** | Regex + LLM fact extraction | [HYBRID_EXTRACTION_COMPLETE.md](HYBRID_EXTRACTION_COMPLETE.md) |

## 🖼️ Media & Multimodal

| Feature | Description | Doc |
|---------|-------------|-----|
| **Image Generation** | Text-to-image via Pollinations/Gemini | [IMAGE_GENERATION.md](IMAGE_GENERATION.md) |
| **Multimodal Support** | Images, audio, video, documents | [MULTIMODAL_CAPABILITIES.md](MULTIMODAL_CAPABILITIES.md) |
| **Media Handling** | Graceful fallbacks for unsupported media | [graceful-media-handling.md](graceful-media-handling.md) |
| **Improved Media** | Enhanced media processing | [IMPROVED_MEDIA_HANDLING.md](IMPROVED_MEDIA_HANDLING.md) |

## ⚙️ Admin & Configuration

| Feature | Description | Doc |
|---------|-------------|-----|
| **System Prompt Management** | Customize bot personality via commands | [SYSTEM_PROMPT_MANAGEMENT.md](SYSTEM_PROMPT_MANAGEMENT.md) |
| **Command Throttling** | Rate limiting for commands | [COMMAND_THROTTLING.md](COMMAND_THROTTLING.md) |
| **Bot Command Hints** | Telegram command menu | [BOT_COMMAND_HINTS.md](BOT_COMMAND_HINTS.md) |

## 🔑 API Keys & Billing

| Feature | Description | Doc |
|---------|-------------|-----|
| **Separate Image API Key** | Different billing for images | [SEPARATE_IMAGE_API_KEY.md](SEPARATE_IMAGE_API_KEY.md) |
| **Separate Web Search Key** | Different billing for search | [SEPARATE_WEB_SEARCH_API_KEY.md](SEPARATE_WEB_SEARCH_API_KEY.md) |

## Quick Reference

- [MULTIMODAL_QUICKREF.md](MULTIMODAL_QUICKREF.md) — Quick multimodal reference
- [COMPREHENSIVE_IMPROVEMENTS_2025_10_21.md](COMPREHENSIVE_IMPROVEMENTS_2025_10_21.md) — October 2025 improvements summary
