from __future__ import annotations

from typing import Any


def print_report(
    plan: dict[str, Any],
    original_data: list[float],
    decrypted: list[float],
    expected: list[float],
    server_response: dict[str, Any],
    timings: dict[str, float],
    poly_mod_degree: int,
) -> None:
    print("\n" + "=" * 72)
    print("Generalized HE Agent Result")
    print("=" * 72)
    print(f"Schema             : {plan['schema_name']}")
    print(f"Scheme             : {plan['scheme']} ({plan['computation_type']})")
    print(f"Formula            : {plan['plaintext_formula']}")
    if plan["notes"]:
        print(f"Planner notes      : {plan['notes']}")
    print(f"Vector length      : {len(original_data)}")
    print(f"Poly modulus degree: {poly_mod_degree}")
    print(f"Ciphertext size    : {server_response['_payload_size_kb']:.2f} KB")
    print(f"Encryption time    : {timings['encryption']:.4f} sec")
    print(f"Server eval time   : {server_response['evaluation_time_sec']:.4f} sec")
    print(f"Round-trip time    : {server_response['_roundtrip_time_sec']:.4f} sec")
    print(f"Decryption time    : {timings['decryption']:.4f} sec")
    print(f"Server audit       : {server_response['audit']['payload_kb']} KB ciphertext")

    sample_count = min(5, len(decrypted))
    print("\nResult sample")
    for idx in range(sample_count):
        print(
            f"  [{idx}] input={original_data[idx]:.6g} "
            f"expected={expected[idx]:.6g} decrypted={decrypted[idx]:.6g}"
        )

    if plan["scheme"] == "CKKS":
        errors = [abs(a - b) for a, b in zip(expected, decrypted)]
        print(f"\nCKKS max abs error : {max(errors):.8f}")
    else:
        mismatches = sum(int(round(a)) != int(round(b)) for a, b in zip(expected, decrypted))
        print(f"\nBFV exact mismatches: {mismatches}")
