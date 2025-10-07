"""Base persona configuration classes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdminUser:
    """Configuration for an admin user with special status."""

    user_id: int
    name: str
    display_name: str | None = None
    special_status: str | None = None  # admin, creator, admin_beloved, etc.

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdminUser:
        """Create AdminUser from dictionary."""
        return cls(
            user_id=int(data["user_id"]),
            name=data["name"],
            display_name=data.get("display_name"),
            special_status=data.get("special_status"),
        )


@dataclass
class PersonaConfig:
    """Configuration for a bot personality.

    This class holds all the configuration needed to define a bot's personality,
    including its name, language, system prompt, admin users, and behavior settings.
    """

    # Basic identity
    name: str = "gryag"
    display_name: str = "гряг"
    language: str = "uk"

    # System prompt and templates
    system_prompt: str = ""
    system_prompt_template_path: str | None = None

    # Trigger patterns (regex)
    trigger_patterns: list[str] = field(default_factory=list)

    # Admin users
    admin_users: list[AdminUser] = field(default_factory=list)

    # Response templates
    response_templates_path: str | None = None
    response_templates: dict[str, str] = field(default_factory=dict)

    # Behavior settings
    allow_profanity: bool = True
    sarcasm_level: str = "high"  # low, medium, high
    humor_style: str = "dark"  # light, dark, dry, sarcastic

    # Metadata
    version: str = "1.0"
    description: str = ""

    def get_admin_user(self, user_id: int) -> AdminUser | None:
        """Get admin user configuration by user ID."""
        for admin in self.admin_users:
            if admin.user_id == user_id:
                return admin
        return None

    def is_admin_user(self, user_id: int) -> bool:
        """Check if user ID is an admin."""
        return any(admin.user_id == user_id for admin in self.admin_users)

    def get_admin_display_name(self, user_id: int) -> str | None:
        """Get display name for an admin user."""
        admin = self.get_admin_user(user_id)
        return admin.display_name if admin else None

    def get_trigger_pattern_regex(self) -> str | None:
        """Get combined regex pattern for triggers."""
        if not self.trigger_patterns:
            return None
        # Join patterns with OR operator
        return "|".join(f"({pattern})" for pattern in self.trigger_patterns)
