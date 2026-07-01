from __future__ import annotations

import time
import uuid
from typing import Any

import requests

from he_common.config import SERVER_URL, SHARED_DIR


def post_compute(context, encrypted_vector, plan: dict[str, Any]) -> tuple[dict[str, Any], float]:
    run_id = uuid.uuid4().hex[:10]
    context_path = SHARED_DIR / f"{run_id}_context.bin"
    payload_path = SHARED_DIR / f"{run_id}_payload.bin"
    result_path = SHARED_DIR / f"{run_id}_result.bin"

    context_path.write_bytes(context.serialize(save_secret_key=False))
    payload_path.write_bytes(encrypted_vector.serialize())

    request_body = {
        "computation_type": plan["computation_type"],
        "scheme": plan["scheme"],
        "context_path": str(context_path),
        "payload_path": str(payload_path),
        "result_path": str(result_path),
        "params": {
            "schema_name": plan["schema_name"],
            "operations": plan["operations"],
            "result_label": plan["result_label"],
        },
    }

    t0 = time.perf_counter()
    response = requests.post(SERVER_URL, json=request_body, timeout=300)
    roundtrip_time = time.perf_counter() - t0
    if response.status_code != 200:
        raise RuntimeError(f"Server returned HTTP {response.status_code}: {response.text}")

    data = response.json()
    data["_payload_size_kb"] = round(payload_path.stat().st_size / 1024, 2)
    data["_roundtrip_time_sec"] = roundtrip_time
    return data, roundtrip_time
