from __future__ import annotations

import ast
import re
from typing import Any


SUPPORTED_FORMULA_PROMPT_PREFIXES = (
    "prompt:",
    "task:",
    "instruction:",
)
SUPPORTED_FORMULA_EXPRESSION_PREFIXES = (
    "risk score func:",
    "formula:",
    "expression:",
)
SUPPORTED_BINARY_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Pow)
UNSUPPORTED_FORMULA_TOKENS = ("/", ">", "<", "log(", "if ", " else ")


def maybe_parse_formula_expression(task_prompt: str) -> ast.AST | None:
    try:
        expression = extract_formula_expression(task_prompt)
        return parse_formula_ast(expression)
    except Exception:
        return None


def looks_like_unsupported_formula_prompt(task_prompt: str) -> bool:
    lowered = task_prompt.lower()
    return any(token in lowered for token in UNSUPPORTED_FORMULA_TOKENS)


def extract_formula_expression(task_prompt: str) -> str:
    expression = task_prompt.strip()
    lowered = expression.lower()

    for prefix in SUPPORTED_FORMULA_EXPRESSION_PREFIXES:
        index = lowered.find(prefix)
        if index >= 0:
            expression = expression[index + len(prefix):].strip()
            lowered = expression.lower()
            break

    for prefix in SUPPORTED_FORMULA_PROMPT_PREFIXES:
        if lowered.startswith(prefix):
            expression = expression[len(prefix):].strip()
            lowered = expression.lower()
            break

    if ":" in expression and not any(marker in lowered for marker in SUPPORTED_FORMULA_EXPRESSION_PREFIXES):
        expression = expression.split(":", 1)[1].strip()
    if "=" in expression:
        expression = expression.split("=", 1)[1].strip()
    if not expression:
        raise ValueError("Could not parse a numeric formula from the task prompt.")
    return expression


def infer_result_column_name(task_prompt: str) -> str:
    lowered_prompt = task_prompt.lower()
    for prefix in SUPPORTED_FORMULA_EXPRESSION_PREFIXES:
        marker_index = lowered_prompt.find(prefix)
        if marker_index >= 0:
            return prefix.removesuffix(":").replace(" ", "_")

    match = re.search(r"([a-zA-Z_][a-zA-Z0-9_\s]*)=", task_prompt)
    if not match:
        return "computed_feature"
    label = match.group(1).strip().lower()
    label = re.sub(r"^(compute|calculate|calculated)\s+", "", label)
    return re.sub(r"\s+", "_", label) or "computed_feature"


def parse_formula_ast(expression: str) -> ast.AST:
    normalized_expression = expression.strip().replace("^", "**")
    if not normalized_expression:
        raise ValueError("Could not parse a numeric formula from the task prompt.")
    parsed = ast.parse(normalized_expression, mode="eval")
    validate_formula_ast(parsed.body)
    return parsed.body


def validate_formula_ast(node: ast.AST) -> None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, SUPPORTED_BINARY_OPS):
        validate_formula_ast(node.left)
        validate_formula_ast(node.right)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        validate_formula_ast(node.operand)
        return
    raise ValueError("Unsupported computed CSV formula. Use only numeric columns, constants, +, -, *, and ^.")


def referenced_variables(node: ast.AST) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id not in seen:
            seen.add(child.id)
            ordered.append(child.id)
    return ordered


def evaluate_formula_ast(node: ast.AST, row_env: dict[str, float]) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in row_env:
        return float(row_env[node.id])
    if isinstance(node, ast.BinOp):
        left = evaluate_formula_ast(node.left, row_env)
        right = evaluate_formula_ast(node.right, row_env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Pow):
            return left ** right
        raise ValueError("Only +, -, *, and ^ are supported in computed CSV formulas.")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -evaluate_formula_ast(node.operand, row_env)
    raise ValueError("Unsupported computed CSV formula. Use only numeric columns, constants, +, -, *, and ^.")


def serialize_formula_node(node: ast.AST) -> dict[str, Any]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return {"type": "constant", "value": float(node.value)}
    if isinstance(node, ast.Name):
        return {"type": "variable", "name": node.id}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return {"type": "neg", "operand": serialize_formula_node(node.operand)}
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            op_name = "add"
        elif isinstance(node.op, ast.Sub):
            op_name = "sub"
        elif isinstance(node.op, ast.Mult):
            op_name = "mul"
        elif isinstance(node.op, ast.Pow):
            op_name = "pow"
        else:
            raise ValueError("Unsupported formula operator.")
        return {
            "type": op_name,
            "left": serialize_formula_node(node.left),
            "right": serialize_formula_node(node.right),
        }
    raise ValueError("Unsupported computed CSV formula. Use only numeric columns, constants, +, -, *, and ^.")
