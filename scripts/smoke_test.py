from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_side.crypto import decrypt_vector, encrypt_vector, make_context
from agent_side.preflight import preflight_plan
from agent_side.transport import post_compute
from he_common.operations import (
    apply_plaintext_pipeline,
    data_profile,
    estimate_depth,
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
                        {"power": 8, "coefficient": 1.0},
                        {"power": 4, "coefficient": 1.0},
                        {"power": 2, "coefficient": 1.0},
                    ],
                    "constant": 0.0,
                }
            ],
            "result_label": "risk score",
            "plaintext_formula": "x^8 + x^4 + x^2",
        },
        data_profile(data),
    )

    decrypted, expected = _run_plan(data, plan)
    max_error = max(abs(a - b) for a, b in zip(expected, decrypted))

    if max_error > 1e-2:
        raise AssertionError(f"CKKS error too large: {max_error}")

    print(f"CKKS smoke test passed: max_error={max_error:.8f}")


def _run_plan(data: list[float], plan: dict) -> tuple[list[float], list[float]]:
    preflight_plan(plan, len(data))
    context, _ = make_context(plan["scheme"], len(data), estimate_depth(plan["operations"]))
    encrypted = encrypt_vector(context, plan["scheme"], data)
    response, _ = post_compute(context, encrypted, plan)
    result_path = Path(response["result_path"])
    decrypted = decrypt_vector(context, plan["scheme"], result_path.read_bytes())
    expected = apply_plaintext_pipeline(data, plan["operations"])
    return decrypted, expected


def main() -> None:
    print("Running end-to-end HE smoke tests against http://localhost:8080 ...")
    run_bfv_test()
    run_ckks_test()
    print("All smoke tests passed.")


if __name__ == "__main__":
    main()
