"""Helper functions for persona and response management."""

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def get_response(
    key: str,
    persona_loader: Any | None,
    default: str,
    **kwargs: Any,
) -> str:
    """Get response from PersonaLoader if available, otherwise use default."""
    if persona_loader is not None:
        try:
            persona = getattr(persona_loader, "persona", None)
            bot_name = getattr(persona, "name", None) if persona is not None else None
            bot_display = (
                getattr(persona, "display_name", None) if persona is not None else None
            )
            if bot_name and "bot_name" not in kwargs:
                kwargs["bot_name"] = bot_name
            if bot_display and "bot_display_name" not in kwargs:
                kwargs["bot_display_name"] = bot_display
        except Exception:
            LOGGER.exception(
                "Failed to inject persona variables into response template"
            )

        return persona_loader.get_response(key, **kwargs)

    if kwargs:
        try:
            return default.format(**kwargs)
        except KeyError:
            LOGGER.warning(
                "Missing variable while formatting default response for key=%s", key
            )
    return default

