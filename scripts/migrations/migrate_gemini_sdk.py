#!/usr/bin/env python3
"""
Script to migrate app/services/gemini.py from google-generativeai to google-genai SDK.

This performs the following transformations:
1. Changes imports: import google.generativeai → from google import genai
2. Adds types import: from google.genai import types
3. Updates __init__ to use Client instead of GenerativeModel
4. Updates _invoke_model to use client.models.generate_content
5. Updates embed_text to use client.models.embed_content
6. Updates safety settings to use types.SafetySetting
7. Keeps all business logic intact (circuit breaker, tool handling, etc.)
"""

import re
import sys


def migrate_imports(content: str) -> str:
    """Update import statements."""
    # Replace old SDK import with new SDK imports
    content = re.sub(
        r"import google\.generativeai as genai\nfrom google\.generativeai\.types import HarmBlockThreshold, HarmCategory",
        "from google import genai\nfrom google.genai import types",
        content,
    )
    return content


def migrate_init_method(content: str) -> str:
    """Update __init__ method to use Client instead of GenerativeModel."""
    old_init = r"""    def __init__\(self, api_key: str, model: str, embed_model: str\) -> None:
        genai\.configure\(api_key=api_key\)  # type: ignore\[attr-defined\]
        self\._model = genai\.GenerativeModel\(model_name=model\)  # type: ignore\[attr-defined\]"""

    new_init = """    def __init__(self, api_key: str, model: str, embed_model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = None  # Not needed in new SDK - we call client.models.generate_content directly"""

    content = re.sub(old_init, new_init, content)
    return content


def migrate_safety_settings(content: str) -> str:
    """Update safety settings to use types.SafetySetting."""
    old_safety = r"""        categories = \[\]
        for name in \(
            "HARM_CATEGORY_HARASSMENT",
            "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "HARM_CATEGORY_SEXUAL",  # backwards compatibility with older SDKs
            "HARM_CATEGORY_SELF_HARM",
            "HARM_CATEGORY_DANGEROUS_CONTENT",
        \):
            category = getattr\(HarmCategory, name, None\)
            if category is not None and category not in categories:
                categories\.append\(category\)

        self\._safety_settings = \[
            \{"category": category, "threshold": HarmBlockThreshold\.BLOCK_NONE\}
            for category in categories
        \]"""

    new_safety = """        # Safety settings for new SDK
        self._safety_settings = [
            types.SafetySetting(
                category='HARM_CATEGORY_HARASSMENT',
                threshold='BLOCK_NONE',
            ),
            types.SafetySetting(
                category='HARM_CATEGORY_HATE_SPEECH',
                threshold='BLOCK_NONE',
            ),
            types.SafetySetting(
                category='HARM_CATEGORY_SEXUALLY_EXPLICIT',
                threshold='BLOCK_NONE',
            ),
            types.SafetySetting(
                category='HARM_CATEGORY_DANGEROUS_CONTENT',
                threshold='BLOCK_NONE',
            ),
        ]"""

    content = re.sub(old_safety, new_safety, content, flags=re.DOTALL)
    return content


def migrate_invoke_model(content: str) -> str:
    """Update _invoke_model to use client.models.generate_content."""
    old_invoke = r"""    async def _invoke_model\(
        self,
        contents: list\[dict\[str, Any\]\],
        tools: list\[dict\[str, Any\]\] \| None,
        system_instruction: str \| None,
    \) -> Any:
        kwargs: dict\[str, Any\] = \{
            "safety_settings": self\._safety_settings,
        \}
        if tools:
            kwargs\["tools"\] = tools
        if system_instruction and self\._system_instruction_supported:
            kwargs\["system_instruction"\] = system_instruction
        try:
            return await asyncio\.wait_for\(
                self\._model\.generate_content_async\(
                    contents,
                    \*\*kwargs,
                \),
                timeout=self\._generate_timeout,
            \)
        except asyncio\.TimeoutError as exc:
            raise GeminiError\("Gemini request timed out"\) from exc"""

    new_invoke = """    async def _invoke_model(
        self,
        contents: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system_instruction: str | None,
    ) -> Any:
        config = types.GenerateContentConfig(
            safety_settings=self._safety_settings,
            system_instruction=system_instruction if self._system_instruction_supported else None,
        )
        if tools:
            config.tools = tools
        
        try:
            # New SDK uses client.models.generate_content (async by default)
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model_name,
                    contents=contents,
                    config=config,
                ),
                timeout=self._generate_timeout,
            )
            return response
        except asyncio.TimeoutError as exc:
            raise GeminiError("Gemini request timed out") from exc"""

    content = re.sub(old_invoke, new_invoke, content, flags=re.DOTALL)
    return content


def migrate_embed_text(content: str) -> str:
    """Update embed_text to use client.models.embed_content."""
    old_embed = r"""    async def embed_text\(self, text: str\) -> list\[float\]:
        if not text or not text\.strip\(\):
            return \[\]

        def _embed\(\) -> list\[float\]:
            result = genai\.embed_content\(model=self\._embed_model, content=text\)  # type: ignore\[attr-defined\]
            embedding = result\.get\("embedding"\) if isinstance\(result, dict\) else None
            return list\(embedding\) if embedding else \[\]

        async with self\._embed_semaphore:
            return await asyncio\.to_thread\(_embed\)"""

    new_embed = """    async def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            return []

        async with self._embed_semaphore:
            try:
                response = await self._client.aio.models.embed_content(
                    model=self._embed_model,
                    contents=text,
                )
                # Extract embedding from response
                if hasattr(response, 'embeddings') and response.embeddings:
                    embedding = response.embeddings[0]
                    if hasattr(embedding, 'values'):
                        return list(embedding.values)
                return []
            except Exception as exc:
                self._logger.warning("Embedding failed: %s", exc)
                return []"""

    content = re.sub(old_embed, new_embed, content, flags=re.DOTALL)
    return content


def main():
    input_file = "app/services/gemini.py"
    output_file = "app/services/gemini_migrated.py"

    with open(input_file, "r") as f:
        content = f.read()

    print("Step 1: Migrating imports...")
    content = migrate_imports(content)

    print("Step 2: Migrating __init__ method...")
    content = migrate_init_method(content)

    print("Step 3: Migrating safety settings...")
    content = migrate_safety_settings(content)

    print("Step 4: Migrating _invoke_model...")
    content = migrate_invoke_model(content)

    print("Step 5: Migrating embed_text...")
    content = migrate_embed_text(content)

    with open(output_file, "w") as f:
        f.write(content)

    print(f"\nMigration complete! Output written to: {output_file}")
    print("Please review the changes before replacing the original file.")
    print("\nTo apply: mv app/services/gemini_migrated.py app/services/gemini.py")


if __name__ == "__main__":
    main()
