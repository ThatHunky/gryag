from __future__ import annotations

import base64
import asyncio
import inspect
import json
import logging
import random
import time
from typing import Any, Awaitable, Callable, Iterable, cast

from google import genai
from google.genai import types

from app.services import telemetry
from app.services.embedding_cache import EmbeddingCache
from app.services.media import MAX_INLINE_SIZE


class _KeyPool:
    """Round-robin pool for rotating Gemini API keys with cooldowns."""

    def __init__(
        self, keys: list[str], cooldown_seconds: float, quota_block_seconds: float
    ) -> None:
        self._keys = list(keys)
        self._cooldown_seconds = cooldown_seconds
        self._quota_block_seconds = quota_block_seconds
        self._cooldowns: dict[str, float] = {}
        self._index = random.randrange(len(self._keys)) if self._keys else 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> str | None:
        async with self._lock:
            if not self._keys:
                return None
            now = time.time()
            total = len(self._keys)
            for _ in range(total):
                key = self._keys[self._index % total]
                self._index += 1
                if self._cooldowns.get(key, 0.0) <= now:
                    return key
            return None

    async def mark_quota(self, key: str, block_seconds: float | None = None) -> None:
        async with self._lock:
            base = block_seconds or self._quota_block_seconds or self._cooldown_seconds
            jitter = random.uniform(0.05, 0.15) * base
            self._cooldowns[key] = time.time() + base + jitter


class GeminiError(Exception):
    """Raised when Gemini generation fails."""


class GeminiContentBlockedError(GeminiError):
    """Raised when Gemini blocks content due to policy violations."""

    def __init__(
        self, message: str, block_reason: str | None = None, safety_ratings: Any = None
    ):
        super().__init__(message)
        self.block_reason = block_reason
        self.safety_ratings = safety_ratings


class GeminiClient:
    """Async wrapper around Google Gemini models."""

    def __init__(
        self,
        api_key: str,
        model: str,
        embed_model: str,
        embedding_cache: EmbeddingCache | None = None,
        *,
        api_keys: list[str] | None = None,
        free_tier_mode: bool = False,
        key_cooldown_seconds: float = 120.0,
        quota_block_seconds: float = 86400.0,
        enable_thinking: bool = False,
    ) -> None:
        provided_keys = [k.strip() for k in (api_keys or []) if k and k.strip()]
        if api_key:
            primary = api_key.strip()
            keys = [primary] + [k for k in provided_keys if k != primary]
        else:
            keys = provided_keys

        if not keys:
            raise ValueError("Gemini API key is required")

        self._api_keys = keys
        self._primary_key = keys[0]
        self._free_tier_mode = free_tier_mode and len(keys) > 1
        self._key_cooldown_seconds = key_cooldown_seconds
        self._quota_block_seconds = quota_block_seconds
        self._enable_thinking = enable_thinking
        self._key_pool = (
            _KeyPool(keys, key_cooldown_seconds, quota_block_seconds)
            if self._free_tier_mode
            else None
        )
        self._clients: dict[str, genai.Client] = {}
        self._client = self._get_or_create_client(self._primary_key)
        self._model = None  # Not needed in new SDK - we call client.models.generate_content directly
        self._model_name = model
        self._embed_model = embed_model
        self._embedding_cache = embedding_cache
        self._logger = logging.getLogger(__name__)
        self._search_grounding_supported = True

        # Model capability detection
        self._audio_supported = self._detect_audio_support(model)
        self._video_supported = self._detect_video_support(model)
        self._tools_supported = self._detect_tools_support(model)

        # New SDK supports system_instruction by default
        self._system_instruction_supported = True
        self._generate_timeout = 45.0
        self._max_failures = 3
        self._cooldown_seconds = 60.0
        self._failure_count = 0
        self._circuit_open_until = 0.0
        self._embed_semaphore = asyncio.Semaphore(8)
        self._tools_fallback_disabled = (
            False  # Track if tools were disabled in last call
        )
        # Gemini 1.5 renamed some safety categories and dropped the SafetySetting class
        # Safety settings for new SDK
        self._safety_settings = [
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
        ]

        if self._free_tier_mode:
            self._logger.info(
                "Gemini free-tier rotation enabled with %d API keys (%.1f h quota cooldown)",
                len(self._api_keys),
                self._quota_block_seconds / 3600 if self._quota_block_seconds else 0.0,
            )

    def _get_or_create_client(self, key: str) -> genai.Client:
        client = self._clients.get(key)
        if client is None:
            client = genai.Client(api_key=key)
            self._clients[key] = client
        return client

    async def _acquire_client(self) -> tuple[genai.Client, str]:
        if not self._key_pool:
            return self._client, self._primary_key

        attempts = len(self._api_keys)
        for _ in range(attempts):
            key = await self._key_pool.acquire()
            if key:
                return self._get_or_create_client(key), key

        await asyncio.sleep(1.0)
        key = await self._key_pool.acquire()
        if not key:
            raise GeminiError("All Gemini API keys are cooling down due to quota hits")
        return self._get_or_create_client(key), key

    async def _mark_quota(self, key: str) -> None:
        if self._key_pool:
            await self._key_pool.mark_quota(key, self._quota_block_seconds)
            cooldown = self._quota_block_seconds or self._key_cooldown_seconds
            hours = cooldown / 3600 if cooldown else 0
            self._logger.warning(
                "Gemini key rotated off due to quota exhaustion; cooling for %.1f hours",
                hours,
            )

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        message = f"{type(exc).__name__} {exc}".lower()
        return (
            "429" in message
            or "quota" in message
            or "rate limit" in message
            or "resourceexhausted" in message
        )

    @staticmethod
    def _detect_audio_support(model_name: str) -> bool:
        """
        Detect if the model supports audio input.

        Gemma models don't support audio. Most Gemini models do.
        """
        model_lower = model_name.lower()
        # Gemma models (all variants) don't support audio
        if "gemma" in model_lower:
            return False
        # Gemini Pro Vision and Flash (1.5+) support audio
        if "gemini" in model_lower:
            return True
        # Default to False for unknown models
        return False

    @staticmethod
    def _detect_video_support(model_name: str) -> bool:
        """
        Detect if the model supports video input.

        Gemma models have limited video support (YouTube URLs only via file_uri).
        Gemini 1.5+ and Gemini Flash models support video.
        """
        model_lower = model_name.lower()
        # Gemma supports YouTube URLs but not inline video
        if "gemma" in model_lower:
            return False  # No inline video support
        # Gemini Flash models (2.0-based) support video
        if "gemini" in model_lower and "flash" in model_lower:
            return True
        # Gemini 1.5+ supports video
        if "gemini" in model_lower and ("1.5" in model_lower or "2." in model_lower):
            return True
        # Default to False for unknown models
        return False

    @staticmethod
    def _detect_tools_support(model_name: str) -> bool:
        """
        Detect if the model supports function calling (tools).

        Gemma models don't support function calling. Gemini models do.
        """
        model_lower = model_name.lower()
        # Gemma models (all variants) don't support function calling
        if "gemma" in model_lower:
            return False
        # Gemini models support function calling
        if "gemini" in model_lower:
            return True
        # Default to True for unknown models (safer to try and fallback)
        return True

    def _filter_tools(
        self, tools: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        if not tools:
            return None

        # If model doesn't support tools at all, return None
        if not self._tools_supported:
            if tools:
                self._logger.info(
                    f"Function calling not supported by model {self._model_name} - disabling {len(tools)} tool(s)",
                )
            return None

        # Filter out search grounding if not supported
        if self._search_grounding_supported:
            return tools
        filtered: list[dict[str, Any]] = []
        for item in tools:
            if isinstance(item, dict) and any(
                key in item for key in ("google_search", "google_search_retrieval")
            ):
                continue
            filtered.append(item)
        return filtered

    def _maybe_disable_search_grounding(self, error_message: str) -> bool:
        if (
            "Search Grounding is not supported" in error_message
            and self._search_grounding_supported
        ):
            self._search_grounding_supported = False
            self._logger.warning(f"Disabling search grounding tools: {error_message}")
            return True
        return False

    def _maybe_disable_tools(self, error_message: str) -> bool:
        """
        Detect and disable function calling if not supported.

        Returns True if tools were disabled, False otherwise.
        """
        if (
            "Function calling is not enabled" in error_message
            or "function_calling is not enabled" in error_message.lower()
        ) and self._tools_supported:
            self._tools_supported = False
            self._logger.warning(
                f"Function calling not supported by model {self._model_name} - disabling tools",
            )
            return True
        return False

    def _ensure_circuit(self) -> None:
        if self._circuit_open_until and time.time() < self._circuit_open_until:
            telemetry.increment_counter("gemini.circuit_block")
            raise GeminiError("Gemini temporarily unavailable (cooling down)")

    def _record_failure(self) -> None:
        self._failure_count += 1
        telemetry.increment_counter("gemini.failure")
        if self._failure_count >= self._max_failures:
            self._circuit_open_until = time.time() + self._cooldown_seconds
            self._failure_count = 0
            telemetry.increment_counter("gemini.circuit_open")
            self._logger.warning(
                "Gemini circuit opened for %.0f seconds after repeated failures",
                self._cooldown_seconds,
            )

    def _record_success(self) -> None:
        self._failure_count = 0
        self._circuit_open_until = 0.0
        telemetry.increment_counter("gemini.success")

    @property
    def tools_fallback_disabled(self) -> bool:
        """Check if tools were disabled during the last API call due to errors."""
        return self._tools_fallback_disabled

    async def _invoke_model(
        self,
        contents: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system_instruction: str | None,
    ) -> Any:
        # Build config with all parameters at once
        # The new SDK requires tools to be wrapped in types.Tool objects
        config_params: dict[str, Any] = {
            "safety_settings": self._safety_settings,
        }

        if self._enable_thinking:
            config_params["thinking_config"] = types.ThinkingConfig(
                include_thoughts=True
            )

        if system_instruction and self._system_instruction_supported:
            config_params["system_instruction"] = system_instruction

        if tools:
            # Convert tool dictionaries to types.Tool objects
            # All tools are now function_declarations (including search_web)
            converted_tools = []
            for tool_dict in tools:
                if "function_declarations" in tool_dict:
                    converted_tools.append(types.Tool(**tool_dict))

            if converted_tools:
                config_params["tools"] = converted_tools
                self._logger.debug(f"Using {len(converted_tools)} function tools")

        config = types.GenerateContentConfig(**config_params)

        attempts = len(self._api_keys) if self._free_tier_mode else 1
        last_quota_exc: Exception | None = None

        for _ in range(max(1, attempts)):
            client, key = await self._acquire_client()
            try:
                # New SDK uses client.models.generate_content (async by default)
                payload = cast(types.ContentListUnionDict, contents)
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=self._model_name,
                        contents=payload,
                        config=config,
                    ),
                    timeout=self._generate_timeout,
                )
                return response
            except asyncio.TimeoutError as exc:
                raise GeminiError("Gemini request timed out") from exc
            except Exception as exc:
                if self._is_quota_error(exc):
                    await self._mark_quota(key)
                    last_quota_exc = exc
                    continue
                raise

        if last_quota_exc:
            raise last_quota_exc

        raise GeminiError("Gemini request failed after rotating API keys")

    def build_media_parts(
        self,
        media_items: Iterable[dict[str, Any]],
        logger: logging.Logger | None = None,
    ) -> list[dict[str, Any]]:
        """
        Convert media items to Gemini API format.

        Supports:
        - Inline data (base64 encoded bytes) for files <20MB
        - File URIs for YouTube URLs

        Filters out unsupported media types based on model capabilities.

        Args:
            media_items: List of dicts with either:
                - 'bytes' + 'mime': Regular file content
                - 'file_uri': YouTube URL or uploaded file reference
            logger: Optional logger for debugging

        Returns:
            List of parts in Gemini API format
        """
        parts: list[dict[str, Any]] = []
        filtered_count = 0
        skipped_oversize = 0

        for item in media_items:
            # YouTube URLs or Files API references
            if "file_uri" in item:
                file_uri = item["file_uri"]
                if file_uri:
                    parts.append({"file_data": {"file_uri": file_uri}})
                    if logger:
                        logger.debug(f"Added file_uri media: {file_uri}")
                continue

            # Regular inline data (base64 encoded)
            blob = item.get("bytes")
            mime = item.get("mime")
            kind = item.get("kind", "unknown")
            size = item.get("size", 0)

            if not blob or not mime:
                continue

            # Enforce inline size limit defensively
            if size and size > MAX_INLINE_SIZE:
                skipped_oversize += 1
                if logger:
                    logger.info(
                        f"Skipping oversize media item: kind={kind} mime={mime} size={size}",
                    )
                continue

            # Filter unsupported media types
            if not self._is_media_supported(mime, kind):
                filtered_count += 1
                if logger:
                    logger.info(
                        f"Filtered unsupported media: mime={mime}, kind={kind} (model: {self._model_name})",
                    )
                continue

            data = base64.b64encode(blob).decode("ascii")
            parts.append({"inline_data": {"mime_type": mime, "data": data}})
            if logger:
                logger.debug(
                    f"Added inline media: mime={mime}, kind={kind}, size={size} bytes, base64_len={len(data)}",
                )

        if logger and (filtered_count > 0 or skipped_oversize > 0):
            if filtered_count > 0:
                logger.warning(
                    f"Filtered {filtered_count} unsupported media item(s) for model {self._model_name}",
                )
            if skipped_oversize > 0:
                logger.warning(
                    f"Skipped {skipped_oversize} oversize media item(s) (> {MAX_INLINE_SIZE} bytes)",
                )

        return parts

    def _is_media_supported(self, mime: str, kind: str) -> bool:
        """
        Check if a media type is supported by the current model.

        Args:
            mime: MIME type (e.g., "audio/ogg", "video/mp4")
            kind: Media kind (e.g., "audio", "video", "photo")

        Returns:
            True if supported, False otherwise
        """
        mime_lower = mime.lower()
        kind_lower = kind.lower()

        # Audio check
        if "audio" in mime_lower or kind_lower == "audio" or kind_lower == "voice":
            if not self._audio_supported:
                return False

        # Video check (inline video, not YouTube URLs)
        if "video" in mime_lower or kind_lower == "video":
            if not self._video_supported:
                return False

        # Images are supported by all models
        # Documents/PDFs are supported by Gemini 1.5+

        return True

    async def generate(
        self,
        system_prompt: str,
        history: Iterable[dict[str, Any]] | None,
        user_parts: Iterable[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_callbacks: (
            dict[str, Callable[[dict[str, Any]], Awaitable[str]]] | None
        ) = None,
    ) -> str:
        self._ensure_circuit()

        def assemble(include_prompt: bool) -> list[dict[str, Any]]:
            payload: list[dict[str, Any]] = []
            if include_prompt and system_prompt:
                payload.append({"role": "user", "parts": [{"text": system_prompt}]})
            if history:
                payload.extend(list(history))
            payload.append({"role": "user", "parts": list(user_parts)})
            return payload

        use_system_instruction = (
            bool(system_prompt) and self._system_instruction_supported
        )
        filtered_tools = self._filter_tools(tools)
        system_instruction = system_prompt if use_system_instruction else None
        contents = assemble(not use_system_instruction)
        call_contents = contents
        response: Any | None = None

        # Reset fallback flag at start of new request
        self._tools_fallback_disabled = False

        try:
            response = await self._invoke_model(
                call_contents,
                filtered_tools,
                system_instruction,
            )
        except TypeError as exc:
            if system_instruction and "system_instruction" in str(exc):
                self._system_instruction_supported = False
                self._logger.warning(f"Disabling system_instruction: {exc}")
                use_system_instruction = False
                system_instruction = None
                contents = assemble(True)
                call_contents = contents
                response = await self._invoke_model(call_contents, filtered_tools, None)
            else:
                self._record_failure()
                raise
        except GeminiError:
            self._record_failure()
            raise
        except Exception as exc:  # pragma: no cover - network failure paths
            err_text = str(exc)

            # Check for rate limit errors (429)
            is_rate_limit = (
                "429" in err_text
                or "quota" in err_text.lower()
                or "rate limit" in err_text.lower()
                or "ResourceExhausted" in str(type(exc))
            )

            if is_rate_limit:
                self._logger.warning(
                    f"Gemini API rate limit exceeded. "
                    f"Consider: 1) Reducing context size, 2) Upgrading API plan, "
                    f"3) Adding delays between requests. Error: {err_text[:200]}",
                )
                # Don't retry on rate limits - let circuit breaker handle it
                self._record_failure()
                raise GeminiError(
                    "Rate limit exceeded. Please try again later."
                ) from exc

            # Check if it's a media-related error
            is_media_error = any(
                keyword in err_text.lower()
                for keyword in [
                    "image",
                    "video",
                    "audio",
                    "media",
                    "inline_data",
                    "modality",
                ]
            )

            if is_media_error:
                self._logger.error(
                    f"Gemini media processing failed: {err_text}. "
                    f"This may be due to unsupported format or corrupted media.",
                )

            self._logger.exception(
                "Gemini request failed with tools; applying fallbacks"
            )
            if system_instruction and "system_instruction" in err_text:
                self._system_instruction_supported = False
                system_instruction = None
                use_system_instruction = False
                contents = assemble(True)
                call_contents = contents

            retried = False
            # Check if we need to disable tools
            if self._maybe_disable_tools(err_text):
                filtered_tools = None  # Disable all tools
                self._tools_fallback_disabled = (
                    True  # Mark tools as temporarily disabled
                )
            elif self._maybe_disable_search_grounding(err_text):
                filtered_tools = self._filter_tools(tools)

            try:
                response = await self._invoke_model(
                    call_contents,
                    filtered_tools,
                    system_instruction,
                )
                retried = True
            except Exception as fallback_exc:
                if filtered_tools:
                    try:
                        response = await self._invoke_model(
                            call_contents,
                            None,
                            system_instruction,
                        )
                        self._tools_fallback_disabled = (
                            True  # Mark tools as temporarily disabled
                        )
                        retried = True
                    except Exception as final_exc:  # pragma: no cover
                        self._record_failure()
                        raise GeminiError("Gemini request failed") from final_exc
                if not retried:
                    self._record_failure()
                    raise GeminiError("Gemini request failed") from fallback_exc

        if tool_callbacks and response is not None:
            self._logger.debug(
                f"Processing response with {len(tool_callbacks)} tool callbacks available"
            )
            try:
                response = await self._handle_tools(
                    initial_contents=call_contents,
                    response=response,
                    tools=tools,
                    callbacks=tool_callbacks,
                    system_instruction=system_instruction,
                )
                self._logger.debug("Tool handling completed successfully")
            except GeminiError:
                self._record_failure()
                raise

        if response is None:
            self._record_failure()
            raise GeminiError("Gemini request returned no response")

        self._record_success()

        # Log final response structure
        extracted_text = self._extract_text(response)
        self._logger.info(
            f"Extracted text length: {len(extracted_text)}, is_empty: {not extracted_text or extracted_text.isspace()}"
        )

        return extracted_text

    @staticmethod
    def _extract_text(response: Any) -> str:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            parts = getattr(content, "parts", None)
            if not parts:
                continue
            text_fragments: list[str] = []
            for part in parts:
                # Skip thinking parts (when thinking mode is enabled)
                is_thought = getattr(part, "thought", False)
                if is_thought:
                    continue

                text_value = getattr(part, "text", None)
                if isinstance(text_value, str) and text_value:
                    text_fragments.append(text_value)
            if text_fragments:
                result = "".join(text_fragments).strip()
                # Basic cleaning at the API level to prevent metadata leakage
                if result.startswith("[meta]"):
                    # Try to extract just the content after metadata
                    lines = result.split("\n")
                    non_meta_lines = [
                        line for line in lines if not line.strip().startswith("[meta")
                    ]
                    if non_meta_lines:
                        result = "\n".join(non_meta_lines).strip()
                return result

        text = getattr(response, "text", None)
        return text.strip() if isinstance(text, str) else ""

    async def _handle_tools(
        self,
        initial_contents: list[dict[str, Any]],
        response: Any,
        tools: list[dict[str, Any]] | None,
        callbacks: dict[str, Callable[[dict[str, Any]], Awaitable[str]]],
        system_instruction: str | None,
    ) -> Any:
        self._logger.info(f"_handle_tools called with {len(callbacks)} callbacks")
        contents = list(initial_contents)
        attempt = 0
        current_response = response
        filtered_tools = self._filter_tools(tools)
        while attempt < 2:  # allow one round-trip
            attempt += 1
            self._logger.info(f"Tool handling attempt {attempt}")
            candidates = getattr(current_response, "candidates", None) or []
            self._logger.info(f"Found {len(candidates)} candidates in response")

            # Log finish_reason and safety_ratings when 0 candidates
            if len(candidates) == 0:
                prompt_feedback = getattr(current_response, "prompt_feedback", None)
                if prompt_feedback:
                    block_reason = getattr(prompt_feedback, "block_reason", None)
                    safety_ratings = getattr(prompt_feedback, "safety_ratings", None)
                    self._logger.warning(
                        f"0 candidates - prompt_feedback block_reason: {block_reason}, safety_ratings: {safety_ratings}"
                    )

                    # Raise specific exception for content blocking
                    if block_reason:
                        block_reason_str = str(block_reason)
                        if "PROHIBITED_CONTENT" in block_reason_str:
                            raise GeminiContentBlockedError(
                                "Content blocked due to policy violation",
                                block_reason=block_reason_str,
                                safety_ratings=safety_ratings,
                            )
                else:
                    self._logger.warning(
                        "0 candidates and no prompt_feedback available"
                    )

            function_called = False
            for candidate in candidates:
                # Log finish_reason for each candidate
                finish_reason = getattr(candidate, "finish_reason", None)
                if finish_reason:
                    self._logger.info(f"Candidate finish_reason: {finish_reason}")

                content = getattr(candidate, "content", None)
                if not content:
                    self._logger.warning("Candidate has no content attribute")
                    continue

                parts = getattr(content, "parts", None)
                if not parts:
                    self._logger.warning(
                        f"Candidate content has no parts (parts={parts})"
                    )
                    continue

                self._logger.info(f"Candidate has {len(parts)} parts")
                parts_payload: list[dict[str, Any]] = []
                tool_calls: list[tuple[str, dict[str, Any]]] = []

                # Log what's in each part
                for idx, part in enumerate(parts):
                    has_text = hasattr(part, "text") and part.text is not None
                    has_function_call = (
                        hasattr(part, "function_call")
                        and part.function_call is not None
                    )
                    is_thought = getattr(part, "thought", False)
                    self._logger.debug(
                        f"Part {idx}: has_text={has_text}, has_function_call={has_function_call}, is_thought={is_thought}"
                    )

                for part in content.parts:
                    function_call = getattr(part, "function_call", None)
                    if function_call:
                        self._logger.info(
                            f"Found function_call in part: {getattr(function_call, 'name', 'UNKNOWN')}"
                        )
                        name = getattr(function_call, "name", "")
                        raw_args = getattr(function_call, "args", {}) or {}
                        if isinstance(raw_args, dict):
                            args = raw_args
                        else:
                            try:
                                args = dict(raw_args)
                            except TypeError:
                                args = {}
                        tool_calls.append((name, args))
                        parts_payload.append(
                            {
                                "function_call": {
                                    "name": name,
                                    "args": args,
                                }
                            }
                        )
                    elif getattr(part, "text", None) is not None:
                        # Skip thinking parts from parts_payload
                        # Thinking is for Gemini's internal reasoning, not for conversation history
                        is_thought = getattr(part, "thought", False)
                        if is_thought:
                            self._logger.info(
                                f"Filtered thinking text part (length: {len(part.text)})"
                            )
                            # Don't add thinking to parts_payload
                        else:
                            parts_payload.append({"text": part.text})

                # If no tool calls found, check if we have actual content
                if not tool_calls:
                    self._logger.info("No tool_calls found in this candidate's parts")
                    # If we have non-thinking text, this is a valid final response
                    if parts_payload:
                        self._logger.info(
                            "Found non-thinking content, breaking tool loop"
                        )
                        # Don't add to contents here - response will be processed normally
                        break
                    # If only thinking (empty parts_payload), skip this candidate
                    self._logger.info(
                        "Only thinking parts, no actual content - continuing"
                    )
                    continue

                self._logger.info(
                    f"Found {len(tool_calls)} tool calls: {[name for name, _ in tool_calls]}"
                )
                # Normalize tool names (Gemini may prefix names with namespaces like 'default_api:search_web')
                normalized_tool_calls: list[tuple[str, dict[str, Any]]] = []
                for raw_name, args in tool_calls:
                    key = raw_name.split(":")[-1] if ":" in raw_name else raw_name
                    normalized_tool_calls.append((key, args))

                local_tool_calls = [
                    (key, args)
                    for (key, args) in normalized_tool_calls
                    if key in callbacks
                ]
                if not local_tool_calls:
                    self._logger.warning(
                        f"No matching callbacks for tool calls: {[name for name, _ in tool_calls]}"
                    )
                    continue
                self._logger.info(f"Matched {len(local_tool_calls)} local tool calls")

                contents.append(
                    {"role": getattr(content, "role", "model"), "parts": parts_payload}
                )

                for name, args in local_tool_calls:
                    function_called = True
                    self._logger.info(f"Calling tool: {name} with args: {args}")
                    callback = callbacks[name]
                    try:
                        result = await callback(args)
                        self._logger.info(f"Tool {name} returned: {str(result)[:200]}")
                    except (
                        Exception
                    ) as exc:  # pragma: no cover - runtime handler errors
                        result = {"error": str(exc)}

                    response_payload: Any
                    if isinstance(result, str):
                        try:
                            response_payload = json.loads(result)
                        except json.JSONDecodeError:
                            response_payload = {"text": result}
                    elif isinstance(result, dict):
                        response_payload = result
                    else:
                        response_payload = {"data": result}

                    contents.append(
                        {
                            "role": "tool",
                            "parts": [
                                {
                                    "function_response": {
                                        "name": name,
                                        "response": response_payload,
                                    }
                                }
                            ],
                        }
                    )

            if not function_called:
                break

            try:
                current_response = await self._invoke_model(
                    contents,
                    filtered_tools,
                    system_instruction,
                )
            except Exception as exc:  # pragma: no cover
                err_text = str(exc)
                self._logger.exception(
                    "Gemini tool-followup failed; retrying without tools"
                )
                if self._maybe_disable_search_grounding(err_text):
                    filtered_tools = self._filter_tools(tools)
                    if filtered_tools:
                        try:
                            current_response = await self._invoke_model(
                                contents,
                                filtered_tools,
                                system_instruction,
                            )
                            continue
                        except Exception:
                            self._logger.exception(
                                "Gemini follow-up retry with filtered tools failed"
                            )
                try:
                    current_response = await self._invoke_model(
                        contents,
                        None,
                        system_instruction,
                    )
                except Exception as fallback_exc:  # pragma: no cover
                    self._logger.exception("Gemini fallback follow-up failed")
                    raise GeminiError("Gemini tool-followup failed") from fallback_exc

        # Check if we exited the loop with tool calls but no text response
        # This happens when Gemini keeps calling tools without providing a final answer
        extracted_text = self._extract_text(current_response)
        if not extracted_text or extracted_text.isspace():
            # Check if last response has function_calls
            has_function_calls = False
            candidates = getattr(current_response, "candidates", None) or []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if content:
                    parts = getattr(content, "parts", None) or []
                    for part in parts:
                        if (
                            hasattr(part, "function_call")
                            and part.function_call is not None
                        ):
                            has_function_calls = True
                            break
                if has_function_calls:
                    break

            if has_function_calls:
                self._logger.warning(
                    "Gemini returned only function_calls without text after tool execution. "
                    "Retrying without tools to force text response."
                )
                try:
                    # Force a response without tools - append a hint to conversation
                    contents.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": "[Provide your response now based on the tool results]"
                                }
                            ],
                        }
                    )
                    current_response = await self._invoke_model(
                        contents,
                        None,  # No tools - force text response
                        system_instruction,
                    )
                except Exception as exc:
                    self._logger.exception("Failed to force text response after tools")
                    # Continue with current_response - handler will use fallback

        return current_response

    async def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            return []

        # Check cache first
        if self._embedding_cache:
            cached = await self._embedding_cache.get(text, model=self._embed_model)
            if cached is not None:
                telemetry.increment_counter("embedding_cache_hits")
                return cached

        async with self._embed_semaphore:
            attempts = len(self._api_keys) if self._free_tier_mode else 1
            last_quota_exc: Exception | None = None

            for _ in range(max(1, attempts)):
                key: str | None = None
                try:
                    client, key = await self._acquire_client()
                    response = await client.aio.models.embed_content(
                        model=self._embed_model,
                        contents=text,
                    )
                    if hasattr(response, "embeddings") and response.embeddings:
                        embedding = response.embeddings[0]
                        if hasattr(embedding, "values"):
                            values = getattr(embedding, "values", None)
                            if values is not None:
                                result = list(values)

                                if self._embedding_cache and result:
                                    await self._embedding_cache.put(
                                        text, result, model=self._embed_model
                                    )
                                    telemetry.increment_counter(
                                        "embedding_cache_stores"
                                    )

                                return result
                    telemetry.increment_counter("embedding_cache_misses")
                    return []
                except Exception as exc:
                    if key is not None and self._is_quota_error(exc):
                        await self._mark_quota(key)
                        last_quota_exc = exc
                        continue
                    self._logger.warning(f"Embedding failed: {exc}")
                    telemetry.increment_counter("embedding_cache_misses")
                    return []

            if last_quota_exc:
                raise GeminiError(
                    "Embedding request failed due to quota limits"
                ) from last_quota_exc

            telemetry.increment_counter("embedding_cache_misses")
            return []
