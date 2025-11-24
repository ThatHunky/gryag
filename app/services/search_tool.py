"""
Web search tool using Gemini's Grounding with Search.

This provides a function tool interface to Google Search via Gemini's
native grounding capability, allowing the bot to search for current information.
Also provides content fetching for detailed page content.
"""

import json
import logging
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import aiohttp
from google.genai import types

logger = logging.getLogger(__name__)


async def search_web_tool(
    params: dict[str, Any],
    gemini_client: Any,
    api_key: str | None = None,  # Not used, kept for compatibility
) -> str:
    """
    Search the web using Gemini's Grounding with Search.

    Args:
        params: Tool parameters containing 'query'
        gemini_client: GeminiClient instance for making API calls
        api_key: Unused (kept for compatibility)

    Returns:
        JSON string with search results or error message
    """
    if not gemini_client:
        return json.dumps(
            {"error": "Gemini client is required for search", "results": []}
        )

    query = (params or {}).get("query", "")
    if not isinstance(query, str) or not query.strip():
        return json.dumps({"error": "Empty query", "results": []})

    max_results = params.get("max_results", 5)
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = 5
    max_results = max(1, min(max_results, 10))

    try:
        # Use Gemini's Grounding with Search by making a separate API call
        # with google_search tool enabled
        client, _ = await gemini_client._acquire_client()

        # Create config with google_search tool
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            safety_settings=gemini_client._safety_settings,
        )

        # Make the search request
        response = await client.aio.models.generate_content(
            model=gemini_client._model_name,
            contents=[{"role": "user", "parts": [{"text": query}]}],
            config=config,
        )

        # Extract text response
        text_response = gemini_client._extract_text(response)

        # Extract grounding metadata
        results = _extract_grounding_results(response, max_results)

        return json.dumps(
            {
                "query": query,
                "results": results,
                "count": len(results),
                "answer": text_response,  # Include the synthesized answer
            }
        )

    except Exception as e:
        logger.exception(f"Google Search grounding failed for query: {query}")
        return json.dumps(
            {
                "error": f"Search failed: {str(e)}",
                "query": query,
                "results": [],
            }
        )


def _extract_grounding_results(response: Any, max_results: int) -> list[dict]:
    """
    Extract search results from Gemini's grounding metadata.

    Args:
        response: Gemini API response object
        max_results: Maximum number of results to return

    Returns:
        List of result dictionaries with title, url, description
    """
    results = []

    try:
        # Access grounding metadata from response
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            # Check for grounding metadata
            grounding_metadata = getattr(candidate, "grounding_metadata", None)
            if not grounding_metadata:
                continue

            # Extract web search queries
            web_search_queries = getattr(
                grounding_metadata, "web_search_queries", None
            ) or []

            # Extract grounding chunks (search results)
            grounding_chunks = getattr(
                grounding_metadata, "grounding_chunks", None
            ) or []

            # Process grounding chunks to extract URLs and titles
            seen_urls = set()
            for chunk in grounding_chunks[:max_results]:
                # Try to get web URI
                web = getattr(chunk, "web", None)
                if not web:
                    continue

                uri = getattr(web, "uri", None)
                if not uri or uri in seen_urls:
                    continue
                seen_urls.add(uri)

                # Try to get title from chunk
                title = getattr(chunk, "title", None) or ""

                # Try to get text/snippet
                text = getattr(chunk, "text", None) or ""
                if not text:
                    # Try alternative field names
                    text = getattr(chunk, "content", None) or ""

                results.append(
                    {
                        "index": len(results),
                        "title": title or uri,
                        "url": uri,
                        "description": text[:500] if text else "",  # Limit description length
                    }
                )

                if len(results) >= max_results:
                    break

    except Exception as e:
        logger.warning(f"Failed to extract grounding metadata: {e}")

    # If no results from grounding metadata, return empty list
    # The answer text will still be available in the response
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
        return json.dumps(
            {
                "error": "URL is required",
                "url": url,
            }
        )

    # Basic URL validation
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return json.dumps(
            {
                "error": f"Invalid URL format: {url}",
                "url": url,
            }
        )

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

            async with session.get(
                url, headers=headers, allow_redirects=True
            ) as response:
                if response.status != 200:
                    return json.dumps(
                        {
                            "error": f"HTTP {response.status}: Failed to fetch URL",
                            "url": url,
                            "status": response.status,
                        }
                    )

                # Check content type
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return json.dumps(
                        {
                            "error": f"Unsupported content type: {content_type}",
                            "url": url,
                            "content_type": content_type,
                        }
                    )

                # Read content with size limit (1MB max)
                content = await response.read()
                if len(content) > 1024 * 1024:  # 1MB limit
                    return json.dumps(
                        {
                            "error": "Page content too large (max 1MB)",
                            "url": url,
                            "size_bytes": len(content),
                        }
                    )

                # Decode HTML
                try:
                    html_content = content.decode("utf-8", errors="replace")
                except UnicodeDecodeError:
                    # Try other encodings
                    try:
                        html_content = content.decode("latin-1", errors="replace")
                    except Exception:
                        return json.dumps(
                            {
                                "error": "Failed to decode page content",
                                "url": url,
                            }
                        )

                # Extract text from HTML
                parser = TextExtractor()
                parser.feed(html_content)
                extracted_text = parser.get_text(max_length=5000)

                # Try to extract title from HTML
                title_match = re.search(
                    r"<title[^>]*>(.*?)</title>",
                    html_content,
                    re.IGNORECASE | re.DOTALL,
                )
                title = title_match.group(1).strip() if title_match else ""
                # Clean title HTML entities
                title = re.sub(r"<[^>]+>", "", title)
                title = title.replace("&nbsp;", " ").strip()

                return json.dumps(
                    {
                        "url": url,
                        "title": title or "No title",
                        "content": extracted_text,
                        "content_length": len(extracted_text),
                        "original_size": len(html_content),
                        "result_index": result_index,
                        "search_query": search_query,
                    },
                    ensure_ascii=False,
                )

    except TimeoutError:
        return json.dumps(
            {
                "error": "Request timeout: URL took too long to respond",
                "url": url,
            }
        )
    except aiohttp.ClientError as e:
        return json.dumps(
            {
                "error": f"Network error: {str(e)}",
                "url": url,
            }
        )
    except Exception as e:
        logger.exception(f"Failed to fetch web content from {url}")
        return json.dumps(
            {
                "error": f"Failed to fetch content: {str(e)}",
                "url": url,
            }
        )


async def analyze_text_results(
    query: str,
    results: list[dict],
    fetched_content: list[dict],
    gemini_client: Any,
) -> dict[str, Any]:
    """
    Analyze text search results using LLM.

    Args:
        query: Original search query
        results: Original search results
        fetched_content: List of fetched content dicts with 'url', 'title', 'content'
        gemini_client: Gemini client for analysis

    Returns:
        Dict with summary, key_points, and sources
    """
    if not fetched_content:
        return {
            "summary": "",
            "key_points": [],
            "sources": [],
        }

    # Build analysis prompt
    content_texts = []
    for idx, content in enumerate(fetched_content):
        url = content.get("url", "")
        title = content.get("title", "")
        text = content.get("content", "")
        if text:
            content_texts.append(
                f"Source {idx + 1} ({url}):\nTitle: {title}\nContent: {text[:2000]}\n"
            )

    if not content_texts:
        return {
            "summary": "",
            "key_points": [],
            "sources": [],
        }

    prompt = f"""Analyze the following search results for the query: "{query}"

{chr(10).join(content_texts)}

Provide:
1. A concise summary (2-3 sentences) of the most relevant information
2. 3-5 key points extracted from the sources
3. Which sources are most relevant

Format your response as JSON:
{{
    "summary": "brief summary here",
    "key_points": ["point 1", "point 2", ...],
    "relevant_sources": [0, 1, ...]  // indices of most relevant sources
}}"""

    try:
        response = await gemini_client.generate(
            system_prompt="You are a helpful assistant that analyzes web search results and extracts relevant information.",
            history=None,
            user_parts=[{"text": prompt}],
        )

        text_response = response.get("text", "").strip()

        # Try to parse JSON from response
        try:
            # Extract JSON if wrapped in markdown code blocks
            json_match = re.search(r"\{[^{}]*\}", text_response, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group(0))
            else:
                analysis = json.loads(text_response)
        except (json.JSONDecodeError, ValueError):
            # Fallback: treat entire response as summary
            analysis = {
                "summary": text_response[:500],
                "key_points": [],
                "relevant_sources": list(range(len(fetched_content))),
            }

        # Build sources list
        sources = []
        relevant_indices = set(analysis.get("relevant_sources", []))
        for idx, content in enumerate(fetched_content):
            sources.append(
                {
                    "index": idx,
                    "url": content.get("url", ""),
                    "title": content.get("title", ""),
                    "relevant": idx in relevant_indices,
                }
            )

        return {
            "summary": analysis.get("summary", ""),
            "key_points": analysis.get("key_points", []),
            "sources": sources,
        }
    except Exception as e:
        logger.warning(f"Failed to analyze text results: {e}")
        return {
            "summary": "",
            "key_points": [],
            "sources": [],
        }


SEARCH_WEB_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "search_web",
            "description": (
                "Шукати актуальну інформацію в інтернеті через Google Search (Gemini Grounding). "
                "Використовуй для пошуку поточної інформації, новин, фактів та даних після середини 2024 року. "
                "Повертає синтезовану відповідь на основі результатів пошуку та список джерел з індексами (0, 1, 2...). "
                "Використовуй fetch_web_content для отримання детального контенту з конкретних результатів. "
                "Search the web for current information via Google Search (Gemini Grounding). "
                "Use for finding up-to-date information, news, facts, and data after mid-2024. "
                "Returns a synthesized answer based on search results and a list of sources with indices (0, 1, 2...). "
                "Use fetch_web_content to get detailed content from specific results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Пошуковий запит / Search query",
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
