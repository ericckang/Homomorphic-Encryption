from __future__ import annotations

from typing import Any


def evaluate_formula_node(
    node: dict[str, Any],
    encrypted_inputs: dict[str, Any],
    encrypted_operands: dict[str, Any] | None = None,
):
    encrypted_operands = encrypted_operands or {}
    node_type = node.get("type")
    if node_type == "constant":
        value = float(node["value"])
        sample_vector = next(iter(encrypted_inputs.values()), None)
        if sample_vector is None:
            raise ValueError("Formula evaluation requires at least one encrypted input vector.")
        return [value] * sample_vector.size()
    if node_type == "encrypted_constant":
        operand_key = str(node.get("operand_key"))
        if operand_key not in encrypted_operands:
            raise ValueError(f"Missing encrypted constant operand '{operand_key}' for formula evaluation.")
        return encrypted_operands[operand_key]
    if node_type == "variable":
        name = str(node.get("name"))
        if name not in encrypted_inputs:
            raise ValueError(f"Missing encrypted input vector '{name}' for formula evaluation.")
        return encrypted_inputs[name]
    if node_type == "neg":
        operand = evaluate_formula_node(node["operand"], encrypted_inputs, encrypted_operands)
        return operand * -1

    left = evaluate_formula_node(node["left"], encrypted_inputs, encrypted_operands)
    right = evaluate_formula_node(node["right"], encrypted_inputs, encrypted_operands)

    if node_type == "add":
        return left + right
    if node_type == "sub":
        return left - right
    if node_type == "mul":
        if isinstance(left, list):
            return right * left[0]
        if isinstance(right, list):
            return left * right[0]
        return left * right
    if node_type == "pow":
        if isinstance(right, list):
            exponent = int(right[0])
        else:
            exponent = int(right)
        if exponent < 1:
            raise ValueError("Only positive integer exponents are supported in encrypted formulas.")
        result = left
        for _ in range(exponent - 1):
            result = result * left
        return result
    raise ValueError(f"Unsupported formula node type: {node_type}")


def formula_depth(node: dict[str, Any]) -> int:
    node_type = node.get("type")
    if node_type in {"constant", "encrypted_constant", "variable"}:
        return 0
    if node_type == "neg":
        return formula_depth(node["operand"])
    if node_type in {"add", "sub"}:
        return max(formula_depth(node["left"]), formula_depth(node["right"]))
    if node_type == "mul":
        return 1 + max(formula_depth(node["left"]), formula_depth(node["right"]))
    if node_type == "pow":
        exponent_node = node["right"]
        if exponent_node.get("type") not in {"constant", "encrypted_constant"}:
            raise ValueError("Exponent must be a constant.")
        exponent = int(exponent_node.get("value", 1))
        if exponent < 1:
            raise ValueError("Exponent must be >= 1.")
        return max(formula_depth(node["left"]), (exponent - 1).bit_length())
    raise ValueError(f"Unsupported formula node type: {node_type}")
