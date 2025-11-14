"""
Web search tool using DuckDuckGo Search.

This provides a function tool interface to DuckDuckGo search,
allowing the bot to search for text, images, videos, and news.
Also provides content fetching for detailed page content.
"""

import asyncio
import json
import logging
import re
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urlparse

import aiohttp
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
        for idx, result in enumerate(raw_results[:max_results]):
            url = result.get("href", "")
            results.append(
                {
                    "index": idx,
                    "title": result.get("title", ""),
                    "url": url,
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
        for idx, result in enumerate(raw_results[:max_results]):
            results.append(
                {
                    "index": idx,
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
        for idx, result in enumerate(raw_results[:max_results]):
            results.append(
                {
                    "index": idx,
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
        for idx, result in enumerate(raw_results[:max_results]):
            results.append(
                {
                    "index": idx,
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


class TextExtractor(HTMLParser):
    """Simple HTML parser to extract text content from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.in_script = False
        self.in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track script and style tags to skip their content."""
        if tag.lower() in ("script", "style"):
            self.in_script = tag.lower() == "script"
            self.in_style = tag.lower() == "style"

    def handle_endtag(self, tag: str) -> None:
        """Reset script/style flags."""
        if tag.lower() in ("script", "style"):
            self.in_script = False
            self.in_style = False

    def handle_data(self, data: str) -> None:
        """Collect text data, skipping script and style content."""
        if not self.in_script and not self.in_style:
            text = data.strip()
            if text:
                self.text_parts.append(text)

    def get_text(self, max_length: int = 5000) -> str:
        """Get extracted text, limited to max_length characters."""
        full_text = " ".join(self.text_parts)
        if len(full_text) > max_length:
            return full_text[:max_length] + "..."
        return full_text


async def fetch_web_content_tool(params: dict[str, Any]) -> str:
    """
    Fetch detailed content from a web page URL.
    
    Can be used after search_web to get full page content from specific results.
    Requires a URL to fetch from. Optional parameters (result_index, search_query) are
    included in the response for context/tracking purposes only.
    
    Args:
        params: Tool parameters containing:
            - 'url' (required): URL of the web page to fetch
            - 'result_index' (optional): Index from previous search_web results (for context)
            - 'search_query' (optional): Original search query (for context)
    
    Returns:
        JSON string with fetched content or error message
    """
    url = params.get("url", "")
    result_index = params.get("result_index")
    search_query = params.get("search_query", "")
    
    # Validate URL
    if not url or not isinstance(url, str):
        return json.dumps({
            "error": "URL is required",
            "url": url,
        })
    
    # Basic URL validation
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return json.dumps({
            "error": f"Invalid URL format: {url}",
            "url": url,
        })
    
    # Ensure URL has a scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    try:
        # Fetch page content with timeout
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Set a reasonable user agent
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            async with session.get(url, headers=headers, allow_redirects=True) as response:
                if response.status != 200:
                    return json.dumps({
                        "error": f"HTTP {response.status}: Failed to fetch URL",
                        "url": url,
                        "status": response.status,
                    })
                
                # Check content type
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return json.dumps({
                        "error": f"Unsupported content type: {content_type}",
                        "url": url,
                        "content_type": content_type,
                    })
                
                # Read content with size limit (1MB max)
                content = await response.read()
                if len(content) > 1024 * 1024:  # 1MB limit
                    return json.dumps({
                        "error": "Page content too large (max 1MB)",
                        "url": url,
                        "size_bytes": len(content),
                    })
                
                # Decode HTML
                try:
                    html_content = content.decode("utf-8", errors="replace")
                except UnicodeDecodeError:
                    # Try other encodings
                    try:
                        html_content = content.decode("latin-1", errors="replace")
                    except Exception:
                        return json.dumps({
                            "error": "Failed to decode page content",
                            "url": url,
                        })
                
                # Extract text from HTML
                parser = TextExtractor()
                parser.feed(html_content)
                extracted_text = parser.get_text(max_length=5000)
                
                # Try to extract title from HTML
                title_match = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
                title = title_match.group(1).strip() if title_match else ""
                # Clean title HTML entities
                title = re.sub(r"<[^>]+>", "", title)
                title = title.replace("&nbsp;", " ").strip()
                
                return json.dumps({
                    "url": url,
                    "title": title or "No title",
                    "content": extracted_text,
                    "content_length": len(extracted_text),
                    "original_size": len(html_content),
                    "result_index": result_index,
                    "search_query": search_query,
                }, ensure_ascii=False)
    
    except asyncio.TimeoutError:
        return json.dumps({
            "error": "Request timeout: URL took too long to respond",
            "url": url,
        })
    except aiohttp.ClientError as e:
        return json.dumps({
            "error": f"Network error: {str(e)}",
            "url": url,
        })
    except Exception as e:
        logger.exception(f"Failed to fetch web content from {url}")
        return json.dumps({
            "error": f"Failed to fetch content: {str(e)}",
            "url": url,
        })


SEARCH_WEB_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "search_web",
            "description": (
                "Шукати інформацію в інтернеті через DuckDuckGo — ОСНОВНИЙ інструмент для пошуку зображень, відео і новин. "
                "ЗАВЖДИ використовуй search_type='images' для пошуку зображень. Це ПЕРШОЧЕРГОВО перед generate_image. "
                "Генеруй зображення ЛИШЕ якщо користувач явно просить створити нове. "
                "КРИТИЧНО: Коли користувач питає про НОВИНИ (новини, атака, події, сьогодні, сьогоднішня, останні події) — ЗАВЖДИ використовуй search_type='news'. "
                "Приклади: 'знайди новини про атаку', 'що сталося сьогодні', 'останні події' → search_type='news'. "
                "Підтримує пошук тексту, зображень, відео та новин. "
                "Повертає результати з індексами (0, 1, 2...). Використовуй fetch_web_content для отримання детального контенту з конкретних результатів. "
                "Primary tool for finding images/videos/news via DuckDuckGo. Use search_type='images' for image search. ALWAYS try this BEFORE generating new images. "
                "CRITICAL: When user asks about NEWS (новини, атака, події, сьогодні, today, recent events, latest news) — ALWAYS use search_type='news'. "
                "Examples: 'find news about attack', 'what happened today', 'latest events' → search_type='news'. "
                "Only generate when user explicitly asks to create new image. Returns results with indices (0, 1, 2...). Use fetch_web_content to get detailed content from specific results."
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
                            "Search type: 'text' (default), 'images', 'videos', 'news'. "
                            "КРИТИЧНО: Використовуй 'news' для новин, атак, подій, сьогоднішніх подій / "
                            "CRITICAL: Use 'news' for news, attacks, events, today's events"
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


FETCH_WEB_CONTENT_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "fetch_web_content",
            "description": (
                "Отримати детальний контент з веб-сторінки за URL. "
                "Використовуй після search_web для отримання повного тексту з конкретних результатів. "
                "Потрібен URL для отримання контенту. Опціональні параметри (result_index, search_query) використовуються лише для контексту. "
                "Fetch detailed content from a web page URL. Use after search_web to get full page content from specific results. "
                "Requires URL to fetch from. Optional parameters (result_index, search_query) are for context only. Extracts main text content (up to 5000 chars) from HTML pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL веб-сторінки для отримання контенту / URL of the web page to fetch content from",
                    },
                    "result_index": {
                        "type": "integer",
                        "description": "Індекс результату з попереднього search_web (опціонально) / Index from previous search_web results (optional)",
                    },
                    "search_query": {
                        "type": "string",
                        "description": "Оригінальний пошуковий запит для контексту (опціонально) / Original search query for context (optional)",
                    },
                },
                "required": ["url"],
            },
        }
    ]
}
