from __future__ import annotations

import base64
import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Iterable
import logging

import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory

from app.services import telemetry


class GeminiError(Exception):
    """Raised when Gemini generation fails."""


class GeminiClient:
    """Async wrapper around Google Gemini models."""

    def __init__(self, api_key: str, model: str, embed_model: str) -> None:
        genai.configure(api_key=api_key)  # type: ignore[attr-defined]
        self._model = genai.GenerativeModel(model_name=model)  # type: ignore[attr-defined]
        self._embed_model = embed_model
        self._logger = logging.getLogger(__name__)
        self._search_grounding_supported = True
        self._system_instruction_supported = True
        self._generate_timeout = 45.0
        self._max_failures = 3
        self._cooldown_seconds = 60.0
        self._failure_count = 0
        self._circuit_open_until = 0.0
        self._embed_semaphore = asyncio.Semaphore(8)
        # Gemini 1.5 renamed some safety categories and dropped the SafetySetting class
        categories = []
        for name in (
            "HARM_CATEGORY_HARASSMENT",
            "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "HARM_CATEGORY_SEXUAL",  # backwards compatibility with older SDKs
            "HARM_CATEGORY_SELF_HARM",
            "HARM_CATEGORY_DANGEROUS_CONTENT",
        ):
            category = getattr(HarmCategory, name, None)
            if category is not None and category not in categories:
                categories.append(category)

        self._safety_settings = [
            {"category": category, "threshold": HarmBlockThreshold.BLOCK_NONE}
            for category in categories
        ]

    def _filter_tools(
        self, tools: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        if not tools:
            return None
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
            self._logger.warning("Disabling search grounding tools: %s", error_message)
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

    async def _invoke_model(
        self,
        contents: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system_instruction: str | None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "safety_settings": self._safety_settings,
        }
        if tools:
            kwargs["tools"] = tools
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        try:
            return await asyncio.wait_for(
                self._model.generate_content_async(
                    contents,
                    **kwargs,
                ),
                timeout=self._generate_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise GeminiError("Gemini request timed out") from exc

    @staticmethod
    def build_media_parts(
        media_items: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        for item in media_items:
            blob = item.get("bytes")
            mime = item.get("mime")
            if not blob or not mime:
                continue
            data = base64.b64encode(blob).decode("ascii")
            parts.append({"inline_data": {"mime_type": mime, "data": data}})
        return parts

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

        try:
            response = await self._invoke_model(
                call_contents,
                filtered_tools,
                system_instruction,
            )
        except TypeError as exc:
            if system_instruction and "system_instruction" in str(exc):
                self._system_instruction_supported = False
                self._logger.warning("Disabling system_instruction: %s", exc)
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
            if self._maybe_disable_search_grounding(err_text):
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
                        retried = True
                    except Exception as final_exc:  # pragma: no cover
                        self._record_failure()
                        raise GeminiError("Gemini request failed") from final_exc
                if not retried:
                    self._record_failure()
                    raise GeminiError("Gemini request failed") from fallback_exc

        if tool_callbacks and response is not None:
            try:
                response = await self._handle_tools(
                    initial_contents=call_contents,
                    response=response,
                    tools=tools,
                    callbacks=tool_callbacks,
                    system_instruction=system_instruction,
                )
            except GeminiError:
                self._record_failure()
                raise

        if response is None:
            self._record_failure()
            raise GeminiError("Gemini request returned no response")

        self._record_success()

        return self._extract_text(response)

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
                text_value = getattr(part, "text", None)
                if isinstance(text_value, str) and text_value:
                    text_fragments.append(text_value)
            if text_fragments:
                return "".join(text_fragments).strip()

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
        contents = list(initial_contents)
        attempt = 0
        current_response = response
        filtered_tools = self._filter_tools(tools)
        while attempt < 2:  # allow one round-trip
            attempt += 1
            candidates = getattr(current_response, "candidates", None) or []
            function_called = False
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if not content or not getattr(content, "parts", None):
                    continue
                parts_payload: list[dict[str, Any]] = []
                tool_calls: list[tuple[str, dict[str, Any]]] = []
                for part in content.parts:
                    function_call = getattr(part, "function_call", None)
                    if function_call:
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
                        parts_payload.append({"text": part.text})
                if not tool_calls:
                    continue

                local_tool_calls = [
                    (name, args) for (name, args) in tool_calls if name in callbacks
                ]
                if not local_tool_calls:
                    continue

                contents.append(
                    {"role": getattr(content, "role", "model"), "parts": parts_payload}
                )

                for name, args in local_tool_calls:
                    function_called = True
                    callback = callbacks[name]
                    try:
                        result = await callback(args)
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

        return current_response

    async def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            return []

        def _embed() -> list[float]:
            result = genai.embed_content(model=self._embed_model, content=text)  # type: ignore[attr-defined]
            embedding = result.get("embedding") if isinstance(result, dict) else None
            return list(embedding) if embedding else []

        async with self._embed_semaphore:
            return await asyncio.to_thread(_embed)
