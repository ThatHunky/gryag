"""
Calculator tool for GRYAG bot.

Provides safe mathematical expression evaluation without external dependencies.
Uses AST-based evaluation to prevent code injection attacks.
"""

from __future__ import annotations

import ast
import json
import logging
import math
import operator
import time
from typing import Any

# Import telemetry for usage tracking
try:
    from app.services import telemetry
    from app.services.tool_logging import log_tool_execution, ToolLogger
except ImportError:
    # Fallback if telemetry not available
    telemetry = None
    log_tool_execution = lambda name: lambda f: f  # No-op decorator
    ToolLogger = None

# Setup logger for calculator tool
logger = logging.getLogger(__name__)
tool_logger = ToolLogger("calculator") if ToolLogger else None


class SafeCalculator:
    """Safe mathematical expression evaluator using AST parsing."""

    # Allowed operators for mathematical expressions
    SAFE_OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    # Allowed functions for mathematical expressions
    SAFE_FUNCTIONS = {
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "ceil": math.ceil,
        "floor": math.floor,
        "pi": math.pi,
        "e": math.e,
    }

    def __init__(self):
        """Initialize the calculator."""
        self.logger = logging.getLogger(f"{__name__}.SafeCalculator")

    def _evaluate_node(self, node: ast.AST) -> float:
        """
        Recursively evaluate an AST node.

        Args:
            node: AST node to evaluate

        Returns:
            Numerical result of the evaluation

        Raises:
            ValueError: If the expression contains unsafe operations
            TypeError: If operands are invalid
        """
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            else:
                raise ValueError(f"Unsupported constant type: {type(node.value)}")

        elif isinstance(node, ast.Num):  # Python < 3.8 compatibility
            if isinstance(node.n, (int, float)):
                return float(node.n)
            else:
                raise ValueError(f"Unsupported number type: {type(node.n)}")

        elif isinstance(node, ast.Name):
            if node.id in self.SAFE_FUNCTIONS:
                return self.SAFE_FUNCTIONS[node.id]
            else:
                raise ValueError(f"Unsupported name: {node.id}")

        elif isinstance(node, ast.BinOp):
            left = self._evaluate_node(node.left)
            right = self._evaluate_node(node.right)
            op_type = type(node.op)

            if op_type not in self.SAFE_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")

            try:
                result = self.SAFE_OPERATORS[op_type](left, right)

                # Check for division by zero
                if math.isinf(result) or math.isnan(result):
                    raise ValueError("Division by zero or invalid operation")

                return result
            except ZeroDivisionError:
                raise ValueError("Division by zero")
            except (OverflowError, ValueError) as e:
                raise ValueError(f"Mathematical error: {e}")

        elif isinstance(node, ast.UnaryOp):
            operand = self._evaluate_node(node.operand)
            op_type = type(node.op)

            if op_type not in self.SAFE_OPERATORS:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")

            return self.SAFE_OPERATORS[op_type](operand)

        elif isinstance(node, ast.Call):
            func_name = node.func.id if isinstance(node.func, ast.Name) else None

            if func_name not in self.SAFE_FUNCTIONS:
                raise ValueError(f"Unsupported function: {func_name}")

            func = self.SAFE_FUNCTIONS[func_name]
            args = [self._evaluate_node(arg) for arg in node.args]

            try:
                result = func(*args)

                if math.isinf(result) or math.isnan(result):
                    raise ValueError("Function returned invalid result")

                return result
            except (TypeError, ValueError, OverflowError) as e:
                raise ValueError(f"Function error: {e}")

        else:
            raise ValueError(f"Unsupported AST node type: {type(node).__name__}")

    def evaluate(self, expression: str) -> float:
        """
        Safely evaluate a mathematical expression.

        Args:
            expression: Mathematical expression as string

        Returns:
            Numerical result

        Raises:
            ValueError: If expression is invalid or unsafe
        """
        if not expression or not isinstance(expression, str):
            raise ValueError("Expression must be a non-empty string")

        expression = expression.strip()
        if not expression:
            raise ValueError("Expression cannot be empty")

        # Basic length check to prevent extremely long expressions
        if len(expression) > 500:
            self.logger.warning(
                "Expression too long for evaluation",
                extra={"expression_length": len(expression), "max_length": 500},
            )
            raise ValueError("Expression too long")

        self.logger.debug(
            "Starting expression evaluation",
            extra={"expression": expression, "expression_length": len(expression)},
        )

        try:
            # Parse the expression into an AST
            tree = ast.parse(expression, mode="eval")
            self.logger.debug("Expression parsed successfully into AST")

            # Evaluate the expression
            result = self._evaluate_node(tree.body)

            # Final validation
            if math.isinf(result):
                self.logger.warning(
                    "Expression evaluation resulted in infinity",
                    extra={"expression": expression},
                )
                raise ValueError("Result is infinite")
            elif math.isnan(result):
                self.logger.warning(
                    "Expression evaluation resulted in NaN",
                    extra={"expression": expression},
                )
                raise ValueError("Result is not a number")

            self.logger.debug(
                "Expression evaluation completed successfully",
                extra={"expression": expression, "result": result},
            )

            return result

        except SyntaxError as e:
            self.logger.warning(
                "Syntax error in expression",
                extra={"expression": expression, "syntax_error": str(e)},
            )
            raise ValueError(f"Invalid syntax: {e}")
        except (TypeError, ValueError) as e:
            self.logger.warning(
                "Evaluation error",
                extra={
                    "expression": expression,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise ValueError(str(e))
        except Exception as e:
            self.logger.error(
                "Unexpected error during expression evaluation",
                extra={
                    "expression": expression,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            raise ValueError(f"Calculation error: {e}")


# Global calculator instance
_calculator = SafeCalculator()


@log_tool_execution("calculator")
async def calculator_tool(params: dict[str, Any]) -> str:
    """
    Calculator tool function for GRYAG bot.

    Safely evaluates mathematical expressions and returns JSON response.

    Args:
        params: Tool parameters containing 'expression' key

    Returns:
        JSON string with calculation result or error
    """
    expression = params.get("expression", "").strip()

    if not expression:
        return json.dumps(
            {"error": "Потрібно вказати математичний вираз", "expression": expression}
        )

    try:
        if tool_logger:
            tool_logger.debug(
                "Attempting calculation",
                expression=expression,
                expression_length=len(expression),
            )

        start_time = time.time()
        result_value = _calculator.evaluate(expression)
        calculation_duration = time.time() - start_time

        if tool_logger:
            tool_logger.performance(
                "calculation", calculation_duration, expression_length=len(expression)
            )

        # Format result nicely
        if result_value.is_integer():
            formatted_result = int(result_value)
        else:
            # Round to 10 decimal places to avoid floating point noise
            formatted_result = round(result_value, 10)

        return json.dumps(
            {
                "expression": expression,
                "result": formatted_result,
                "formatted": f"{expression} = {formatted_result}",
            }
        )

    except ValueError as e:
        if tool_logger:
            tool_logger.warning(f"Calculation error: {e}", expression=expression)
        return json.dumps({"error": str(e), "expression": expression})
    except Exception as e:
        if tool_logger:
            tool_logger.error(
                f"Unexpected calculation error: {e}",
                expression=expression,
                exc_info=True,
            )
        return json.dumps(
            {"error": f"Помилка обчислення: {e}", "expression": expression}
        )


# Tool definition for registration
CALCULATOR_TOOL_DEFINITION = {
    "function_declarations": [
        {
            "name": "calculator",
            "description": "Виконати математичні обчислення з підтримкою основних операцій та функцій",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Математичний вираз для обчислення (наприклад: '2+2', 'sqrt(16)', 'sin(pi/2)')",
                    }
                },
                "required": ["expression"],
            },
        }
    ]
}


if __name__ == "__main__":
    # Test the calculator
    test_expressions = [
        "2 + 2",
        "10 / 3",
        "sqrt(16)",
        "sin(pi/2)",
        "2**3",
        "abs(-5)",
        "ceil(3.14159)",
        "max(1, 2, 3)",
        "invalid expression",
        "1/0",
    ]

    import asyncio

    async def test():
        for expr in test_expressions:
            result = await calculator_tool({"expression": expr})
            print(f"{expr}: {result}")

    asyncio.run(test())
