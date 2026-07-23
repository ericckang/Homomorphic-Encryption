from __future__ import annotations

import tenseal as ts

from he_common.operations import polynomial_power_depth


def run_pipeline(vector, params: dict, *, integer: bool) -> tuple[object, int]:
    operations = params.get("operations")
    encrypted_operands = params.get("encrypted_operands") or {}
    if not isinstance(operations, list) or not operations:
        raise ValueError("params.operations must be a non-empty list.")
    if len(operations) > 12:
        raise ValueError("Too many operations for this demo; limit is 12.")

    max_depth = 0
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Each operation must be an object.")
        op = operation.get("op")
        if op == "polynomial":
            vector = _apply_polynomial(vector, operation, encrypted_operands, integer=integer)
            term_powers = [int(term.get("power")) for term in operation.get("terms", [])]
            max_depth += max(polynomial_power_depth(power) for power in term_powers)
        elif op == "sum_reduce":
            vector = _sum_vector(vector)
        elif op == "mean_reduce":
            vector = _mean_vector(vector, integer=integer)
            max_depth += 1
        elif op == "dot_product_public":
            vector = _dot_product_public(vector, operation, integer=integer)
            max_depth += 1
        else:
            vector = _apply_basic_op(vector, operation, encrypted_operands, integer=integer)
            if op in {"square", "mul_encrypted_scalar"}:
                max_depth += 1

    return vector, max_depth


def _apply_basic_op(vector, operation: dict, encrypted_operands: dict, *, integer: bool):
    op = operation.get("op")

    if op == "add_scalar":
        value = _require_number(operation.get("value"), "value", integer=integer)
        return vector + _scalar_vector(vector, value)
    if op == "sub_scalar":
        value = _require_number(operation.get("value"), "value", integer=integer)
        return vector - _scalar_vector(vector, value)
    if op == "mul_scalar":
        value = _require_number(operation.get("value"), "value", integer=integer)
        return vector * value
    if op == "add_encrypted_scalar":
        return vector + _load_encrypted_operand(vector, operation, encrypted_operands, integer=integer)
    if op == "sub_encrypted_scalar":
        return vector - _load_encrypted_operand(vector, operation, encrypted_operands, integer=integer)
    if op == "mul_encrypted_scalar":
        return vector * _load_encrypted_operand(vector, operation, encrypted_operands, integer=integer)
    if op == "square":
        return _square_vector(vector)

    raise ValueError(f"Unsupported pipeline operation: {op}")


def _dot_product_public(vector, operation: dict, *, integer: bool):
    weights = operation.get("weights")
    if not isinstance(weights, list) or not weights:
        raise ValueError("dot_product_public requires a non-empty weights list.")
    checked = [_require_number(weight, "dot_product_public weight", integer=integer) for weight in weights]

    if hasattr(vector, "dot"):
        return vector.dot(checked)
    if hasattr(vector, "dot_"):
        clone = _clone_vector(vector)
        clone.dot_(checked)
        return clone

    product = vector * checked
    return _sum_vector(product)


def _mean_vector(vector, *, integer: bool):
    if integer:
        raise ValueError("mean_reduce is only supported for CKKS in this demo.")
    count = vector.size()
    if count <= 0:
        raise ValueError("Cannot compute the mean of an empty encrypted vector.")
    return _sum_vector(vector) * (1.0 / count)


def _sum_vector(vector):
    if hasattr(vector, "sum"):
        return vector.sum()
    if hasattr(vector, "sum_"):
        clone = _clone_vector(vector)
        clone.sum_()
        return clone
    raise ValueError("The current TenSEAL backend does not expose vector sum operations.")


def _clone_vector(vector):
    if hasattr(vector, "copy"):
        return vector.copy()
    raise ValueError("The current TenSEAL backend does not expose a safe vector copy helper.")


def _apply_polynomial(vector, operation: dict, encrypted_operands: dict, *, integer: bool):
    terms = operation.get("terms")
    if not isinstance(terms, list) or not terms:
        raise ValueError("polynomial operation requires a non-empty terms list.")

    powers = {1: vector}

    result = None
    for idx, term in enumerate(terms, start=1):
        power = _require_positive_int(term.get("power"), f"term {idx} power")
        power_vector = _power_vector(vector, power, powers)
        operand_key = term.get("operand_key")
        if operand_key:
            contribution = power_vector * _load_encrypted_operand_by_key(
                vector,
                operand_key,
                encrypted_operands,
                label=f"polynomial term {idx}",
            )
        else:
            coefficient = _require_number(
                term.get("coefficient", 1),
                f"term {idx} coefficient",
                integer=integer,
            )
            contribution = power_vector * coefficient
        result = contribution if result is None else result + contribution

    constant_operand_key = operation.get("constant_operand_key")
    if constant_operand_key:
        result = result + _load_encrypted_operand_by_key(
            vector,
            constant_operand_key,
            encrypted_operands,
            label="polynomial constant",
        )
    else:
        constant = operation.get("constant", 0)
        if constant:
            value = _require_number(constant, "polynomial constant", integer=integer)
            result = result + _scalar_vector(vector, value)

    return result


def _require_number(value, field: str, *, integer: bool = False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric.")
    if integer and not float(value).is_integer():
        raise ValueError(f"{field} must be an integer for BFV.")
    return int(value) if integer else float(value)


def _require_positive_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a positive integer.")
    if not float(value).is_integer():
        raise ValueError(f"{field} must be a positive integer.")
    result = int(value)
    if result <= 0:
        raise ValueError(f"{field} must be >= 1.")
    return result


def _power_vector(vector, exponent: int, cache: dict[int, object]):
    if exponent in cache:
        return cache[exponent]

    if exponent % 2 == 0:
        half = _power_vector(vector, exponent // 2, cache)
        cache[exponent] = _square_vector(half)
        return cache[exponent]

    lower = exponent // 2
    upper = exponent - lower
    cache[exponent] = _power_vector(vector, lower, cache) * _power_vector(vector, upper, cache)
    return cache[exponent]


def _square_vector(vector):
    if hasattr(vector, "square"):
        return vector.square()
    return vector * vector


def _scalar_vector(vector, value):
    return [value] * vector.size()


def _load_encrypted_operand(vector, operation: dict, encrypted_operands: dict, *, integer: bool):
    operand_key = operation.get("operand_key")
    if not isinstance(operand_key, str) or not operand_key:
        raise ValueError(f"{operation.get('op')} requires a valid operand_key.")
    return _load_encrypted_operand_by_key(
        vector,
        operand_key,
        encrypted_operands,
        label=str(operation.get("op", "operation")),
    )


def _load_encrypted_operand_by_key(vector, operand_key: str, encrypted_operands: dict, *, label: str):
    operand_payload = encrypted_operands.get(operand_key)
    if not isinstance(operand_payload, (bytes, bytearray)):
        raise ValueError(f"Missing encrypted operand bytes for key '{operand_key}' in {label}.")
    if _is_bfv_vector(vector):
        return ts.bfv_vector_from(vector.context(), bytes(operand_payload))
    return ts.ckks_vector_from(vector.context(), bytes(operand_payload))


def _is_bfv_vector(vector) -> bool:
    return vector.__class__.__name__.lower().startswith("bfv")
