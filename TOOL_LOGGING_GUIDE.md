# GRYAG Bot Tool Logging System

## Overview

The GRYAG bot now includes a comprehensive logging and telemetry system for all tools. This system provides visibility into tool usage, performance metrics, error tracking, and debugging information.

## Features

### 📊 **Comprehensive Metrics**
- **Invocation tracking** - Every tool call is logged
- **Success/Error rates** - Track tool reliability
- **Performance metrics** - Execution time monitoring
- **Parameter logging** - Input validation and debugging
- **Error categorization** - Different error types tracked

### 🔍 **Multi-Level Logging**
- **Tool-level logging** - High-level tool operations
- **Implementation logging** - Internal calculation steps
- **Performance logging** - Separate performance metrics
- **Error logging** - Detailed error information with stack traces

### 📈 **Telemetry Integration**
- **Usage counters** - `tools.{tool_name}.invoked`
- **Success counters** - `tools.{tool_name}.success`
- **Error counters** - `tools.{tool_name}.error`
- **Performance metrics** - `tools.{tool_name}.performance.{operation}`

## Implementation

### Core Components

1. **`app/services/tool_logging.py`** - Logging framework
2. **`app/services/calculator.py`** - Example implementation
3. **Tool decorator** - `@log_tool_execution("tool_name")`
4. **ToolLogger class** - Standardized logging interface

### Calculator Tool Metrics

The calculator tool now provides these logging events:

#### **Success Case:**
```
tools.calculator - INFO - Tool 'calculator' invoked
tools.calculator - DEBUG - Attempting calculation  
app.services.calculator.SafeCalculator - DEBUG - Starting expression evaluation
app.services.calculator.SafeCalculator - DEBUG - Expression parsed successfully into AST
app.services.calculator.SafeCalculator - DEBUG - Expression evaluation completed successfully
tools.calculator.performance - INFO - Performance: calculator.calculation
tools.calculator - INFO - Tool 'calculator' completed successfully
```

#### **Error Case:**
```
tools.calculator - INFO - Tool 'calculator' invoked
tools.calculator - DEBUG - Attempting calculation
app.services.calculator.SafeCalculator - DEBUG - Starting expression evaluation  
app.services.calculator.SafeCalculator - WARNING - Evaluation error
tools.calculator - WARNING - Calculation error: Division by zero
tools.calculator - WARNING - Tool 'calculator' completed with error
```

### Telemetry Counters

- `tools.calculator.invoked` - Total invocations
- `tools.calculator.success` - Successful calculations
- `tools.calculator.error` - Failed calculations  
- `tools.calculator.performance.calculation` - Performance timing

## Usage for New Tools

### 1. Using the Decorator (Recommended)

```python
from app.services.tool_logging import log_tool_execution, ToolLogger

tool_logger = ToolLogger("weather")

@log_tool_execution("weather")
async def weather_tool(params: dict[str, Any]) -> str:
    location = params.get("location", "")
    
    # Optional: Add detailed logging
    tool_logger.debug("Fetching weather data", location=location)
    
    try:
        # ... implementation ...
        tool_logger.performance("api_call", api_duration)
        return json.dumps({"result": "success"})
    except Exception as e:
        tool_logger.error(f"Weather API error: {e}", exc_info=True)
        raise
```

### 2. Manual Logging (For Complex Cases)

```python
from app.services.tool_logging import ToolLogger, log_tool_performance

async def complex_tool(params: dict[str, Any]) -> str:
    tool_logger = ToolLogger("complex_tool")
    
    tool_logger.info("Starting complex operation", params=params)
    
    start_time = time.time()
    try:
        # ... implementation ...
        duration = time.time() - start_time
        log_tool_performance("complex_tool", "full_operation", duration)
        return result
    except Exception as e:
        tool_logger.error("Complex operation failed", exc_info=True)
        raise
```

## Viewing Logs

### Development Environment
```bash
# Show all tool logs
docker compose logs -f | grep "tools\."

# Show only calculator logs  
docker compose logs -f | grep "tools.calculator"

# Show only errors
docker compose logs -f | grep "ERROR\|WARNING"

# Show performance metrics
docker compose logs -f | grep "Performance:"
```

### Log Levels
- **DEBUG** - Detailed implementation steps, AST parsing, internal operations
- **INFO** - Tool invocations, successful completions, performance metrics
- **WARNING** - Calculation errors, validation failures, recoverable issues
- **ERROR** - Unexpected exceptions, system errors, critical failures

## Monitoring & Alerting

### Key Metrics to Monitor

1. **Tool Error Rates**
   - `tools.{name}.error / tools.{name}.invoked` should be < 5%

2. **Performance Degradation**  
   - `tools.{name}.performance.{operation}` trending upward

3. **Usage Patterns**
   - Peak usage times via `tools.{name}.invoked`

### Log Analysis Queries

```bash
# Error rate for calculator
docker compose logs --since 1h | grep "tools.calculator" | grep -c "error"

# Average performance (manual calculation needed)  
docker compose logs --since 1h | grep "Performance: calculator.calculation"

# Most common errors
docker compose logs --since 1h | grep "Calculator error:" | sort | uniq -c
```

## Benefits

### 🐛 **Debugging**
- Trace exact execution path for failed calculations
- See parameter inputs that cause errors
- Understand performance bottlenecks

### 📊 **Monitoring**  
- Track tool adoption and usage patterns
- Monitor error rates and reliability
- Performance regression detection

### 🔧 **Optimization**
- Identify slow operations for optimization
- Find common error patterns for prevention
- Usage analytics for feature prioritization

### 🚨 **Alerting**
- Automated alerts on error rate spikes
- Performance degradation detection
- Usage anomaly detection

## Future Enhancements

### Planned Features
1. **Structured logging** - JSON format for better parsing
2. **Correlation IDs** - Track requests across components  
3. **Sampling** - Reduce log volume for high-traffic tools
4. **Metrics dashboard** - Visual monitoring interface
5. **Automated alerting** - Slack/email notifications

### Extension Points
- Custom telemetry backends (Prometheus, DataDog)
- Log aggregation (ELK stack, Grafana)
- Real-time monitoring dashboards
- Performance benchmarking suites

## Testing the Logging System

```bash
# Test calculator logging
docker compose exec bot python -c "
import asyncio
import logging
logging.basicConfig(level=logging.INFO)
from app.services.calculator import calculator_tool

async def test():
    await calculator_tool({'expression': '2+2'})
    await calculator_tool({'expression': '1/0'})  # Error case

asyncio.run(test())
"
```

The logging system is now production-ready and provides comprehensive visibility into tool behavior and performance!