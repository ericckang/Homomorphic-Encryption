from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from he_common.operations import estimate_depth


MAX_VECTOR_LENGTH = 200_000
MAX_OPERATION_COUNT = 12
MAX_CKKS_DEPTH = 4
MAX_BFV_DEPTH = 2
MAX_ESTIMATED_PAYLOAD_BYTES = 1_900_000_000

UNSUPPORTED_TASK_HINTS = {
    "median": "Median requires sorting/comparison, which is not supported by this HE pipeline.",
    "sort": "Sorting requires comparisons and branching, which are not supported by this HE pipeline.",
    "minimum": "Min/max require comparisons, which are not supported by this HE pipeline.",
    "maximum": "Min/max require comparisons, which are not supported by this HE pipeline.",
    "threshold": "Boolean thresholding is not supported. Use a difference score such as x - threshold.",
    "greater than": "Boolean comparison is not supported. Use a difference score such as x - threshold.",
    "less than": "Boolean comparison is not supported. Use a difference score such as x - threshold.",
    "if ": "Branching is not supported by this HE pipeline.",
    "classify": "General classification models are not supported. Use a bounded polynomial risk score.",
}


@dataclass(frozen=True)
class PreflightResult:
    warnings: list[str]
    estimated_payload_bytes: int


def preflight_input_vector(data: list[float]) -> None:
    if not data:
        raise ValueError("Input data cannot be empty.")
    if len(data) > MAX_VECTOR_LENGTH:
        raise ValueError(
            f"Input vector has {len(data):,} values, which exceeds the agent preflight "
            f"limit of {MAX_VECTOR_LENGTH:,}. Use a smaller batch or aggregate locally first."
        )
    conservative_estimate = estimate_payload_bytes("CKKS", len(data))
    if conservative_estimate > MAX_ESTIMATED_PAYLOAD_BYTES:
        raise ValueError(
            f"Conservative ciphertext estimate is {conservative_estimate / 1024 / 1024:.1f} MB, "
            "which is too close to the serialization limit. Use a smaller batch."
        )


def preflight_task_prompt(redacted_prompt: str) -> None:
    prompt = redacted_prompt.lower()
    for hint, explanation in UNSUPPORTED_TASK_HINTS.items():
        if hint in prompt:
            raise ValueError(f"Unsupported HE task requested: {explanation}")


def preflight_plan(plan: dict[str, Any], vector_length: int) -> PreflightResult:
    scheme = plan["scheme"]
    operations = plan["operations"]
    depth = estimate_depth(operations)
    warnings: list[str] = []

    if vector_length <= 0:
        raise ValueError("Input vector cannot be empty.")
    if vector_length > MAX_VECTOR_LENGTH:
        raise ValueError(
            f"Input vector has {vector_length:,} values, which exceeds the demo limit "
            f"of {MAX_VECTOR_LENGTH:,}. Use a smaller batch or aggregate locally first."
        )
    if len(operations) > MAX_OPERATION_COUNT:
        raise ValueError(
            f"Operation plan has {len(operations)} steps, which exceeds the limit "
            f"of {MAX_OPERATION_COUNT}."
        )
    if scheme == "BFV" and any(operation["op"] == "mean_reduce" for operation in operations):
        raise ValueError("BFV mean_reduce is not supported in this demo. Use CKKS or divide after decryption.")

    if scheme == "CKKS" and depth > MAX_CKKS_DEPTH:
        raise ValueError(
            f"CKKS multiplication depth {depth} is too high for this demo. "
            f"Use a shallower polynomial with depth <= {MAX_CKKS_DEPTH}."
        )
    if scheme == "BFV" and depth > MAX_BFV_DEPTH:
        raise ValueError(
            f"BFV multiplication depth {depth} is too high for this demo. "
            f"Prefer exact add/subtract/multiply-by-scalar operations."
        )

    estimated_payload_bytes = estimate_payload_bytes(scheme, vector_length)
    if estimated_payload_bytes > MAX_ESTIMATED_PAYLOAD_BYTES:
        raise ValueError(
            f"Estimated ciphertext payload is {estimated_payload_bytes / 1024 / 1024:.1f} MB, "
            "which is too close to the serialization limit. Use a smaller batch."
        )

    if scheme == "CKKS" and depth > 0:
        warnings.append(
            "CKKS uses approximate arithmetic; multiplication depth will increase numerical error."
        )
    if vector_length > 50_000:
        warnings.append(
            "Large vectors can produce large ciphertext payloads and slow encryption/evaluation."
        )
    if any(operation["op"] in {"sum_reduce", "mean_reduce", "dot_product_public"} for operation in operations):
        warnings.append(
            "Reduction operations require slot rotations and Galois keys, which increase context size and eval cost."
        )

    return PreflightResult(warnings=warnings, estimated_payload_bytes=estimated_payload_bytes)


def estimate_payload_bytes(scheme: str, vector_length: int) -> int:
    """
    Conservative rough estimate based on measured demo payload growth.
    The server still enforces the exact serialized size.
    """
    bytes_per_value = 260 if scheme == "BFV" else 1_600
    base_overhead = 256_000 if scheme == "BFV" else 1_500_000
    return base_overhead + vector_length * bytes_per_value


def agent_limits() -> dict[str, Any]:
    return {
        "max_vector_length": MAX_VECTOR_LENGTH,
        "max_operation_count": MAX_OPERATION_COUNT,
        "max_ckks_depth": MAX_CKKS_DEPTH,
        "max_bfv_depth": MAX_BFV_DEPTH,
        "max_estimated_payload_bytes": MAX_ESTIMATED_PAYLOAD_BYTES,
        "supported_operations": [
            "add_scalar",
            "sub_scalar",
            "mul_scalar",
            "square",
            "polynomial",
            "sum_reduce",
            "mean_reduce",
            "dot_product_public",
        ],
        "unsupported_task_hints": UNSUPPORTED_TASK_HINTS,
    }
