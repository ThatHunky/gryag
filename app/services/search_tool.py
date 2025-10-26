"""
Web search tool using Google Search grounding.

This provides a function tool interface to Google's search grounding,
allowing the bot to explicitly call search alongside other tools.
"""

import json
from typing import Any

from google import genai
from google.genai import types


async def search_web_tool(
    params: dict[str, Any],
    gemini_client: Any,  # GeminiClient instance
    api_key: str | None = None,  # Optional separate API key
) -> str:
    """
    Search the web using Google Search grounding.

    Args:
        params: Tool parameters containing 'query'
        gemini_client: GeminiClient instance for API access
        api_key: Optional separate API key for web search (falls back to client's key)

    Returns:
        JSON string with search results or error message
    """
    query = (params or {}).get("query", "")
    if not isinstance(query, str) or not query.strip():
        return json.dumps({"error": "Empty query", "results": []})

    try:
        # Use provided API key or fall back to gemini_client's key
        effective_api_key = api_key or gemini_client._api_key

        # Create a simple request with just the search grounding tool
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        # Create a temporary client with the effective API key if different
        if api_key and api_key != gemini_client._api_key:
            # Use a separate client instance for this search
            search_client = genai.Client(api_key=effective_api_key)
            response = await search_client.aio.models.generate_content(
                model=gemini_client._model_name,
                contents=[{"role": "user", "parts": [{"text": query}]}],
                config=config,
            )
        else:
            # Use the gemini client's underlying API client
            response = await gemini_client._client.aio.models.generate_content(
                model=gemini_client._model_name,
                contents=[{"role": "user", "parts": [{"text": query}]}],
                config=config,
            )

        # Extract text from response
        result_text = "No results found"
        if hasattr(response, "text") and response.text:
            result_text = response.text
        elif hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if (
                candidate
                and hasattr(candidate, "content")
                and candidate.content
                and hasattr(candidate.content, "parts")
            ):
                parts = candidate.content.parts
                if parts:
                    result_text = " ".join(
                        part.text
                        for part in parts
                        if hasattr(part, "text") and part.text
                    )

        return json.dumps({"query": query, "answer": result_text})

    except Exception as e:
        return json.dumps(
            {"error": f"Search failed: {str(e)}", "query": query, "results": []}
        )


SEARCH_WEB_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "search_web",
            "description": (
                "Шукати інформацію в інтернеті через Google. "
                "Використовуй для пошуку актуальних новин, фактів, подій, даних. "
                "Search the web using Google for current information, news, facts, events, data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Пошуковий запит / Search query",
                    },
                },
                "required": ["query"],
            },
        }
    ]
}
