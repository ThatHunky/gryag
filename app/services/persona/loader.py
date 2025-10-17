"""Persona loader for loading and managing bot personas."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from app.services.persona.base import AdminUser, PersonaConfig

LOGGER = logging.getLogger(__name__)


class PersonaLoader:
    """Loads and manages bot persona configurations.

    This class is responsible for loading persona configurations from YAML files,
    response templates from JSON files, and providing template substitution for
    dynamic responses.
    """

    def __init__(
        self,
        persona_config_path: str | None = None,
        response_templates_path: str | None = None,
    ):
        """Initialize persona loader.

        Args:
            persona_config_path: Path to persona YAML file. If None, uses default config.
            response_templates_path: Path to response templates JSON. If None, uses default responses.
        """
        self.persona: PersonaConfig
        self.response_templates: dict[str, str] = {}

        if persona_config_path:
            self.persona = self._load_persona_from_yaml(persona_config_path)
        else:
            # Use default hardcoded persona for backwards compatibility
            self.persona = self._get_default_persona()

        if response_templates_path:
            self.response_templates = self._load_response_templates(
                response_templates_path
            )
        elif self.persona.response_templates_path:
            self.response_templates = self._load_response_templates(
                self.persona.response_templates_path
            )
        else:
            # Use default hardcoded responses
            self.response_templates = self._get_default_responses()

    def _load_persona_from_yaml(self, yaml_path: str) -> PersonaConfig:
        """Load persona configuration from YAML file."""
        try:
            path = Path(yaml_path)
            if not path.exists():
                LOGGER.warning(
                    f"Persona config file not found: {yaml_path}. Using default persona."
                )
                return self._get_default_persona()

            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            # Parse admin users
            admin_users = []
            if "admin_users" in data:
                for admin_data in data["admin_users"]:
                    admin_users.append(AdminUser.from_dict(admin_data))

            # Load system prompt from template file if specified
            system_prompt = data.get("system_prompt", "")
            if "system_prompt_template" in data:
                template_path = Path(data["system_prompt_template"])
                if template_path.exists():
                    with open(template_path, "r", encoding="utf-8") as f:
                        system_prompt = f.read()
                else:
                    LOGGER.warning(
                        f"System prompt template not found: {data['system_prompt_template']}"
                    )

            return PersonaConfig(
                name=data.get("name", "gryag"),
                display_name=data.get("display_name", "гряг"),
                language=data.get("language", "uk"),
                system_prompt=system_prompt,
                system_prompt_template_path=data.get("system_prompt_template"),
                trigger_patterns=data.get("trigger_patterns", []),
                admin_users=admin_users,
                response_templates_path=data.get("response_templates"),
                allow_profanity=data.get("allow_profanity", True),
                sarcasm_level=data.get("sarcasm_level", "high"),
                humor_style=data.get("humor_style", "dark"),
                version=data.get("version", "1.0"),
                description=data.get("description", ""),
            )

        except Exception as e:
            LOGGER.error(f"Error loading persona from {yaml_path}: {e}")
            return self._get_default_persona()

    def _load_response_templates(self, json_path: str) -> dict[str, str]:
        """Load response templates from JSON file."""
        try:
            path = Path(json_path)
            if not path.exists():
                LOGGER.warning(
                    f"Response templates file not found: {json_path}. Using default responses."
                )
                return self._get_default_responses()

            with open(path, "r", encoding="utf-8") as f:
                templates = json.load(f)

            return templates

        except Exception as e:
            LOGGER.error(f"Error loading response templates from {json_path}: {e}")
            return self._get_default_responses()

    def _get_default_persona(self) -> PersonaConfig:
        """Get default hardcoded persona for backwards compatibility."""
        from app.persona import SYSTEM_PERSONA

        # Default admin users (from current hardcoded persona)
        default_admins = [
            AdminUser(
                user_id=831570515,
                name="кавунева пітса",
                display_name="кавунева пітса #Я_З_ТОМАТОМ_СПАЙСІ 🍻△✙➔",
                special_status="admin_beloved",
            ),
            AdminUser(
                user_id=392817811,
                name="Всеволод Добровольський",
                display_name="батько",
                special_status="creator",
            ),
        ]

        # Default trigger pattern (from current hardcoded triggers)
        default_triggers = [r"\b(?:гр[яи]г[аоуеєіїюяьґ]*|gr[yi]ag\w*)\b"]

        return PersonaConfig(
            name="gryag",
            display_name="гряг",
            language="uk",
            system_prompt=SYSTEM_PERSONA,
            trigger_patterns=default_triggers,
            admin_users=default_admins,
            allow_profanity=True,
            sarcasm_level="high",
            humor_style="dark",
            description="Default Ukrainian sarcastic bot personality",
        )

    def _get_default_responses(self) -> dict[str, str]:
        """Get default hardcoded responses for backwards compatibility."""
        return {
            "error_fallback": "Ґеміні знову тупить. Спробуй пізніше.",
            "empty_reply": "Скажи конкретніше, бо зараз з цього нічого не зробити.",
            "banned_reply": "Ти для {bot_name} в бані. Йди погуляй.",
            "snarky_reply": "Пригальмуй, балакучий...",
            "throttle_notice": "Занадто багато повідомлень. Почекай {minutes} хв.",
            "admin_only": "Ця команда лише для своїх. І явно не для тебе.",
            "chat_not_allowed": "Я тут не працюю.",
            # Admin responses
            "ban_success": "Готово: користувача кувалдіровано.",
            "unban_success": "Ок, розбанив. Нехай знову пиздить.",
            "already_banned": "Та він і так у бані сидив.",
            "not_banned": "Нема кого розбанювати — список чистий.",
            "missing_target": "Покажи, кого саме прибрати: зроби реплай або передай ID.",
            "reset_done": "Все, обнулив ліміти. Можна знову розганяти балачки.",
        }

    def get_system_prompt(self, **kwargs: Any) -> str:
        """Get system prompt with optional variable substitution.

        Args:
            **kwargs: Variables for template substitution (e.g., current_time, bot_name)

        Returns:
            System prompt string with variables substituted
        """
        prompt = self.persona.system_prompt

        # Simple variable substitution using format
        try:
            if kwargs:
                prompt = prompt.format(**kwargs)
        except KeyError as e:
            LOGGER.warning(f"Missing variable in system prompt template: {e}")

        return prompt

    def get_response(self, key: str, **kwargs: Any) -> str:
        """Get localized response with variable substitution.

        Args:
            key: Response template key (e.g., 'error_fallback', 'banned_reply')
            **kwargs: Variables for template substitution (e.g., bot_name, seconds)

        Returns:
            Response string with variables substituted
        """
        template = self.response_templates.get(key, "")

        if not template:
            # Fallback to default if key not found
            LOGGER.warning(f"Response template not found: {key}")
            default_responses = self._get_default_responses()
            template = default_responses.get(key, "")

        # Variable substitution
        try:
            if kwargs:
                template = template.format(**kwargs)
        except KeyError as e:
            LOGGER.warning(f"Missing variable in response template '{key}': {e}")

        return template

    def get_trigger_patterns(self) -> list[str]:
        """Get list of trigger regex patterns."""
        return self.persona.trigger_patterns

    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin."""
        return self.persona.is_admin_user(user_id)

    def get_admin_info(self, user_id: int) -> AdminUser | None:
        """Get admin user information."""
        return self.persona.get_admin_user(user_id)
