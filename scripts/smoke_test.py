from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_side.crypto import decrypt_vector, encrypt_scalar_operand, encrypt_vector, make_context
from agent_side.input_data import load_csv_table
from agent_side.preflight import preflight_plan
from agent_side.transport import post_compute
from he_common.config import SERVER_URL
from he_common.operations import (
    apply_plaintext_pipeline,
    data_profile,
    estimate_depth,
    normalize_decrypted_result,
    sanitize_plan,
)


def run_bfv_test() -> None:
    data = [85000.0, 90000.0, 95000.0]
    plan = sanitize_plan(
        {
            "schema_name": "salary_difference",
            "scheme": "BFV",
            "operations": [
                {"op": "sub_scalar", "value": 90000},
                {"op": "mul_scalar", "value": 2},
            ],
            "result_label": "salary difference",
            "plaintext_formula": "(x - 90000) * 2",
        },
        data_profile(data),
    )

    decrypted, expected = _run_plan(data, plan)
    rounded = [int(round(value)) for value in decrypted]
    expected_int = [int(round(value)) for value in expected]

    if rounded != expected_int:
        raise AssertionError(f"BFV mismatch: expected {expected_int}, got {rounded}")

    print(f"BFV smoke test passed: {rounded}")


def run_ckks_test() -> None:
    data = [1.05, 1.10, 1.15]
    plan = sanitize_plan(
        {
            "schema_name": "risk_polynomial",
            "scheme": "CKKS",
            "operations": [
                {
                    "op": "polynomial",
                    "terms": [
                        {"power": 5, "coefficient": 1.0},
                        {"power": 3, "coefficient": 1.0},
                        {"power": 2, "coefficient": 1.0},
                    ],
                    "constant": 0.0,
                }
            ],
            "result_label": "risk score",
            "plaintext_formula": "x^5 + x^3 + x^2",
        },
        data_profile(data),
    )

    decrypted, expected = _run_plan(data, plan)
    max_error = max(abs(a - b) for a, b in zip(expected, decrypted))

    if max_error > 1e-2:
        raise AssertionError(f"CKKS error too large: {max_error}")

    print(f"CKKS smoke test passed: max_error={max_error:.8f}")


def run_bfv_sum_test() -> None:
    data = [100.0, 90000.0, 95000.0]
    plan = sanitize_plan(
        {
            "schema_name": "salary_sum",
            "scheme": "BFV",
            "operations": [{"op": "sum_reduce"}],
            "result_label": "salary sum",
            "plaintext_formula": "sum(x)",
        },
        data_profile(data),
    )

    decrypted, expected = _run_plan(data, plan)
    if int(round(decrypted[0])) != int(round(expected[0])):
        raise AssertionError(f"BFV sum mismatch: expected {expected[0]}, got {decrypted[0]}")

    print(f"BFV reduction smoke test passed: total={int(round(decrypted[0]))}")


def run_ckks_mean_test() -> None:
    data = [1.05, 1.10, 1.15]
    plan = sanitize_plan(
        {
            "schema_name": "feature_mean",
            "scheme": "CKKS",
            "operations": [{"op": "mean_reduce"}],
            "result_label": "feature mean",
            "plaintext_formula": "mean(x)",
        },
        data_profile(data),
    )

    decrypted, expected = _run_plan(data, plan)
    error = abs(expected[0] - decrypted[0])
    if error > 1e-2:
        raise AssertionError(f"CKKS mean error too large: {error}")

    print(f"CKKS reduction smoke test passed: mean_error={error:.8f}")


def run_ckks_dot_test() -> None:
    data = [1.0, 2.0, 3.0]
    plan = sanitize_plan(
        {
            "schema_name": "weighted_risk_score",
            "scheme": "CKKS",
            "operations": [{"op": "dot_product_public", "weights": [0.2, 0.3, 0.5]}],
            "result_label": "weighted risk score",
            "plaintext_formula": "0.2*x1 + 0.3*x2 + 0.5*x3",
        },
        data_profile(data),
    )

    decrypted, expected = _run_plan(data, plan)
    error = abs(expected[0] - decrypted[0])
    if error > 1e-2:
        raise AssertionError(f"CKKS dot-product error too large: {error}")

    print(f"CKKS dot-product smoke test passed: error={error:.8f}")


def run_ckks_encrypted_polynomial_constants_test() -> None:
    data = [1.05, 1.10, 1.15]
    plan = sanitize_plan(
        {
            "schema_name": "encrypted_poly_constants",
            "scheme": "CKKS",
            "operations": [
                {
                    "op": "polynomial",
                    "terms": [
                        {"power": 2, "coefficient": 0.5, "operand_key": "enc_poly_coef_0"},
                        {"power": 1, "coefficient": 1.2, "operand_key": "enc_poly_coef_1"},
                    ],
                    "constant": 3.0,
                    "constant_operand_key": "enc_poly_const_0",
                }
            ],
            "result_label": "encrypted polynomial constants",
            "plaintext_formula": "0.5*x^2 + 1.2*x + 3",
        },
        data_profile(data),
    )

    decrypted, expected = _run_plan(data, plan, encrypt_operands=True)
    max_error = max(abs(a - b) for a, b in zip(expected, decrypted))
    if max_error > 1e-2:
        raise AssertionError(f"Encrypted polynomial constant error too large: {max_error}")

    print(f"CKKS encrypted polynomial constants smoke test passed: max_error={max_error:.8f}")


def run_csv_column_mean_test() -> None:
    csv_info = load_csv_table(str(PROJECT_ROOT / "data" / "sample_employee_metrics.csv"))
    data = csv_info["table_columns"]["salary"]
    numeric_data = [float(value) for value in data]
    profile = data_profile(
        numeric_data,
        {
            "input_kind": "table",
            "row_count": csv_info["row_count"],
            "columns": csv_info["columns"],
            "selected_column": csv_info["selected_column"],
        },
    )
    plan = sanitize_plan(
        {
            "schema_name": "salary_mean_from_csv",
            "target_column": "salary",
            "scheme": "CKKS",
            "operations": [{"op": "mean_reduce"}],
            "result_label": "salary mean",
            "plaintext_formula": "mean(salary)",
        },
        profile,
    )

    if plan.get("target_column") != "salary":
        raise AssertionError(f"CSV target_column mismatch: {plan.get('target_column')}")

    decrypted, expected = _run_plan(numeric_data, plan)
    error = abs(expected[0] - decrypted[0])
    if error > 1e-2:
        raise AssertionError(f"CSV salary mean error too large: {error}")

    print(f"CSV column smoke test passed: selected=salary mean_error={error:.8f}")


def _run_plan(data: list[float], plan: dict, *, encrypt_operands: bool = False) -> tuple[list[float], list[float]]:
    preflight_plan(plan, len(data))
    context, _ = make_context(plan["scheme"], len(data), estimate_depth(plan["operations"]))
    encrypted = encrypt_vector(context, plan["scheme"], data)
    encrypted_operands = _build_test_encrypted_operands(context, plan, len(data)) if encrypt_operands else None
    response, _ = post_compute(context, encrypted, plan, encrypted_operands)
    result_path = Path(response["result_path"])
    decrypted = normalize_decrypted_result(
        plan,
        decrypt_vector(context, plan["scheme"], result_path.read_bytes()),
    )
    expected = apply_plaintext_pipeline(data, plan["operations"])
    return decrypted, expected


def _build_test_encrypted_operands(context, plan: dict, vector_size: int) -> dict[str, Any]:
    operands: dict[str, Any] = {}
    for operation in plan["operations"]:
        operand_key = operation.get("operand_key")
        if operand_key:
            operands[operand_key] = encrypt_scalar_operand(context, plan["scheme"], operation["value"], vector_size)
        if operation.get("op") == "polynomial":
            for term in operation.get("terms", []):
                term_operand_key = term.get("operand_key")
                if term_operand_key:
                    operands[term_operand_key] = encrypt_scalar_operand(
                        context,
                        plan["scheme"],
                        term["coefficient"],
                        vector_size,
                    )
            constant_operand_key = operation.get("constant_operand_key")
            if constant_operand_key:
                operands[constant_operand_key] = encrypt_scalar_operand(
                    context,
                    plan["scheme"],
                    operation.get("constant", 0),
                    vector_size,
                )
    return operands


def main() -> None:
    print(f"Running end-to-end HE smoke tests against {SERVER_URL} ...")
    run_bfv_test()
    run_bfv_sum_test()
    run_ckks_test()
    run_ckks_mean_test()
    run_ckks_dot_test()
    run_ckks_encrypted_polynomial_constants_test()
    run_csv_column_mean_test()
    print("All smoke tests passed.")


if __name__ == "__main__":
    main()
