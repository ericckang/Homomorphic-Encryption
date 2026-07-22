from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_side.crypto import decrypt_vector, encrypt_scalar_operand, encrypt_vector, make_context
from agent_side.transport import post_compute
from he_common.operations import apply_plaintext_pipeline, estimate_depth, normalize_decrypted_result

OUTPUT_DIR = Path("benchmark_results")
OUTPUT_CSV = OUTPUT_DIR / "encrypted_constants_benchmark.csv"
OUTPUT_MD = OUTPUT_DIR / "encrypted_constants_benchmark.md"

BFV_VECTOR_SIZES = [128, 1024, 4096, 8192, 16384]
REPEATS = 5


def estimated_slot_capacity(poly_modulus_degree: int) -> int:
    return poly_modulus_degree


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    benchmark_cases = [
        {
            "case_name": "bfv_add",
            "scheme": "BFV",
            "data": lambda n: [((i % 97) + 1) for i in range(n)],
            "baseline_op": {"op": "add_scalar", "value": 5},
            "encrypted_op": {"op": "add_encrypted_scalar", "value": 5, "operand_key": "enc_const_0"},
            "formula_plain": "x + 5",
            "formula_encrypted": "x + ⟦5⟧",
        },
        {
            "case_name": "bfv_sub",
            "scheme": "BFV",
            "data": lambda n: [((i % 97) + 50) for i in range(n)],
            "baseline_op": {"op": "sub_scalar", "value": 5},
            "encrypted_op": {"op": "sub_encrypted_scalar", "value": 5, "operand_key": "enc_const_0"},
            "formula_plain": "x - 5",
            "formula_encrypted": "x - ⟦5⟧",
        },
        {
            "case_name": "bfv_mul",
            "scheme": "BFV",
            "data": lambda n: [((i % 31) + 1) for i in range(n)],
            "baseline_op": {"op": "mul_scalar", "value": 5},
            "encrypted_op": {"op": "mul_encrypted_scalar", "value": 5, "operand_key": "enc_const_0"},
            "formula_plain": "x * 5",
            "formula_encrypted": "x * ⟦5⟧",
        },
    ]

    for case in benchmark_cases:
        for vector_length in BFV_VECTOR_SIZES:
            data = case["data"](vector_length)
            for use_encrypted_constants in (False, True):
                operation = case["encrypted_op"] if use_encrypted_constants else case["baseline_op"]
                formula = case["formula_encrypted"] if use_encrypted_constants else case["formula_plain"]
                run_rows = []
                for repeat in range(1, REPEATS + 1):
                    run_rows.append(
                        run_single_benchmark(
                            case_name=case["case_name"],
                            scheme=case["scheme"],
                            vector_length=vector_length,
                            data=data,
                            operation=operation,
                            formula=formula,
                            use_encrypted_constants=use_encrypted_constants,
                            repeat=repeat,
                        )
                    )
                rows.extend(run_rows)

    write_csv(rows)
    write_markdown(rows)
    print(f"Saved CSV benchmark results to {OUTPUT_CSV}")
    print(f"Saved Markdown benchmark table to {OUTPUT_MD}")
    print(f"BFV vector sizes benchmarked: {BFV_VECTOR_SIZES}")


def run_single_benchmark(
    *,
    case_name: str,
    scheme: str,
    vector_length: int,
    data: list[float],
    operation: dict[str, Any],
    formula: str,
    use_encrypted_constants: bool,
    repeat: int,
) -> dict[str, Any]:
    plan = {
        "schema_name": case_name,
        "scheme": scheme,
        "computation_type": "general_bfv" if scheme == "BFV" else "general_ckks",
        "operations": [dict(operation)],
        "result_shape": "vector",
        "result_label": "result",
        "plaintext_formula": formula,
        "server_display_formula": formula,
        "notes": "Encrypted constant benchmark" if use_encrypted_constants else "Plain constant benchmark",
    }

    depth = estimate_depth(plan["operations"])
    context, poly_mod_degree = make_context(scheme, vector_length, depth)

    import time

    slot_capacity = estimated_slot_capacity(poly_mod_degree)
    likely_multi_ciphertext = vector_length > slot_capacity

    t0 = time.perf_counter()
    encrypted_vector = encrypt_vector(context, scheme, data)
    encrypted_operands: dict[str, Any] = {}
    if use_encrypted_constants:
        encrypted_operands[operation["operand_key"]] = encrypt_scalar_operand(
            context,
            scheme,
            operation["value"],
            vector_length,
        )
    encryption_time = time.perf_counter() - t0
    total_payload_kb = round(
        (
            len(encrypted_vector.serialize())
            + sum(len(operand.serialize()) for operand in encrypted_operands.values())
        ) / 1024,
        2,
    )

    server_response, _ = post_compute(context, encrypted_vector, plan, encrypted_operands)

    t0 = time.perf_counter()
    decrypted = normalize_decrypted_result(
        plan,
        decrypt_vector(context, scheme, Path(server_response["result_path"]).read_bytes()),
    )
    decryption_time = time.perf_counter() - t0

    expected = apply_plaintext_pipeline(data, plan["operations"])
    row = {
        "case_name": case_name,
        "operation": operation["op"],
        "scheme": scheme,
        "vector_length": vector_length,
        "encrypted_constants": use_encrypted_constants,
        "formula": formula,
        "repeat": repeat,
        "poly_modulus_degree": poly_mod_degree,
        "estimated_slot_capacity": slot_capacity,
        "likely_multi_ciphertext": likely_multi_ciphertext,
        "ciphertext_size_kb": server_response["_payload_size_kb"],
        "total_payload_kb": total_payload_kb,
        "encryption_time_sec": encryption_time,
        "evaluation_time_sec": server_response["evaluation_time_sec"],
        "roundtrip_time_sec": server_response["_roundtrip_time_sec"],
        "decryption_time_sec": decryption_time,
    }

    mismatches = sum(int(round(a)) != int(round(b)) for a, b in zip(expected, decrypted))
    row["accuracy_metric"] = "exact_mismatches"
    row["accuracy_value"] = mismatches

    return row


def write_csv(rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_name",
        "operation",
        "scheme",
        "vector_length",
        "encrypted_constants",
        "formula",
        "repeat",
        "poly_modulus_degree",
        "estimated_slot_capacity",
        "likely_multi_ciphertext",
        "ciphertext_size_kb",
        "total_payload_kb",
        "encryption_time_sec",
        "evaluation_time_sec",
        "roundtrip_time_sec",
        "decryption_time_sec",
        "accuracy_metric",
        "accuracy_value",
    ]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str, int, bool], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            row["case_name"],
            row["scheme"],
            row["vector_length"],
            row["encrypted_constants"],
        )
        grouped.setdefault(key, []).append(row)

    ordered_keys = sorted(grouped.keys(), key=lambda item: (item[0], item[2], item[3]))
    lines = [
        "# Encrypted Constants Benchmark Summary",
        "",
        f"Runs per case: {REPEATS}",
        "",
        "| Case | Scheme | N | Mode | Poly Degree | Slot Capacity | Multi-CT? | Avg Encrypt (s) | Avg Eval (s) | Avg Roundtrip (s) | Avg Decrypt (s) | Avg Payload (KB) | Accuracy |",
        "|---|---|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]

    for key in ordered_keys:
        case_name, scheme, vector_length, encrypted_constants = key
        group = grouped[key]
        accuracy_metric = group[0]["accuracy_metric"]
        accuracy_values = [float(item["accuracy_value"]) for item in group]
        accuracy_cell = f"{statistics.mean(accuracy_values):.2f} mismatches"
        lines.append(
            "| {case} | {scheme} | {n} | {mode} | {degree} | {capacity} | {multi} | {enc:.4f} | {eval:.4f} | {rt:.4f} | {dec:.4f} | {payload:.2f} | {accuracy} |".format(
                case=case_name,
                scheme=scheme,
                n=vector_length,
                mode="encrypted constants" if encrypted_constants else "plaintext constants",
                degree=group[0]["poly_modulus_degree"],
                capacity=group[0]["estimated_slot_capacity"],
                multi="yes" if group[0]["likely_multi_ciphertext"] else "no",
                enc=statistics.mean(float(item["encryption_time_sec"]) for item in group),
                eval=statistics.mean(float(item["evaluation_time_sec"]) for item in group),
                rt=statistics.mean(float(item["roundtrip_time_sec"]) for item in group),
                dec=statistics.mean(float(item["decryption_time_sec"]) for item in group),
                payload=statistics.mean(float(item["total_payload_kb"]) for item in group),
                accuracy=accuracy_cell,
            )
        )

    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
