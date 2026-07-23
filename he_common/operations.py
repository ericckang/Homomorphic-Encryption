from __future__ import annotations

import re
from typing import Any


ALLOWED_OPS = {
    "add_scalar",
    "sub_scalar",
    "mul_scalar",
    "add_encrypted_scalar",
    "sub_encrypted_scalar",
    "mul_encrypted_scalar",
    "square",
    "polynomial",
    "sum_reduce",
    "mean_reduce",
    "dot_product_public",
}
REDUCTION_OPS = {"sum_reduce", "mean_reduce", "dot_product_public"}


def data_profile(data: list[float], input_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    all_integer = all(float(x).is_integer() for x in data)
    profile = {
        "vector_length": len(data),
        "numeric_kind": "integer" if all_integer else "float",
        "raw_values_shared_with_model": False,
    }
    if input_metadata and input_metadata.get("input_kind") == "table":
        profile.update(
            {
                "input_kind": "table",
                "row_count": input_metadata.get("row_count", len(data)),
                "columns": input_metadata.get("columns", []),
                "selected_column": input_metadata.get("selected_column"),
            }
        )
    else:
        profile["input_kind"] = "vector"
    return profile


def sanitize_plan(plan: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    scheme = str(plan.get("scheme", "")).upper()
    requested_operations = plan.get("operations")
    if not isinstance(requested_operations, list) or not requested_operations:
        raise ValueError("Planner did not return any operations.")

    target_column = _resolve_target_column(plan, profile)
    selected_kind = _selected_numeric_kind(profile, target_column)

    wants_ckks = selected_kind == "float" or any(
        operation.get("op") in {"mean_reduce", "square", "polynomial"}
        for operation in requested_operations
        if isinstance(operation, dict)
    )
    if wants_ckks:
        scheme = "CKKS"
    if scheme not in {"BFV", "CKKS"}:
        scheme = "BFV" if selected_kind == "integer" else "CKKS"

    clean_ops = [_sanitize_operation(operation, scheme, profile) for operation in requested_operations]
    _validate_operation_order(clean_ops)
    result_shape = _infer_result_shape(clean_ops)
    sanitized_plan = {
        "schema_name": _safe_schema_name(plan.get("schema_name", "general_task")),
        "scheme": scheme,
        "computation_type": "general_bfv" if scheme == "BFV" else "general_ckks",
        "operations": clean_ops,
        "result_shape": result_shape,
        "result_label": str(plan.get("result_label", "result"))[:80],
        "plaintext_formula": str(plan.get("plaintext_formula", "element-wise HE pipeline"))[:200],
        "notes": str(plan.get("notes", ""))[:300],
        "target_column": target_column,
    }
    sanitized_plan["server_display_formula"] = build_server_display_formula(sanitized_plan)
    return sanitized_plan


def estimate_depth(operations: list[dict[str, Any]]) -> int:
    depth = 0
    for operation in operations:
        if operation["op"] == "square":
            depth += 1
        elif operation["op"] == "polynomial":
            powers = [term["power"] for term in operation["terms"]]
            depth += max(polynomial_power_depth(power) for power in powers)
        elif operation["op"] in {"mean_reduce", "dot_product_public"}:
            depth += 1
    return depth


def apply_plaintext_pipeline(data: list[float], operations: list[dict[str, Any]]) -> list[float]:
    result = list(data)
    for operation in operations:
        op = operation["op"]
        if op == "add_scalar":
            result = [x + operation["value"] for x in result]
        elif op == "sub_scalar":
            result = [x - operation["value"] for x in result]
        elif op == "mul_scalar":
            result = [x * operation["value"] for x in result]
        elif op == "add_encrypted_scalar":
            result = [x + operation["value"] for x in result]
        elif op == "sub_encrypted_scalar":
            result = [x - operation["value"] for x in result]
        elif op == "mul_encrypted_scalar":
            result = [x * operation["value"] for x in result]
        elif op == "square":
            result = [x * x for x in result]
        elif op == "polynomial":
            constant = operation.get("constant", 0)
            result = [
                sum(term["coefficient"] * (x ** term["power"]) for term in operation["terms"])
                + constant
                for x in result
            ]
        elif op == "sum_reduce":
            result = [sum(result)]
        elif op == "mean_reduce":
            result = [sum(result) / len(result)]
        elif op == "dot_product_public":
            weights = operation["weights"]
            result = [sum(x * weight for x, weight in zip(result, weights))]
    return result


def normalize_decrypted_result(plan: dict[str, Any], decrypted: list[float]) -> list[float]:
    if plan.get("result_shape") != "scalar":
        return decrypted
    if not decrypted:
        raise ValueError("Decrypted result is empty.")
    return [decrypted[0]]


def _sanitize_operation(operation: Any, scheme: str, profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(operation, dict):
        raise ValueError("Each planned operation must be a JSON object.")

    op = operation.get("op")
    if op not in ALLOWED_OPS:
        raise ValueError(f"Unsupported planned operation: {op}")

    if op in {
        "add_scalar",
        "sub_scalar",
        "mul_scalar",
        "add_encrypted_scalar",
        "sub_encrypted_scalar",
        "mul_encrypted_scalar",
    }:
        value = _as_number(operation.get("value"), integer=(scheme == "BFV"))
        clean_operation = {"op": op, "value": value}
        if op in {"add_encrypted_scalar", "sub_encrypted_scalar", "mul_encrypted_scalar"}:
            operand_key = operation.get("operand_key")
            if not isinstance(operand_key, str) or not operand_key.strip():
                raise ValueError(f"{op} requires a non-empty operand_key.")
            clean_operation["operand_key"] = operand_key.strip()
        return clean_operation

    if op == "square":
        return {"op": "square"}

    if op == "sum_reduce":
        return {"op": "sum_reduce"}

    if op == "mean_reduce":
        if scheme != "CKKS":
            raise ValueError("mean_reduce requires CKKS because this demo does not support encrypted division in BFV.")
        return {"op": "mean_reduce"}

    if op == "dot_product_public":
        weights = _as_number_list(
            operation.get("weights"),
            integer=(scheme == "BFV"),
            field="dot_product_public weights",
        )
        if len(weights) != profile["vector_length"]:
            raise ValueError(
                "dot_product_public weights must match the encrypted vector length known to the agent."
            )
        return {"op": "dot_product_public", "weights": weights}

    terms = operation.get("terms")
    if not isinstance(terms, list) or not terms:
        raise ValueError("Polynomial operation requires terms.")

    clean_terms = []
    for term in terms:
        power = _as_positive_int(term.get("power"), field="polynomial power")
        coefficient = _as_number(term.get("coefficient", 1), integer=(scheme == "BFV"))
        clean_term = {"power": power, "coefficient": coefficient}
        operand_key = term.get("operand_key")
        if operand_key is not None:
            if not isinstance(operand_key, str) or not operand_key.strip():
                raise ValueError("Polynomial term operand_key must be a non-empty string.")
            clean_term["operand_key"] = operand_key.strip()
        clean_terms.append(clean_term)

    constant = _as_number(operation.get("constant", 0), integer=(scheme == "BFV"))
    clean_operation = {"op": "polynomial", "terms": clean_terms, "constant": constant}
    constant_operand_key = operation.get("constant_operand_key")
    if constant_operand_key is not None:
        if not isinstance(constant_operand_key, str) or not constant_operand_key.strip():
            raise ValueError("Polynomial constant_operand_key must be a non-empty string.")
        clean_operation["constant_operand_key"] = constant_operand_key.strip()
    return clean_operation


def _as_number(value: Any, *, integer: bool) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Expected a numeric operation value, got {value!r}")
    if integer:
        if not float(value).is_integer():
            raise ValueError("BFV operations must use integer scalar values.")
        return int(value)
    return float(value)


def _as_number_list(value: Any, *, integer: bool, field: str) -> list[int] | list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list of numbers.")
    return [_as_number(item, integer=integer) for item in value]


def polynomial_power_depth(power: int) -> int:
    """
    Minimal multiplicative depth for x^power using exponentiation by squaring.
    """
    validated = _as_positive_int(power, field="polynomial power")
    return (validated - 1).bit_length()


def _as_positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a positive integer.")
    if not float(value).is_integer():
        raise ValueError(f"{field} must be a positive integer.")
    result = int(value)
    if result <= 0:
        raise ValueError(f"{field} must be >= 1.")
    return result


def _resolve_target_column(plan: dict[str, Any], profile: dict[str, Any]) -> str | None:
    if profile.get("input_kind") != "table":
        return None

    columns = profile.get("columns") or []
    available = {str(col.get("name")): str(col.get("kind")) for col in columns if isinstance(col, dict)}
    requested = plan.get("target_column")
    fallback = profile.get("selected_column")
    candidate = requested if isinstance(requested, str) and requested.strip() else fallback
    if not isinstance(candidate, str) or candidate not in available:
        raise ValueError("Planner must choose a valid numeric CSV column.")
    if available[candidate] not in {"integer", "float"}:
        raise ValueError(f"Selected CSV column '{candidate}' is not numeric.")
    return candidate


def _selected_numeric_kind(profile: dict[str, Any], target_column: str | None) -> str:
    if profile.get("input_kind") != "table":
        return str(profile["numeric_kind"])
    columns = profile.get("columns") or []
    for column in columns:
        if isinstance(column, dict) and column.get("name") == target_column:
            kind = str(column.get("kind", ""))
            if kind in {"integer", "float"}:
                return kind
            break
    raise ValueError(f"Unable to determine numeric kind for selected column '{target_column}'.")


def _safe_schema_name(value: Any) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value).strip().lower()).strip("_")
    return name[:60] or "general_task"


def _infer_result_shape(operations: list[dict[str, Any]]) -> str:
    if operations and operations[-1]["op"] in REDUCTION_OPS:
        return "scalar"
    return "vector"


def _validate_operation_order(operations: list[dict[str, Any]]) -> None:
    reductions = [idx for idx, operation in enumerate(operations) if operation["op"] in REDUCTION_OPS]
    if not reductions:
        return
    if len(reductions) > 1:
        raise ValueError("Only one reduction operation is allowed per plan.")
    if reductions[0] != len(operations) - 1:
        raise ValueError("Reduction operations must be the final step in the HE pipeline.")


def build_server_display_formula(plan: dict[str, Any]) -> str:
    expression = str(plan.get("target_column") or "x")
    for operation in plan.get("operations", []):
        op = operation.get("op")
        if op == "add_scalar":
            expression = f"({expression} + {operation['value']})"
        elif op == "sub_scalar":
            expression = f"({expression} - {operation['value']})"
        elif op == "mul_scalar":
            expression = f"({operation['value']} * {expression})"
        elif op == "add_encrypted_scalar":
            expression = f"({expression} + ⟦c⟧)"
        elif op == "sub_encrypted_scalar":
            expression = f"({expression} - ⟦c⟧)"
        elif op == "mul_encrypted_scalar":
            expression = f"(⟦c⟧ * {expression})"
        elif op == "square":
            expression = f"({expression})^2"
        elif op == "polynomial":
            expression = _polynomial_display_formula(operation, expression)
        elif op == "sum_reduce":
            expression = f"sum({expression})"
        elif op == "mean_reduce":
            expression = f"mean({expression})"
        elif op == "dot_product_public":
            expression = f"dot_public({expression}, w)"
    return expression


def _polynomial_display_formula(operation: dict[str, Any], variable: str = "x") -> str:
    parts: list[str] = []
    for term in operation.get("terms", []):
        coefficient = "⟦c⟧" if term.get("operand_key") else term["coefficient"]
        power = term["power"]
        if power == 1:
            parts.append(f"{coefficient}*{variable}")
        else:
            parts.append(f"{coefficient}*{variable}^{power}")
    constant = "⟦c⟧" if operation.get("constant_operand_key") else operation.get("constant", 0)
    if constant:
        parts.append(str(constant))
    return " + ".join(parts) if parts else "0"
