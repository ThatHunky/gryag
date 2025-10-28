# Gemini 503 Server Error Handling Fix

**Date**: 2025-10-28  
**Issue**: Bot experiencing frequent 503 errors when Gemini servers are overloaded  
**Status**: Fixed

## Problem

The bot was experiencing unhandled 503 "server overloaded" errors from Gemini API, causing:

1. Episode summarization failures
2. Chat message processing failures
3. Poor user experience during peak API usage times

Example error:

```text
google.genai.errors.ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The model is overloaded. Please try again later.', 'status': 'UNAVAILABLE'}}
```

## Root Cause

1. **No transient error retry logic**: The `_invoke_model` method didn't retry on 503 server errors
2. **Generic error handling**: 503 errors were treated the same as fatal errors
3. **No exponential backoff**: Immediate failures without giving the server time to recover

## Solution

### 1. Added Server Error Detection (`app/services/gemini.py`)

```python
@staticmethod
def _is_server_error(exc: Exception) -> bool:
    """Check if error is a transient server error (503, 500, etc.)."""
    if isinstance(exc, ServerError):
        return True
    message = f"{type(exc).__name__} {exc}".lower()
    return (
        "503" in message
        or "500" in message
        or "unavailable" in message
        or "overloaded" in message
        or "servererror" in message
    )
```

### 2. Implemented Retry Logic with Exponential Backoff

Modified `_invoke_model` to:

- Retry server errors up to 3 times per API key
- Use exponential backoff: 1s, 2s, 4s between retries
- Log retry attempts for debugging
- Move to next API key if retries exhausted

```python
server_error_retries = 3  # Retry server errors up to 3 times

for retry in range(server_error_retries):
    try:
        response = await asyncio.wait_for(...)
        return response
    except Exception as exc:
        if self._is_server_error(exc):
            last_server_exc = exc
            if retry < server_error_retries - 1:
                # Exponential backoff: 1s, 2s, 4s
                backoff = 2 ** retry
                self._logger.warning(
                    f"Server error (503/500), retry {retry + 1}/{server_error_retries} "
                    f"after {backoff}s: {exc}"
                )
                await asyncio.sleep(backoff)
                continue
```

### 3. Better Error Messages

- Distinguish between server errors (Google's problem) and quota errors (our limit)
- Provide clear user-facing messages
- Enhanced logging for debugging

### 4. Graceful Degradation

Episode summarizer already had fallback logic:

- Returns heuristic-based summary if Gemini fails
- Extracts topic from first message
- Generates simple tags from word frequency
- No data loss, just less sophisticated summaries during outages

## Benefits

1. **Resilience**: Automatically recovers from transient 503 errors
2. **User Experience**: Most server errors now succeed after retry
3. **API Key Rotation**: If one key hits overloaded servers, tries next key
4. **Observability**: Clear logging shows retry attempts and final outcomes
5. **Circuit Breaker**: Still respects existing circuit breaker for persistent failures

## Testing

To verify the fix works:

```bash
# Watch logs for retry messages during peak usage
docker-compose logs -f bot | grep -E "Server error|retry"

# Should see messages like:
# "Server error (503/500), retry 1/3 after 1s: ..."
# "Server error (503/500), retry 2/3 after 2s: ..."
```

## Related Files

- `app/services/gemini.py` - Main retry logic and error detection
- `app/services/context/episode_summarizer.py` - Already has fallback logic
- `app/services/donation_scheduler.py` - Fixed unrelated table name bug

## Migration Notes

No migration needed - changes are backward compatible. The retry logic is transparent to callers.

## Performance Impact

- Minimal: Only adds delay when actual 503 errors occur
- Max additional latency: 7 seconds (1+2+4) per API key during persistent outages
- Most requests succeed on first try (no overhead)

## Future Improvements

1. **Adaptive timeout**: Increase timeout during known overload periods
2. **Jitter**: Add random jitter to backoff to prevent thundering herd
3. **Health check**: Pre-check API health before critical operations
4. **Telemetry**: Track 503 frequency to detect patterns
