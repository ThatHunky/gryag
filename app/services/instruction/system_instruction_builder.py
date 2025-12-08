"""System instruction builder for dynamic system prompt generation."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from app.persona import SYSTEM_PERSONA
from app.repositories.chat_summary_repository import ChatSummaryRepository
from app.services.context.token_optimizer import estimate_message_tokens

logger = logging.getLogger(__name__)


class SystemInstructionBuilder:
    """Builds dynamic system instructions with context, summaries, and tools."""

    def __init__(
        self,
        settings: Settings,
        summary_repository: ChatSummaryRepository,
        context_store: Any | None = None,
    ) -> None:
        """
        Initialize the system instruction builder.

        Args:
            settings: Application settings
            summary_repository: Repository for chat summaries
            context_store: Optional context store for message retrieval
        """
        self.settings = settings
        self.summary_repository = summary_repository
        self.context_store = context_store

    def build_immutable_block(
        self, chat_name: str | None = None, member_count: int | None = None
    ) -> str:
        """
        Build the immutable core persona block.

        Loads core persona from personas/ukrainian_gryag.txt, strips tool
        and memory sections, and adds current time.

        Args:
            chat_name: Optional chat name
            member_count: Optional member count

        Returns:
            Immutable persona block
        """
        # Use SYSTEM_PERSONA as the core persona
        # (personas/ukrainian_gryag.txt can be added later if needed)
        core_persona = SYSTEM_PERSONA

        # Strip tool and memory sections
        # Remove "# Available Tools" section and everything after it
        tools_match = re.search(r"# Available Tools", core_persona, re.IGNORECASE)
        if tools_match:
            core_persona = core_persona[: tools_match.start()].strip()

        # Remove "# Memory Tools" section if it exists separately
        memory_match = re.search(r"# Memory Tools", core_persona, re.IGNORECASE)
        if memory_match:
            core_persona = core_persona[: memory_match.start()].strip()

        # Build immutable block
        sections = [core_persona.strip()]

        # Add current time
        current_time = self._format_current_time()
        sections.append(f"# Current Time\n\nThe current time is: {current_time}")

        # Add chat info if available
        if chat_name:
            sections.append(f"# Chat Information\n\n**Chat Name**: {chat_name}")
            if member_count is not None:
                sections.append(f"**Member Count**: {member_count}")

        return "\n\n".join(sections)

    def build_tools_section(self) -> str:
        """
        Build dynamic tools section based on enabled features.

        Returns:
            Tools section markdown
        """
        tools = []

        # Always include search_messages
        tools.append("- `search_messages` - Search through past conversations")

        # Web search
        if self.settings.enable_web_search:
            tools.append("- `search_web` - Search the web for current information")
            tools.append("- `fetch_web_content` - Fetch content from URLs")

        # Calculator
        tools.append("- `calculator` - Perform mathematical calculations")

        # Weather
        tools.append("- `weather` - Get weather forecasts")

        # Currency
        tools.append("- `currency` - Get exchange rates and conversions")

        # Image generation
        if self.settings.enable_image_generation:
            tools.append("- `generate_image` - Generate images from descriptions")
            tools.append("- `edit_image` - Edit images")

        # Memory tools
        if self.settings.enable_tool_based_memory:
            tools.append("- `recall_memories` - Recall stored memories about users")
            tools.append("- `remember_memory` - Store important facts about users")
            tools.append("- `forget_memory` - Remove specific memories")
            tools.append("- `forget_all_memories` - Remove all memories about a user")
            tools.append("- `set_pronouns` - Store user pronouns")

        if not tools:
            return ""

        return "# Available Tools\n\n" + "\n".join(tools)

    async def build_summaries_section(self, chat_id: int) -> str:
        """
        Build summaries section with 30-day and 7-day summaries.

        Args:
            chat_id: Chat ID

        Returns:
            Summaries section markdown
        """
        sections = []

        # Get 30-day summary
        summary_30 = await self.summary_repository.get_latest_summary(
            chat_id, "30days"
        )
        if summary_30:
            sections.append("## 30-Day Chat Summary\n\n" + summary_30["summary_text"])

        # Get 7-day summary
        summary_7 = await self.summary_repository.get_latest_summary(chat_id, "7days")
        if summary_7:
            sections.append("## 7-Day Chat Summary\n\n" + summary_7["summary_text"])

        if not sections:
            return ""

        return "# Chat History Summaries\n\n" + "\n\n".join(sections)

    def build_immediate_context(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 2000,
        max_media_items: int = 5,
    ) -> str:
        """
        Build immediate chat context with token counting and truncation.

        Args:
            messages: List of message dicts
            max_tokens: Maximum tokens for immediate context
            max_media_items: Maximum media items to include

        Returns:
            Immediate context section markdown
        """
        if not messages:
            return ""

        # Deduplicate messages by message ID or text+timestamp
        seen = set()
        unique_messages = []
        for msg in messages:
            # Create unique key
            msg_id = msg.get("id") or msg.get("external_message_id")
            text = msg.get("text", "")
            ts = msg.get("ts") or msg.get("timestamp", 0)

            if msg_id:
                key = f"id:{msg_id}"
            else:
                key = f"text:{text[:50]}:ts:{ts}"

            if key not in seen:
                seen.add(key)
                unique_messages.append(msg)

        # Sort chronologically (oldest first)
        unique_messages.sort(key=lambda m: m.get("ts") or m.get("timestamp", 0))

        # Truncate to token budget
        truncated = []
        total_tokens = 0
        media_count = 0

        for msg in unique_messages:
            # Estimate tokens for this message
            msg_tokens = estimate_message_tokens(msg)

            # Check media limit
            media_items = msg.get("media", [])
            if isinstance(media_items, str):
                try:
                    import json

                    media_items = json.loads(media_items)
                    if isinstance(media_items, dict):
                        media_items = media_items.get("media", [])
                except Exception:
                    media_items = []

            if isinstance(media_items, list):
                msg_media_count = len(media_items)
            else:
                msg_media_count = 0

            if media_count + msg_media_count > max_media_items:
                # Skip this message if it would exceed media limit
                continue

            if total_tokens + msg_tokens > max_tokens:
                break

            truncated.append(msg)
            total_tokens += msg_tokens
            media_count += msg_media_count

        if not truncated:
            return ""

        # Format messages
        formatted = []
        for msg in truncated:
            role = msg.get("role", "user")
            # Extract text from either direct 'text' field or 'parts' array
            text = msg.get("text", "").strip()
            if not text and "parts" in msg:
                # Extract text from parts array (format from context_store.recent())
                parts = msg.get("parts", [])
                text_parts = [
                    part.get("text", "")
                    for part in parts
                    if isinstance(part, dict) and "text" in part
                ]
                text = " ".join(text_parts).strip()
            ts = msg.get("ts") or msg.get("timestamp", 0)

            # Format timestamp
            if ts:
                dt = time.localtime(ts)
                time_str = time.strftime("%Y-%m-%d %H:%M", dt)
            else:
                time_str = "Unknown"

            # Skip empty messages
            if not text:
                continue
                
            # Format message
            if role == "user":
                sender_name = (
                    msg.get("sender_name")
                    or msg.get("name")
                    or msg.get("username", "User")
                )
                formatted.append(f"[{time_str}] {sender_name}: {text}")
            elif role == "model" or role == "assistant":
                formatted.append(f"[{time_str}] Bot: {text}")
            else:
                formatted.append(f"[{time_str}] {text}")

        return "# Immediate Chat Context\n\n" + "\n".join(formatted)

    def _format_current_time(self) -> str:
        """
        Format current time in Kyiv timezone.

        Returns:
            Formatted time string
        """
        try:
            kyiv_tz = ZoneInfo("Europe/Kiev")
            now = time.time()
            dt = time.localtime(now)
            kyiv_dt = time.localtime(now)
            # Convert to Kyiv timezone
            import datetime

            dt_obj = datetime.datetime.fromtimestamp(now, tz=kyiv_tz)
            return dt_obj.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception as e:
            logger.warning(f"Failed to format Kyiv time: {e}")
            return time.strftime("%Y-%m-%d %H:%M:%S")

    async def assemble_system_instruction(
        self,
        chat_id: int,
        chat_name: str | None = None,
        member_count: int | None = None,
        messages: list[dict[str, Any]] | None = None,
        current_message: dict[str, Any] | None = None,
        replied_to_message: dict[str, Any] | None = None,
    ) -> str:
        """
        Assemble complete system instruction.

        Args:
            chat_id: Chat ID
            chat_name: Optional chat name
            member_count: Optional member count
            messages: Optional recent messages for immediate context
            current_message: Optional current message
            replied_to_message: Optional replied-to message

        Returns:
            Complete system instruction
        """
        sections = []

        # Immutable block
        sections.append(
            self.build_immutable_block(chat_name=chat_name, member_count=member_count)
        )

        # Tools section
        tools_section = self.build_tools_section()
        if tools_section:
            sections.append(tools_section)

        # Summaries section
        summaries_section = await self.build_summaries_section(chat_id)
        if summaries_section:
            sections.append(summaries_section)

        # Immediate context
        if messages:
            immediate_context = self.build_immediate_context(messages)
            if immediate_context:
                sections.append(immediate_context)

        # Replied-to message context (quoted message)
        is_reply = replied_to_message is not None
        if replied_to_message:
            replied_to = self.build_replied_to_context(replied_to_message)
            if replied_to:
                sections.append(replied_to)
                sections.append("")

        # Current message context (indicate if it's a reply/quote)
        if current_message:
            current = self.build_current_message(current_message, is_reply=is_reply)
            sections.append(current)

        return "\n\n".join(sections)

    def build_replied_to_context(self, replied_to_message: dict[str, Any]) -> str:
        """Build replied-to message context (with actual media).

        This represents a QUOTED message that the current message is replying to.
        The current message is a quote/reply to this message.

        Args:
            replied_to_message: Replied-to message dict

        Returns:
            Replied-to context section markdown
        """
        sender_name = (
            replied_to_message.get("sender_name")
            or replied_to_message.get("name")
            or replied_to_message.get("username", "Unknown")
        )
        user_id = replied_to_message.get("user_id") or replied_to_message.get("external_user_id", "?")
        username = replied_to_message.get("username") or replied_to_message.get("sender_username")
        text = replied_to_message.get("text") or replied_to_message.get("content", "").strip()

        username_part = f", `@{username}`" if username else ""

        sections = []
        sections.append("### QUOTED MESSAGE (the message being replied to):")
        sections.append("")
        sections.append(
            f"**Quoted from**: {sender_name} [id`{user_id}`{username_part}]"
        )
        sections.append("")
        sections.append(f"**Quoted text**: `{text}`")
        sections.append("")

        # Note: Actual media will be included in API request, not as text
        if replied_to_message.get("media"):
            sections.append("**Quoted media**: [media parts included in API request]")
            sections.append("")

        return "\n".join(sections)

    def build_current_message(
        self, message: dict[str, Any], is_reply: bool = False
    ) -> str:
        """Build current message section.

        Args:
            message: Current message dict
            is_reply: Whether this message is a reply/quote to another message

        Returns:
            Current message section markdown
        """
        sender_name = (
            message.get("sender_name")
            or message.get("name")
            or message.get("username", "User")
        )
        user_id = message.get("user_id") or message.get("external_user_id", "?")
        username = message.get("username") or message.get("sender_username")
        text = message.get("text") or message.get("content", "").strip()

        username_part = f", `@{username}`" if username else ""

        sections = []
        sections.append("---")
        sections.append("")
        
        # Indicate if this is a reply/quote message
        if is_reply:
            sections.append(
                f"[CURRENT MESSAGE - REPLY/QUOTE] by {sender_name} [id`{user_id}`{username_part}]:"
            )
            sections.append(
                "**Note**: This message is a reply/quote to the message shown above in the QUOTED MESSAGE section."
            )
            sections.append("")
        else:
            sections.append(
                f"[CURRENT MESSAGE] by {sender_name} [id`{user_id}`{username_part}]:"
            )
        
        sections.append(f"`{text}`")
        sections.append("")

        return "\n".join(sections)

