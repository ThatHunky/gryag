"""
Tool logging framework for GRYAG bot.

Provides standardized logging and telemetry for bot tools.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

# Import telemetry for usage tracking
try:
    from app.services import telemetry
except ImportError:
    # Fallback if telemetry not available
    telemetry = None

# Type for tool functions
ToolFunction = Callable[[dict[str, Any]], Awaitable[str]]

# Setup logger for tool framework
logger = logging.getLogger(__name__)


def log_tool_execution(tool_name: str):
    """
    Decorator to add comprehensive logging and telemetry to tool functions.

    Args:
        tool_name: Name of the tool for logging and telemetry

    Returns:
        Decorated function with logging and telemetry
    """

    def decorator(func: ToolFunction) -> ToolFunction:
        @functools.wraps(func)
        async def wrapper(params: dict[str, Any]) -> str:
            start_time = time.time()
            tool_logger = logging.getLogger(f"tools.{tool_name}")

            # Log tool invocation
            tool_logger.info(
                f"Tool '{tool_name}' invoked",
                extra={
                    "tool": tool_name,
                    "params": _sanitize_params(params),
                    "param_count": len(params) if params else 0,
                },
            )

            # Increment telemetry counter for tool usage
            if telemetry:
                telemetry.increment_counter(f"tools.{tool_name}.invoked")

            try:
                # Execute the tool function
                result = await func(params)
                execution_time = time.time() - start_time

                # Parse result to determine success/error
                try:
                    result_data = json.loads(result)
                    is_error = "error" in result_data

                    if is_error:
                        # Log error result
                        tool_logger.warning(
                            f"Tool '{tool_name}' completed with error",
                            extra={
                                "tool": tool_name,
                                "error": result_data.get("error", "Unknown error"),
                                "duration_ms": round(execution_time * 1000, 2),
                                "params": _sanitize_params(params),
                            },
                        )

                        if telemetry:
                            telemetry.increment_counter(f"tools.{tool_name}.error")
                    else:
                        # Log successful result
                        tool_logger.info(
                            f"Tool '{tool_name}' completed successfully",
                            extra={
                                "tool": tool_name,
                                "duration_ms": round(execution_time * 1000, 2),
                                "result_size": len(result),
                                "params": _sanitize_params(params),
                            },
                        )

                        if telemetry:
                            telemetry.increment_counter(f"tools.{tool_name}.success")

                except json.JSONDecodeError:
                    # Result is not JSON, treat as success
                    tool_logger.info(
                        f"Tool '{tool_name}' completed (non-JSON result)",
                        extra={
                            "tool": tool_name,
                            "duration_ms": round(execution_time * 1000, 2),
                            "result_size": len(result),
                            "params": _sanitize_params(params),
                        },
                    )

                    if telemetry:
                        telemetry.increment_counter(f"tools.{tool_name}.success")

                return result

            except Exception as e:
                execution_time = time.time() - start_time

                # Log unexpected exception
                tool_logger.error(
                    f"Tool '{tool_name}' failed with exception",
                    extra={
                        "tool": tool_name,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "duration_ms": round(execution_time * 1000, 2),
                        "params": _sanitize_params(params),
                    },
                    exc_info=True,
                )

                if telemetry:
                    telemetry.increment_counter(f"tools.{tool_name}.exception")

                # Re-raise the exception
                raise

        return wrapper

    return decorator


def _sanitize_params(params: dict[str, Any], max_length: int = 200) -> dict[str, Any]:
    """
    Sanitize parameters for logging to prevent overly long log entries.

    Args:
        params: Original parameters
        max_length: Maximum length for string values

    Returns:
        Sanitized parameters
    """
    if not params:
        return {}

    sanitized = {}
    for key, value in params.items():
        if isinstance(value, str) and len(value) > max_length:
            sanitized[key] = value[:max_length] + "..."
        elif isinstance(value, (dict, list)):
            # Convert complex objects to string representation
            str_repr = str(value)
            if len(str_repr) > max_length:
                sanitized[key] = str_repr[:max_length] + "..."
            else:
                sanitized[key] = str_repr
        else:
            sanitized[key] = value

    return sanitized


def log_tool_performance(
    tool_name: str,
    operation: str,
    duration: float,
    extra_data: dict[str, Any] | None = None,
):
    """
    Log performance metrics for tool operations.

    Args:
        tool_name: Name of the tool
        operation: Name of the operation
        duration: Duration in seconds
        extra_data: Additional data to log
    """
    tool_logger = logging.getLogger(f"tools.{tool_name}.performance")

    log_data = {
        "tool": tool_name,
        "operation": operation,
        "duration_ms": round(duration * 1000, 2),
    }

    if extra_data:
        log_data.update(extra_data)

    tool_logger.info(f"Performance: {tool_name}.{operation}", extra=log_data)

    # Record performance metric in telemetry
    if telemetry:
        # Convert duration to a more suitable metric format
        duration_ms = round(duration * 1000)
        telemetry.increment_counter(
            f"tools.{tool_name}.performance.{operation}", value=duration_ms
        )


class ToolLogger:
    """
    Tool-specific logger that provides consistent logging patterns.
    """

    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        self.logger = logging.getLogger(f"tools.{tool_name}")

    def debug(self, message: str, **extra):
        """Log debug message with tool context."""
        self.logger.debug(message, extra={"tool": self.tool_name, **extra})

    def info(self, message: str, **extra):
        """Log info message with tool context."""
        self.logger.info(message, extra={"tool": self.tool_name, **extra})

    def warning(self, message: str, **extra):
        """Log warning message with tool context."""
        self.logger.warning(message, extra={"tool": self.tool_name, **extra})

    def error(self, message: str, exc_info=False, **extra):
        """Log error message with tool context."""
        self.logger.error(
            message, extra={"tool": self.tool_name, **extra}, exc_info=exc_info
        )

    def performance(self, operation: str, duration: float, **extra):
        """Log performance data."""
        log_tool_performance(self.tool_name, operation, duration, extra)


# Example usage and testing
if __name__ == "__main__":
    import asyncio

    # Setup logging for testing
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    @log_tool_execution("test_tool")
    async def test_tool(params: dict[str, Any]) -> str:
        """Test tool function."""
        await asyncio.sleep(0.1)  # Simulate work

        if params.get("error"):
            return json.dumps({"error": "Test error"})
        else:
            return json.dumps({"result": "success", "input": params.get("input", "")})

    async def test():
        print("Testing tool logging framework...")

        # Test successful execution
        result1 = await test_tool({"input": "test data"})
        print(f"Success result: {result1}")

        # Test error execution
        result2 = await test_tool({"error": True})
        print(f"Error result: {result2}")

        # Test performance logging
        tool_logger = ToolLogger("example_tool")
        start = time.time()
        await asyncio.sleep(0.05)
        tool_logger.performance(
            "example_operation", time.time() - start, extra_param="test"
        )

    asyncio.run(test())
