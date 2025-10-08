# Search as Function Tool Implementation

**Date**: 2025-10-08  
**Status**: ✅ Complete  
**Related**: SDK migration from google-generativeai to google-genai

## Problem

Google's Gemini API has a critical limitation: **you cannot use both `google_search` grounding AND function calling tools in the same request**. This creates a conflict:

- `ENABLE_SEARCH_GROUNDING=true` with `{"google_search": {}}` format → Search works, but all function tools (memory, calculator, weather, etc.) are disabled
- Function tools enabled → Memory, calculator, weather work, but no search capability

Error encountered:
```
google.genai.errors.ClientError: 400 INVALID_ARGUMENT. 
{'error': {'code': 400, 'message': 'Tool use with function calling is unsupported', 'status': 'INVALID_ARGUMENT'}}
```

## Solution

Created a **custom search function tool** (`search_web`) that wraps Google Search grounding in a function calling interface. This allows:

✅ **All function tools work** (memory, calculator, weather, currency, polls, search_messages)  
✅ **Web search capability** via explicit `search_web` tool call  
✅ **No API conflicts** - everything uses function_declarations format

## Implementation

### 1. Created `app/services/search_tool.py`

New service that wraps Google Search grounding:

```python
async def search_web_tool(
    params: dict[str, Any],
    gemini_client: Any,
) -> str:
    """Search the web using Google Search grounding backend."""
    query = params.get("query", "")
    
    # Use google_search grounding directly via Gemini client
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )
    
    response = await gemini_client._client.aio.models.generate_content(
        model=gemini_client._model_name,
        contents=[{"role": "user", "parts": [{"text": query}]}],
        config=config,
    )
    
    # Return results as JSON
    return json.dumps({"query": query, "answer": response.text})
```

**Tool Definition**:
```python
SEARCH_WEB_TOOL_DEFINITION = {
    "function_declarations": [{
        "name": "search_web",
        "description": "Шукати інформацію в інтернеті через Google...",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    }]
}
```

### 2. Updated `app/handlers/chat.py`

**Removed** direct google_search grounding:
```python
# BEFORE (caused API error):
if settings.enable_search_grounding:
    retrieval_tool: dict[str, Any] = {"google_search": {}}
    tool_definitions.append(retrieval_tool)

# AFTER (function tool):
if settings.enable_search_grounding:
    tool_definitions.append(SEARCH_WEB_TOOL_DEFINITION)
```

**Added** search_web callback:
```python
if settings.enable_search_grounding:
    tracked_tool_callbacks["search_web"] = make_tracked_tool_callback(
        "search_web",
        lambda params: search_web_tool(params, gemini_client),
    )
```

### 3. Simplified `app/services/gemini.py`

Removed complex logic for handling mixed tools:

```python
# BEFORE: Complex branching for google_search vs function tools
if has_function_tools:
    # Use function tools, skip google_search
elif has_google_search:
    # Use google_search only

# AFTER: Simple conversion - all tools are function_declarations
if tools:
    converted_tools = []
    for tool_dict in tools:
        if "function_declarations" in tool_dict:
            converted_tools.append(types.Tool(**tool_dict))
    
    if converted_tools:
        config_params["tools"] = converted_tools
```

### 4. Updated `app/persona.py`

Added search_web to available tools section:
```python
# Available Tools

You have these tools, use them when people actually need them:
- `search_web` - search the internet for current info, news, facts (uses Google Search)
- `search_messages` - dig through past conversations
- `calculator` - math calculations
- `weather` - current weather and forecasts for any location
- `currency` - exchange rates and currency conversion
```

## How It Works

1. **User asks a question** requiring current information
2. **Gemini decides** to call `search_web` function with a query
3. **search_web_tool()** internally uses Google Search grounding:
   - Creates a separate Gemini API call with `google_search` tool
   - Sends the query to get grounded results
   - Returns formatted answer as JSON
4. **Main conversation** continues with search results integrated

## Benefits

✅ **No API limitations** - Everything uses function_declarations  
✅ **All tools work together** - Memory, calculator, weather, search  
✅ **Explicit search calls** - Bot consciously decides when to search  
✅ **Same Google backend** - Still uses official Google Search grounding  
✅ **Better debugging** - Search calls are logged as function calls  
✅ **Consistent interface** - All tools follow same pattern

## Configuration

No changes needed - uses existing `ENABLE_SEARCH_GROUNDING` setting:

```bash
# .env
ENABLE_SEARCH_GROUNDING=true  # Enables search_web tool
```

## Testing

1. **Basic search**: Ask about recent events/news
   - Bot should call `search_web` tool
   - Results should be integrated naturally

2. **Combined usage**: Ask question needing both search and calculation
   - Bot should use both `search_web` and `calculator`
   - No API errors should occur

3. **Memory + search**: Ask to remember something, then search
   - Both `remember_fact` and `search_web` should work
   - No conflicts

## Verification Commands

```bash
# Check bot logs for tool usage
docker compose logs bot -f | grep "search_web\|function tools"

# Should see:
# "Using 7 function tools" (search_web + 6 others when ENABLE_SEARCH_GROUNDING=true)
# "Tool call: search_web" when bot searches
```

## Files Changed

- **Created**: `app/services/search_tool.py` (new search wrapper)
- **Modified**: `app/handlers/chat.py` (tool registration)
- **Modified**: `app/services/gemini.py` (simplified tool handling)
- **Modified**: `app/persona.py` (documented search_web tool)

## Related Issues

- **SDK Migration**: Part of google-generativeai → google-genai migration
- **API Limitation**: Google's restriction on mixing grounding + functions
- **Search Grounding Verification**: Original goal was checking if search works

## Next Steps

1. ✅ Bot is running without errors
2. 🔄 Test search_web in real conversation
3. 📋 Monitor search quality and response times
4. 📋 Consider caching search results if needed
5. 📋 Add search result formatting improvements

## Known Limitations

- **Extra API call**: Each search requires a separate Gemini API call (counts against quota)
- **No streaming**: Search results come back complete, not streamed
- **Rate limits**: Search grounding has 500 requests/day limit on Free tier
- **Response format**: Results are text-based, not structured data

## Migration Path

If you want to revert to direct google_search grounding (losing function tools):

1. Remove `SEARCH_WEB_TOOL_DEFINITION` from tool_definitions
2. Add back `{"google_search": {}}` format in chat.py
3. Update gemini.py to handle mixed tool types again
4. Remove search_web from persona.py

Not recommended - function tools are more valuable than direct grounding.
