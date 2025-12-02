"""
Text-to-Speech service for GRYAG bot.

Supports multiple TTS providers with automatic fallback.
Converts text responses to audio for voice messages in Telegram.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import ServerError

from app.services.tts_providers import (
    EdgeTTSProvider,
    FallbackTTSProvider,
    GeminiTTSProvider,
    TTSProvider,
)

# Optional audio conversion support
try:
    from pydub import AudioSegment
    from pydub.utils import which

    PYDUB_AVAILABLE = True
    FFMPEG_AVAILABLE = which("ffmpeg") is not None
except ImportError:
    PYDUB_AVAILABLE = False
    FFMPEG_AVAILABLE = False


class TTSError(Exception):
    """Raised when TTS generation fails."""


class TTSService:
    """Service for generating audio from text with multiple provider support."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash-preview-tts",
        voice: str = "Zephyr",
        language: str = "uk-UA",
        provider: str = "auto",
        edge_tts_voice: str = "uk-UA-PolinaNeural",
    ):
        """
        Initialize TTS service.

        Args:
            api_key: Google Gemini API key (optional if using edge-tts)
            model: TTS model name (default: gemini-2.5-flash-preview-tts)
            voice: Gemini voice name (default: Zephyr)
            language: Language code (default: uk-UA)
            provider: TTS provider: "gemini", "edge-tts", or "auto" (fallback)
            edge_tts_voice: Edge TTS voice name (default: uk-UA-PolinaNeural)
        """
        self.voice = voice
        self.language = language
        self.edge_tts_voice = edge_tts_voice
        self.logger = logging.getLogger(f"{__name__}.TTSService")

        # Initialize providers based on configuration
        providers: list[TTSProvider] = []

        if provider in ("auto", "gemini") and api_key:
            try:
                gemini_provider = GeminiTTSProvider(
                    api_key=api_key,
                    model=model,
                    voice=voice,
                )
                providers.append(gemini_provider)
                self.logger.info("Gemini TTS provider initialized")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Gemini TTS provider: {e}")

        if provider in ("auto", "edge-tts"):
            try:
                edge_provider = EdgeTTSProvider(voice=self.edge_tts_voice)
                if edge_provider.is_available():
                    providers.append(edge_provider)
                    self.logger.info(f"Edge TTS provider initialized with voice: {self.edge_tts_voice}")
                else:
                    self.logger.warning("Edge TTS not available (edge-tts not installed)")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Edge TTS provider: {e}")

        if not providers:
            raise ValueError(
                "No TTS providers available. Install edge-tts (pip install edge-tts) "
                "or provide a Gemini API key."
            )

        # Use fallback provider if multiple, otherwise use single provider
        if len(providers) > 1:
            self.provider: TTSProvider = FallbackTTSProvider(providers)
            self.logger.info(
                f"TTS service initialized with fallback: {len(providers)} providers"
            )
        else:
            self.provider = providers[0]
            self.logger.info(
                f"TTS service initialized with single provider: {providers[0].__class__.__name__}"
            )

    async def generate_audio(self, text: str) -> tuple[bytes, str] | None:
        """
        Generate audio from text using configured TTS provider(s).

        Args:
            text: Text to convert to speech

        Returns:
            Tuple of (audio_bytes, mime_type) or None on failure
        """
        if not text or not text.strip():
            self.logger.warning("Empty text provided for TTS generation")
            return None

        self.logger.info(f"Generating TTS audio: text_length={len(text)}")

        try:
            # Use the provider (which handles fallback if configured)
            audio_result = await self.provider.generate_audio(text, self.language)
            if audio_result:
                audio_bytes, mime_type = audio_result
                self.logger.info(
                    f"TTS generation successful: audio_size={len(audio_bytes)}, "
                    f"mime_type={mime_type}"
                )
                return audio_result
            else:
                self.logger.warning("TTS provider returned no audio")
                return None

        except Exception as e:
            error_str = str(e).lower()
            # Check if it's a quota error
            is_quota_error = (
                "429" in error_str
                or "quota" in error_str
                or "resource_exhausted" in error_str
            )

            if is_quota_error:
                error_msg = (
                    "TTS quota exceeded. Free tier allows 15 requests per day. "
                    "Please try again later or upgrade to paid tier."
                )
                self.logger.warning(f"TTS quota error: {e}")
                raise TTSError(error_msg) from e

            self.logger.error(f"TTS generation failed: {e}", exc_info=True)
            raise TTSError(f"TTS generation failed: {e}") from e

    def convert_audio_to_ogg(self, audio_bytes: bytes, input_format: str) -> bytes:
        """
        Convert audio bytes to OGG/Opus format for Telegram voice messages.

        Args:
            audio_bytes: Input audio bytes
            input_format: Input format (e.g., "mp3", "wav", "mpeg")

        Returns:
            OGG/Opus encoded audio bytes

        Raises:
            TTSError: If conversion fails or pydub/ffmpeg not available
        """
        if not PYDUB_AVAILABLE:
            raise TTSError(
                "pydub is required for audio conversion. Install with: pip install pydub"
            )
        if not FFMPEG_AVAILABLE:
            raise TTSError(
                "ffmpeg is required for audio conversion. Install ffmpeg system package."
            )

        try:
            # Determine input format
            format_map = {
                "mp3": "mp3",
                "mpeg": "mp3",
                "wav": "wav",
                "aac": "aac",
                "ogg": "ogg",
                "opus": "ogg",
            }
            input_fmt = format_map.get(input_format.lower(), input_format.lower())

            # Load audio
            audio = AudioSegment.from_file(
                io.BytesIO(audio_bytes), format=input_fmt
            )

            # Export as OGG/Opus
            output = io.BytesIO()
            audio.export(output, format="ogg", codec="libopus")
            output.seek(0)
            return output.read()
        except Exception as e:
            self.logger.error(f"Audio conversion failed: {e}", exc_info=True)
            raise TTSError(f"Failed to convert audio to OGG: {e}") from e

