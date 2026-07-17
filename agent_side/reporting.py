from __future__ import annotations

from typing import Any

from he_common.demo_state import update_result


def print_report(
    plan: dict[str, Any],
    original_data: list[float],
    decrypted: list[float],
    expected: list[float],
    server_response: dict[str, Any],
    timings: dict[str, float],
    poly_mod_degree: int,
) -> dict[str, Any]:
    if plan.get("result_shape") == "scalar":
        samples = [
            {
                "index": "scalar",
                "input": f"{len(original_data)} encrypted values",
                "expected": expected[0],
                "decrypted": decrypted[0],
            }
        ]
    else:
        sample_count = min(5, len(decrypted))
        samples = [
            {
                "index": idx,
                "input": original_data[idx],
                "expected": expected[idx],
                "decrypted": decrypted[idx],
            }
            for idx in range(sample_count)
        ]

    result_summary = {
        "schema_name": plan["schema_name"],
        "scheme": plan["scheme"],
        "computation_type": plan["computation_type"],
        "result_shape": plan.get("result_shape", "vector"),
        "formula": plan["plaintext_formula"],
        "notes": plan["notes"],
        "vector_length": len(original_data),
        "poly_modulus_degree": poly_mod_degree,
        "ciphertext_size_kb": server_response["_payload_size_kb"],
        "encryption_time_sec": timings["encryption"],
        "evaluation_time_sec": server_response["evaluation_time_sec"],
        "roundtrip_time_sec": server_response["_roundtrip_time_sec"],
        "decryption_time_sec": timings["decryption"],
        "server_audit": server_response["audit"],
        "samples": samples,
        "expected_output": expected,
        "decrypted_output": decrypted,
    }
    print("\n" + "=" * 72)
    print("Generalized HE Agent Result")
    print("=" * 72)
    print(f"Schema             : {plan['schema_name']}")
    print(f"Scheme             : {plan['scheme']} ({plan['computation_type']})")
    print(f"Formula            : {plan['plaintext_formula']}")
    if plan["notes"]:
        print(f"Planner notes      : {plan['notes']}")
    print(f"Vector length      : {len(original_data)}")
    print(f"Result shape       : {plan.get('result_shape', 'vector')}")
    print(f"Poly modulus degree: {poly_mod_degree}")
    print(f"Ciphertext size    : {server_response['_payload_size_kb']:.2f} KB")
    print(f"Encryption time    : {timings['encryption']:.4f} sec")
    print(f"Server eval time   : {server_response['evaluation_time_sec']:.4f} sec")
    print(f"Round-trip time    : {server_response['_roundtrip_time_sec']:.4f} sec")
    print(f"Decryption time    : {timings['decryption']:.4f} sec")
    print(f"Server audit       : {server_response['audit']['payload_kb']} KB ciphertext")

    print("\nResult sample")
    for sample in samples:
        print(
            f"  [{sample['index']}] input={_format_value(sample['input'])} "
            f"expected={_format_value(sample['expected'])} decrypted={_format_value(sample['decrypted'])}"
        )

    if plan["scheme"] == "CKKS":
        errors = [abs(a - b) for a, b in zip(expected, decrypted)]
        max_error = max(errors)
        result_summary["max_abs_error"] = max_error
        print(f"\nCKKS max abs error : {max_error:.8f}")
    else:
        mismatches = sum(int(round(a)) != int(round(b)) for a, b in zip(expected, decrypted))
        result_summary["exact_mismatches"] = mismatches
        print(f"\nBFV exact mismatches: {mismatches}")

    update_result(result_summary)
    return result_summary


def _format_value(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.6g}"
    return str(value)
