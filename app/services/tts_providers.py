"""TTS provider implementations for different backends.

Supports multiple TTS providers with fallback capability.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class TTSProvider(ABC):
    """Abstract base class for TTS providers."""

    @abstractmethod
    async def generate_audio(self, text: str, language: str = "uk-UA") -> tuple[bytes, str] | None:
        """
        Generate audio from text.

        Args:
            text: Text to convert to speech
            language: Language code (default: uk-UA)

        Returns:
            Tuple of (audio_bytes, mime_type) or None on failure
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available."""
        pass


class GeminiTTSProvider(TTSProvider):
    """Gemini TTS provider implementation."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash-tts",
        voice: str = "Zephyr",
    ):
        """Initialize Gemini TTS provider."""
        from google import genai
        from google.genai import types

        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.voice = voice
        self.types = types
        self.logger = logging.getLogger(f"{__name__}.GeminiTTSProvider")

    async def generate_audio(self, text: str, language: str = "uk-UA") -> tuple[bytes, str] | None:
        """Generate audio using Gemini TTS."""
        if not text or not text.strip():
            return None

        try:
            contents = [{"role": "user", "parts": [{"text": text}]}]
            config_params: dict[str, Any] = {
                "response_modalities": ["Audio"],
            }

            try:
                if hasattr(self.types, "AudioConfig"):
                    audio_config = self.types.AudioConfig(
                        voice=self.voice,
                        language_code=language,
                    )
                    config_params["audio_config"] = audio_config
            except Exception:
                pass

            config = self.types.GenerateContentConfig(**config_params)

            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                ),
                timeout=30.0,
            )

            # Extract audio from response
            candidates = getattr(response, "candidates", None) or []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if not content:
                    continue

                parts = getattr(content, "parts", None) or []
                for part in parts:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data:
                        mime_type = getattr(inline_data, "mime_type", "")
                        data = getattr(inline_data, "data", "")

                        if mime_type.startswith("audio/") and data:
                            if isinstance(data, bytes):
                                return (data, mime_type)
                            else:
                                audio_bytes = base64.b64decode(data)
                                if audio_bytes:
                                    return (audio_bytes, mime_type)

            return None
        except Exception as e:
            self.logger.error(f"Gemini TTS generation failed: {e}", exc_info=True)
            raise

    def is_available(self) -> bool:
        """Check if Gemini TTS is available."""
        return self.client is not None


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge TTS provider (free, no API key required)."""

    def __init__(self, voice: str = "uk-UA-PolinaNeural"):
        """
        Initialize Edge TTS provider.

        Args:
            voice: Voice name (default: uk-UA-PolinaNeural for Ukrainian)
        """
        self.voice = voice
        self.logger = logging.getLogger(f"{__name__}.EdgeTTSProvider")
        self._available = None

    async def generate_audio(self, text: str, language: str = "uk-UA") -> tuple[bytes, str] | None:
        """Generate audio using Edge TTS."""
        try:
            import edge_tts
        except ImportError:
            self.logger.error(
                "edge-tts not installed. Install with: pip install edge-tts"
            )
            return None

        if not text or not text.strip():
            return None

        try:
            # Use the configured voice directly (set via EDGE_TTS_VOICE env var)
            # The voice is already set in __init__ from the configuration
            voice_name = self.voice
            self.logger.debug(f"Using Edge TTS voice: {voice_name} (configured via EDGE_TTS_VOICE)")

            # Generate audio
            communicate = edge_tts.Communicate(text, voice_name)
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]

            if audio_data:
                # Edge TTS returns MP3 format
                return (audio_data, "audio/mpeg")
            return None
        except Exception as e:
            self.logger.error(f"Edge TTS generation failed: {e}", exc_info=True)
            return None

    def is_available(self) -> bool:
        """Check if Edge TTS is available."""
        if self._available is None:
            try:
                import edge_tts
                self._available = True
            except ImportError:
                self._available = False
        return self._available


class FallbackTTSProvider(TTSProvider):
    """TTS provider with fallback support."""

    def __init__(self, providers: list[TTSProvider]):
        """
        Initialize fallback TTS provider.

        Args:
            providers: List of TTS providers to try in order
        """
        self.providers = providers
        self.logger = logging.getLogger(f"{__name__}.FallbackTTSProvider")

    async def generate_audio(self, text: str, language: str = "uk-UA") -> tuple[bytes, str] | None:
        """Generate audio using first available provider."""
        last_error: Exception | None = None

        for provider in self.providers:
            if not provider.is_available():
                self.logger.debug(f"Provider {provider.__class__.__name__} not available, skipping")
                continue

            try:
                self.logger.info(f"Trying TTS provider: {provider.__class__.__name__}")
                result = await provider.generate_audio(text, language)
                if result:
                    self.logger.info(
                        f"Successfully generated audio using {provider.__class__.__name__}"
                    )
                    return result
            except Exception as e:
                self.logger.warning(
                    f"Provider {provider.__class__.__name__} failed: {e}, "
                    "trying next provider"
                )
                last_error = e
                continue

        # All providers failed
        if last_error:
            raise last_error
        return None

    def is_available(self) -> bool:
        """Check if any provider is available."""
        return any(provider.is_available() for provider in self.providers)

