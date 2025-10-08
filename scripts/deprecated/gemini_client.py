import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = os.getenv("GEMINI_API_URL", "https://api.gemini.example/v1/generate")


try:
    # prefer official Google Generative AI SDK
    import google.generativeai as genai  # type: ignore

    class GeminiClient:
        def __init__(self, api_key: Optional[str] = None, model: str = "gemini-medium"):
            self.api_key = api_key or GEMINI_API_KEY
            if not self.api_key:
                raise RuntimeError("GEMINI_API_KEY is not set")
            genai.configure(api_key=self.api_key)
            self.model = model

        async def generate_text(self, prompt: str, max_tokens: int = 256) -> str:
            # google-generative-ai currently provides sync or async clients depending on version;
            # using the `genai` high-level API if available. This call may be synchronous depending on SDK.
            try:
                resp = genai.generate_text(model=self.model, prompt=prompt, max_output_tokens=max_tokens)
                # resp may be a dict-like object
                if isinstance(resp, dict):
                    return resp.get("output", resp.get("text", ""))
                # fallback to string conversion
                return str(resp)
            except Exception as e:
                logger.exception("GenAI SDK call failed, falling back to HTTP: %s", e)
                raise

except Exception:
    # fallback to aiohttp-based generic POST client
    import json
    import aiohttp

    class GeminiClient:
        def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
            self.api_key = api_key or GEMINI_API_KEY
            self.base_url = base_url or GEMINI_API_URL
            if not self.api_key:
                raise RuntimeError("GEMINI_API_KEY is not set")

        async def generate_text(self, prompt: str, max_tokens: int = 256) -> str:
            payload = {"prompt": prompt, "max_tokens": max_tokens}
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_url, json=payload, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        logger.error("Gemini API error %s: %s", resp.status, text)
                        raise RuntimeError(f"Gemini API error: {resp.status}")
                    try:
                        data = await resp.json()
                        return data.get("text") or data.get("output") or text
                    except Exception:
                        return text


__all__ = ["GeminiClient"]
