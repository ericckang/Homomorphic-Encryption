from __future__ import annotations

import time
from pathlib import Path

import requests

from agent_side.crypto import decrypt_vector, encrypt_vector, make_context
from agent_side.input_data import collect_task_and_data
from agent_side.planner import plan_he_task
from agent_side.preflight import preflight_plan, preflight_task_prompt
from agent_side.reporting import print_report
from agent_side.transport import post_compute
from he_common.config import SERVER_URL
from he_common.operations import (
    apply_plaintext_pipeline,
    data_profile,
    estimate_depth,
    sanitize_plan,
)


def main() -> None:
    print("\n" + "#" * 72)
    print("Generalizable Homomorphic Encryption Agent")
    print("#" * 72)
    print("The LLM plans the operation schema. Raw data stays local and encrypted.")

    try:
        _, redacted_prompt, data = collect_task_and_data()
        profile = data_profile(data)
        preflight_task_prompt(redacted_prompt)

        print("\n[Agent] Asking planner for an HE operation schema without raw data...")
        raw_plan = plan_he_task(redacted_prompt, profile)
        plan = sanitize_plan(raw_plan, profile)

        depth = estimate_depth(plan["operations"])
        preflight = preflight_plan(plan, len(data))
        print(f"[Agent] Planned schema '{plan['schema_name']}' with {len(plan['operations'])} operation(s).")
        print(f"[Agent] Selected {plan['scheme']} with estimated multiplication depth {depth}.")
        print(f"[Agent] Estimated ciphertext payload: {preflight.estimated_payload_bytes / 1024:.2f} KB.")
        for warning in preflight.warnings:
            print(f"[Agent] Warning: {warning}")

        context, poly_mod_degree = make_context(plan["scheme"], len(data), depth)

        print("[Agent] Encrypting local data...")
        t0 = time.perf_counter()
        encrypted_vector = encrypt_vector(context, plan["scheme"], data)
        encryption_time = time.perf_counter() - t0

        print("[Agent] Sending ciphertext and operation schema to compute service...")
        server_response, _ = post_compute(context, encrypted_vector, plan)

        result_path = Path(server_response["result_path"])
        print("[Agent] Decrypting returned ciphertext locally...")
        t0 = time.perf_counter()
        decrypted = decrypt_vector(context, plan["scheme"], result_path.read_bytes())
        decryption_time = time.perf_counter() - t0

        expected = apply_plaintext_pipeline(data, plan["operations"])
        print_report(
            plan,
            data,
            decrypted,
            expected,
            server_response,
            {"encryption": encryption_time, "decryption": decryption_time},
            poly_mod_degree,
        )
    except requests.ConnectionError:
        print(f"\n[Agent] Could not reach server at {SERVER_URL}. Start it with: python server.py")
    except Exception as exc:
        print(f"\n[Agent] Error: {exc}")
