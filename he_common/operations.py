from __future__ import annotations

import re
from typing import Any


ALLOWED_OPS = {"add_scalar", "sub_scalar", "mul_scalar", "square", "polynomial"}


def data_profile(data: list[float]) -> dict[str, Any]:
    all_integer = all(float(x).is_integer() for x in data)
    return {
        "vector_length": len(data),
        "numeric_kind": "integer" if all_integer else "float",
        "raw_values_shared_with_model": False,
    }


def sanitize_plan(plan: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    scheme = str(plan.get("scheme", "")).upper()
    if profile["numeric_kind"] == "float":
        scheme = "CKKS"
    if scheme not in {"BFV", "CKKS"}:
        scheme = "BFV" if profile["numeric_kind"] == "integer" else "CKKS"

    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("Planner did not return any operations.")

    clean_ops = [_sanitize_operation(operation, scheme) for operation in operations]
    return {
        "schema_name": _safe_schema_name(plan.get("schema_name", "general_task")),
        "scheme": scheme,
        "computation_type": "general_bfv" if scheme == "BFV" else "general_ckks",
        "operations": clean_ops,
        "result_label": str(plan.get("result_label", "result"))[:80],
        "plaintext_formula": str(plan.get("plaintext_formula", "element-wise HE pipeline"))[:200],
        "notes": str(plan.get("notes", ""))[:300],
    }


def estimate_depth(operations: list[dict[str, Any]]) -> int:
    depth = 0
    for operation in operations:
        if operation["op"] == "square":
            depth += 1
        elif operation["op"] == "polynomial":
            powers = [term["power"] for term in operation["terms"]]
            depth += max(polynomial_power_depth(power) for power in powers)
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
        elif op == "square":
            result = [x * x for x in result]
        elif op == "polynomial":
            constant = operation.get("constant", 0)
            result = [
                sum(term["coefficient"] * (x ** term["power"]) for term in operation["terms"])
                + constant
                for x in result
            ]
    return result


def _sanitize_operation(operation: Any, scheme: str) -> dict[str, Any]:
    if not isinstance(operation, dict):
        raise ValueError("Each planned operation must be a JSON object.")

    op = operation.get("op")
    if op not in ALLOWED_OPS:
        raise ValueError(f"Unsupported planned operation: {op}")

    if op in {"add_scalar", "sub_scalar", "mul_scalar"}:
        value = _as_number(operation.get("value"), integer=(scheme == "BFV"))
        return {"op": op, "value": value}

    if op == "square":
        return {"op": "square"}

    terms = operation.get("terms")
    if not isinstance(terms, list) or not terms:
        raise ValueError("Polynomial operation requires terms.")

    clean_terms = []
    for term in terms:
        power = _as_positive_int(term.get("power"), field="polynomial power")
        coefficient = _as_number(term.get("coefficient", 1), integer=(scheme == "BFV"))
        clean_terms.append({"power": power, "coefficient": coefficient})

    constant = _as_number(operation.get("constant", 0), integer=(scheme == "BFV"))
    return {"op": "polynomial", "terms": clean_terms, "constant": constant}


def _as_number(value: Any, *, integer: bool) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Expected a numeric operation value, got {value!r}")
    if integer:
        if not float(value).is_integer():
            raise ValueError("BFV operations must use integer scalar values.")
        return int(value)
    return float(value)


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


def _safe_schema_name(value: Any) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value).strip().lower()).strip("_")
    return name[:60] or "general_task"
