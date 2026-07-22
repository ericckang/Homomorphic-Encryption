from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_side.crypto import decrypt_vector, encrypt_scalar_operand, encrypt_vector, make_context
from agent_side.planner import plan_he_task
from agent_side.preflight import preflight_input_vector, preflight_plan, preflight_task_prompt
from agent_side.reporting import print_report
from agent_side.result_store import save_agent_result
from agent_side.transport import post_compute
from he_common.demo_state import reset_demo_state, update_agent, update_result
from he_common.operations import (
    apply_plaintext_pipeline,
    build_server_display_formula,
    data_profile,
    estimate_depth,
    normalize_decrypted_result,
    sanitize_plan,
)


def run_agent_task(
    redacted_prompt: str,
    data: list[float],
    *,
    reset_state: bool = True,
    encrypt_formula_constants: bool = False,
) -> dict[str, Any]:
    if reset_state:
        reset_demo_state()
    update_agent("collecting_input", "Task received from user input.", {"vector_length": len(data)})

    preflight_input_vector(data)
    profile = data_profile(data)
    preflight_task_prompt(redacted_prompt)

    update_agent(
        "planning",
        "Asking planner for an HE operation schema without raw data.",
        {"vector_length": len(data), "numeric_kind": profile.get("numeric_kind")},
    )
    raw_plan = plan_he_task(redacted_prompt, profile)
    plan = sanitize_plan(raw_plan, profile)
    if encrypt_formula_constants:
        plan = _encrypt_plan_constants(plan)

    depth = estimate_depth(plan["operations"])
    preflight = preflight_plan(plan, len(data))
    update_agent(
        "planned",
        f"Planned schema '{plan['schema_name']}' with {len(plan['operations'])} operation(s).",
        {
            "schema_name": plan["schema_name"],
            "scheme": plan["scheme"],
            "depth": depth,
            "estimated_payload_kb": round(preflight.estimated_payload_bytes / 1024, 2),
            "warnings": preflight.warnings,
            "encrypt_formula_constants": encrypt_formula_constants,
        },
    )

    context, poly_mod_degree = make_context(plan["scheme"], len(data), depth)

    update_agent("encrypting", "Encrypting local data.", {"scheme": plan["scheme"]})
    t0 = time.perf_counter()
    encrypted_vector = encrypt_vector(context, plan["scheme"], data)
    encrypted_operands = _build_encrypted_operands(context, plan, len(data))
    encryption_time = time.perf_counter() - t0

    update_agent("sending", "Sending ciphertext and operation schema to compute service.")
    server_response, _ = post_compute(context, encrypted_vector, plan, encrypted_operands)

    result_path = Path(server_response["result_path"])
    update_agent("decrypting", "Decrypting returned ciphertext locally.")
    t0 = time.perf_counter()
    decrypted = normalize_decrypted_result(
        plan,
        decrypt_vector(context, plan["scheme"], result_path.read_bytes()),
    )
    decryption_time = time.perf_counter() - t0

    expected = apply_plaintext_pipeline(data, plan["operations"])
    update_agent("reporting", "Preparing final result summary for the dashboard.")
    result_summary = print_report(
        plan,
        data,
        decrypted,
        expected,
        server_response,
        {"encryption": encryption_time, "decryption": decryption_time},
        poly_mod_degree,
        encrypt_formula_constants,
    )
    saved_result_path = save_agent_result(result_summary)
    result_summary["saved_result_path"] = saved_result_path
    update_result(result_summary)
    update_agent(
        "done",
        "Agent run completed successfully.",
        {"schema_name": plan["schema_name"], "saved_result_path": saved_result_path},
    )

    return {
        "plan": plan,
        "decrypted": decrypted,
        "expected": expected,
        "server_response": server_response,
        "timings": {"encryption": encryption_time, "decryption": decryption_time},
        "poly_mod_degree": poly_mod_degree,
        "result_summary": result_summary,
    }


def _encrypt_plan_constants(plan: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(plan)
    transformed_ops: list[dict[str, Any]] = []
    operand_index = 0
    for operation in plan["operations"]:
        op = operation["op"]
        if op in {"add_scalar", "sub_scalar", "mul_scalar"}:
            transformed_op = dict(operation)
            transformed_op["op"] = op.replace("_scalar", "_encrypted_scalar")
            transformed_op["operand_key"] = f"enc_const_{operand_index}"
            transformed_ops.append(transformed_op)
            operand_index += 1
        else:
            transformed_ops.append(dict(operation))
    transformed["operations"] = transformed_ops
    transformed["notes"] = (
        f"{plan['notes']} Constants in eligible scalar operations were encrypted before server evaluation."
    ).strip()
    transformed["server_display_formula"] = build_server_display_formula(transformed)
    return transformed


def _build_encrypted_operands(context, plan: dict[str, Any], vector_size: int) -> dict[str, Any]:
    operands: dict[str, Any] = {}
    for operation in plan["operations"]:
        operand_key = operation.get("operand_key")
        if not operand_key:
            continue
        operands[operand_key] = encrypt_scalar_operand(context, plan["scheme"], operation["value"], vector_size)
    return operands
