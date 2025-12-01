"""
Text-to-Speech service for GRYAG bot.

Provides TTS using Gemini 2.5 Flash Preview TTS model.
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
    """Service for generating audio from text using Gemini TTS API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash-preview-tts",
        voice: str = "Zephyr",
        language: str = "uk-UA",
    ):
        """
        Initialize TTS service.

        Args:
            api_key: Google Gemini API key
            model: TTS model name (default: gemini-2.5-flash-preview-tts)
            voice: Voice name (default: Zephyr)
            language: Language code (default: uk-UA)
        """
        if not api_key:
            raise ValueError("api_key is required for TTS service")
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.voice = voice
        self.language = language
        self.logger = logging.getLogger(f"{__name__}.TTSService")
        self.logger.info(
            f"TTS service initialized: model={model}, voice={voice}, language={language}"
        )

    async def generate_audio(self, text: str) -> tuple[bytes, str] | None:
        """
        Generate audio from text using Gemini TTS API.

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
            # Build content with text (using standard format)
            contents = [{"role": "user", "parts": [{"text": text}]}]

            # Configure TTS generation
            # Note: The exact API format may vary - this is based on standard generateContent
            # If Gemini TTS uses a different format, this will need adjustment
            config_params: dict[str, Any] = {
                "response_modalities": ["Audio"],  # Request audio response
            }

            # Try to add audio config if available (similar to image_config for images)
            # Voice and language might need to be in audio_config or passed differently
            try:
                # Check if AudioConfig exists in types (may not be available in all SDK versions)
                if hasattr(types, "AudioConfig"):
                    audio_config = types.AudioConfig(
                        voice=self.voice,
                        language_code=self.language,
                    )
                    config_params["audio_config"] = audio_config
                    self.logger.debug(
                        f"Using AudioConfig: voice={self.voice}, language={self.language}"
                    )
            except Exception as e:
                self.logger.debug(
                    f"AudioConfig not available or failed to create: {e}. "
                    "Using basic response_modalities only."
                )

            config = types.GenerateContentConfig(**config_params)
            self.logger.debug(
                f"TTS request config: response_modalities={config_params.get('response_modalities')}, "
                f"has_audio_config={'audio_config' in config_params}"
            )

            # Generate audio with timeout (30 seconds max for TTS) and retry logic for server errors
            server_error_retries = 3
            last_server_exc: Exception | None = None
            
            for retry in range(server_error_retries):
                try:
                    response = await asyncio.wait_for(
                        self.client.aio.models.generate_content(
                            model=self.model,
                            contents=contents,
                            config=config,
                        ),
                        timeout=30.0,
                    )
                    break  # Success, exit retry loop
                except TimeoutError as e:
                    self.logger.error("TTS generation timed out after 30 seconds")
                    raise TTSError("TTS generation timed out") from e
                except Exception as e:
                    error_str = str(e).lower()
                    
                    # Check if it's a quota error (429)
                    is_quota_error = (
                        "429" in error_str
                        or "quota" in error_str
                        or "resource_exhausted" in error_str
                        or "rate limit" in error_str
                    )
                    
                    # Check if it's a server error (503, 500, etc.)
                    is_server_error = isinstance(e, ServerError) or any(
                        keyword in error_str
                        for keyword in ["503", "500", "unavailable", "overloaded", "servererror"]
                    )
                    
                    # Handle quota errors - extract retry delay from error if available
                    if is_quota_error:
                        # Try to extract retry delay from error message
                        retry_delay = 10.0  # Default 10 seconds
                        try:
                            import re
                            delay_match = re.search(r"retry in ([\d.]+)s", error_str, re.IGNORECASE)
                            if delay_match:
                                retry_delay = float(delay_match.group(1)) + 1.0  # Add 1s buffer
                        except Exception:
                            pass
                        
                        self.logger.warning(
                            f"TTS quota exceeded (429), retry {retry + 1}/{server_error_retries} "
                            f"after {retry_delay:.1f}s. Free tier limit: 15 requests/day."
                        )
                        if retry < server_error_retries - 1:
                            await asyncio.sleep(retry_delay)
                            last_server_exc = e
                            continue
                        else:
                            # Quota exhausted after retries
                            raise TTSError(
                                "TTS quota exceeded. Free tier allows 15 requests per day. "
                                "Please try again later or upgrade to paid tier."
                            ) from e
                    
                    # Handle server errors
                    if is_server_error and retry < server_error_retries - 1:
                        # Exponential backoff: 1s, 2s, 4s
                        backoff = 2**retry
                        self.logger.warning(
                            f"TTS server error (503/500), retry {retry + 1}/{server_error_retries} "
                            f"after {backoff}s: {e}"
                        )
                        await asyncio.sleep(backoff)
                        last_server_exc = e
                        continue
                    else:
                        # Not a retryable error or last retry failed
                        raise
            
            # If we exhausted retries due to server errors
            if last_server_exc:
                self.logger.error(
                    f"TTS generation failed after {server_error_retries} retries: {last_server_exc}"
                )
                raise TTSError(
                    "TTS service is temporarily unavailable. Please try again later."
                ) from last_server_exc

            # Extract audio from response
            audio_result = self._extract_audio_from_response(response)
            if audio_result:
                audio_bytes, mime_type = audio_result
                self.logger.info(
                    f"TTS generation successful: audio_size={len(audio_bytes)}, "
                    f"mime_type={mime_type}"
                )
                return audio_result
            else:
                self.logger.warning("No audio found in TTS response")
                return None

        except TTSError:
            raise
        except Exception as e:
            self.logger.error(f"TTS generation failed: {e}", exc_info=True)
            raise TTSError(f"TTS generation failed: {e}") from e

    def _extract_audio_from_response(self, response: Any) -> tuple[bytes, str] | None:
        """
        Extract audio data from Gemini TTS response.

        Args:
            response: Gemini API response object

        Returns:
            Tuple of (audio_bytes, mime_type) or None if not found
        """
        try:
            candidates = getattr(response, "candidates", None) or []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if not content:
                    continue
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    # Check for inline_data with audio MIME type
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data:
                        mime_type = getattr(inline_data, "mime_type", "")
                        data = getattr(inline_data, "data", "")
                        if mime_type.startswith("audio/") and data:
                            try:
                                audio_bytes = base64.b64decode(data)
                                return (audio_bytes, mime_type)
                            except Exception as e:
                                self.logger.warning(
                                    f"Failed to decode audio data: {e}"
                                )
                                continue

                    # Alternative: Check for file_data (if Gemini uses file URIs)
                    file_data = getattr(part, "file_data", None)
                    if file_data:
                        uri = getattr(file_data, "file_uri", None)
                        if uri:
                            self.logger.warning(
                                "TTS returned file URI instead of inline data - "
                                "file URI handling not implemented"
                            )

            return None
        except Exception as e:
            self.logger.error(f"Error extracting audio from response: {e}", exc_info=True)
            return None

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

