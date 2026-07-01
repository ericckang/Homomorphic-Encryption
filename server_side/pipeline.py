from __future__ import annotations


def run_pipeline(vector, params: dict, *, integer: bool) -> tuple[object, int]:
    operations = params.get("operations")
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
            vector = _apply_polynomial(vector, operation, integer=integer)
            term_powers = [int(term.get("power")) for term in operation.get("terms", [])]
            max_depth += max(power.bit_length() - 1 for power in term_powers)
        else:
            vector = _apply_basic_op(vector, operation, integer=integer)
            if op == "square":
                max_depth += 1

    return vector, max_depth


def _apply_basic_op(vector, operation: dict, *, integer: bool):
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
    if op == "square":
        return vector.square()

    raise ValueError(f"Unsupported pipeline operation: {op}")


def _apply_polynomial(vector, operation: dict, *, integer: bool):
    terms = operation.get("terms")
    if not isinstance(terms, list) or not terms:
        raise ValueError("polynomial operation requires a non-empty terms list.")

    allowed_powers = {1, 2, 4, 8, 16}
    max_power = max(int(term.get("power")) for term in terms)
    if max_power not in allowed_powers:
        raise ValueError("polynomial powers must be one of 1, 2, 4, 8, 16.")

    powers = {1: vector}
    current = vector
    for power in [2, 4, 8, 16]:
        if power > max_power:
            break
        current = current.square()
        powers[power] = current

    result = None
    for idx, term in enumerate(terms, start=1):
        power = int(term.get("power"))
        if power not in allowed_powers:
            raise ValueError(f"term {idx} uses unsupported power {power}.")
        coefficient = _require_number(
            term.get("coefficient", 1),
            f"term {idx} coefficient",
            integer=integer,
        )
        contribution = powers[power] * coefficient
        result = contribution if result is None else result + contribution

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


def _scalar_vector(vector, value):
    return [value] * vector.size()
