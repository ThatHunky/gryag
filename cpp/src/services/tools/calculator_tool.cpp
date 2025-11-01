#include "gryag/services/tools/calculator_tool.hpp"

#include <cmath>
#include <sstream>
#include <stdexcept>

namespace gryag::services::tools {

namespace {

double evaluate_expression(const std::string& expression) {
    std::stringstream ss(expression);
    double result = 0.0;
    double operand = 0.0;
    char op = '+';

    while (ss >> operand) {
        switch (op) {
            case '+':
                result += operand;
                break;
            case '-':
                result -= operand;
                break;
            case '*':
                result *= operand;
                break;
            case '/':
                if (operand == 0.0) {
                    throw std::runtime_error("Ділення на нуль заборонено");
                }
                result /= operand;
                break;
            default:
                throw std::runtime_error("Невідома операція");
        }
        ss >> op;
    }

    return result;
}

}  // namespace

void register_calculator_tool(ToolRegistry& registry) {
    registry.register_tool(
        ToolDefinition{
            .name = "calculator",
            .description = "Обчислює прості математичні вирази",
            .parameters = {
                {"type", "object"},
                {"properties", {
                    {"expression", {
                        {"type", "string"},
                        {"description", "Математичний вираз для обчислення"}
                    }}
                }},
                {"required", {"expression"}}
            }
        },
        [](const nlohmann::json& args, ToolContext&) {
            const auto expression = args.value("expression", "");
            if (expression.empty()) {
                throw std::runtime_error("Порожній вираз");
            }
            const auto result = evaluate_expression(expression);
            return nlohmann::json{{"result", result}};
        }
    );
}

}  // namespace gryag::services::tools
