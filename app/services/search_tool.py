"""
Web search tool using DuckDuckGo Search.

This provides a function tool interface to DuckDuckGo search,
allowing the bot to search for text, images, videos, and news.
"""

import asyncio
import json
import logging
from typing import Any, Literal

from ddgs import DDGS

logger = logging.getLogger(__name__)

SearchType = Literal["text", "images", "videos", "news"]


async def search_web_tool(
    params: dict[str, Any],
    gemini_client: Any = None,  # Not needed for DDG, kept for compatibility
    api_key: str | None = None,  # Not needed for DDG, kept for compatibility
) -> str:
    """
    Search the web using DuckDuckGo.

    Args:
        params: Tool parameters containing 'query' and optional 'search_type'
        gemini_client: Unused (kept for compatibility)
        api_key: Unused (kept for compatibility)

    Returns:
        JSON string with search results or error message
    """
    query = (params or {}).get("query", "")
    if not isinstance(query, str) or not query.strip():
        return json.dumps({"error": "Empty query", "results": []})

    search_type: SearchType = params.get("search_type", "text")
    if search_type not in ("text", "images", "videos", "news"):
        search_type = "text"

    max_results = params.get("max_results", 5)
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = 5
    max_results = max(1, min(max_results, 10))

    try:
        # Run search in thread pool since DDGS is synchronous
        results = await asyncio.to_thread(
            _search_sync, query, search_type, max_results
        )

        return json.dumps(
            {
                "query": query,
                "search_type": search_type,
                "results": results,
                "count": len(results),
            }
        )

    except Exception as e:
        logger.exception(f"DuckDuckGo search failed for query: {query}")
        return json.dumps(
            {
                "error": f"Search failed: {str(e)}",
                "query": query,
                "search_type": search_type,
                "results": [],
            }
        )


def _search_sync(query: str, search_type: SearchType, max_results: int) -> list[dict]:
    """Synchronous search wrapper for all search types."""
    with DDGS() as ddgs:
        if search_type == "text":
            return _search_text(ddgs, query, max_results)
        elif search_type == "images":
            return _search_images(ddgs, query, max_results)
        elif search_type == "videos":
            return _search_videos(ddgs, query, max_results)
        elif search_type == "news":
            return _search_news(ddgs, query, max_results)
        else:
            return []


def _search_text(ddgs: DDGS, query: str, max_results: int) -> list[dict]:
    """Search for text results."""
    results = []
    try:
        raw_results = ddgs.text(query, max_results=max_results, safesearch="off")
        for result in raw_results[:max_results]:
            results.append(
                {
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "description": result.get("body", ""),
                }
            )
    except Exception as e:
        logger.warning(f"Text search error: {e}")
    return results


def _search_images(ddgs: DDGS, query: str, max_results: int) -> list[dict]:
    """Search for image results."""
    results = []
    try:
        raw_results = ddgs.images(query, max_results=max_results, safesearch="off")
        for result in raw_results[:max_results]:
            results.append(
                {
                    "title": result.get("title", ""),
                    "url": result.get("image", ""),
                    "thumbnail": result.get("thumbnail", ""),
                    "source": result.get("source", ""),
                    "width": result.get("width"),
                    "height": result.get("height"),
                }
            )
    except Exception as e:
        logger.warning(f"Image search error: {e}")
    return results


def _search_videos(ddgs: DDGS, query: str, max_results: int) -> list[dict]:
    """Search for video results."""
    results = []
    try:
        raw_results = ddgs.videos(query, max_results=max_results, safesearch="off")
        for result in raw_results[:max_results]:
            results.append(
                {
                    "title": result.get("title", ""),
                    "url": result.get("content", ""),
                    "description": result.get("description", ""),
                    "publisher": result.get("publisher", ""),
                    "duration": result.get("duration", ""),
                    "published": result.get("published", ""),
                }
            )
    except Exception as e:
        logger.warning(f"Video search error: {e}")
    return results


def _search_news(ddgs: DDGS, query: str, max_results: int) -> list[dict]:
    """Search for news results."""
    results = []
    try:
        raw_results = ddgs.news(query, max_results=max_results, safesearch="off")
        for result in raw_results[:max_results]:
            results.append(
                {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "description": result.get("body", ""),
                    "source": result.get("source", ""),
                    "date": result.get("date", ""),
                }
            )
    except Exception as e:
        logger.warning(f"News search error: {e}")
    return results


SEARCH_WEB_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "search_web",
            "description": (
                "Шукати інформацію в інтернеті через DuckDuckGo — ОСНОВНИЙ інструмент для пошуку зображень, відео і новин. "
                "ЗАВЖДИ використовуй search_type='images' для пошуку зображень. Це ПЕРШОЧЕРГОВО перед generate_image. "
                "Генеруй зображення ЛИШЕ якщо користувач явно просить створити нове. "
                "Підтримує пошук тексту, зображень, відео та новин. "
                "Primary tool for finding images/videos/news via DuckDuckGo. Use search_type='images' for image search. ALWAYS try this BEFORE generating new images. Only generate when user explicitly asks to create new image."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Пошуковий запит / Search query",
                    },
                    "search_type": {
                        "type": "string",
                        "description": (
                            "Тип пошуку: 'text' (за замовчуванням), 'images', 'videos', 'news' / "
                            "Search type: 'text' (default), 'images', 'videos', 'news'"
                        ),
                        "enum": ["text", "images", "videos", "news"],
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Максимальна кількість результатів (1-10, за замовчуванням 5) / Max results (1-10, default 5)",
                    },
                },
                "required": ["query"],
            },
        }
    ]
}
