from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from he_common.config import SHARED_DIR


STATUS_PATH = SHARED_DIR / "demo_status.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict[str, Any]:
    return {
        "updated_at": _now(),
        "agent": {
            "stage": "idle",
            "message": "Waiting for agent run.",
            "updated_at": _now(),
        },
        "server": {
            "status": "idle",
            "message": "Waiting for compute request.",
            "last_request": None,
            "updated_at": _now(),
        },
        "result": None,
        "history": [],
    }


def read_demo_state() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        state = _default_state()
        STATUS_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def write_demo_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _now()
    STATUS_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_history(source: str, stage: str, message: str, extra: dict[str, Any] | None = None) -> None:
    state = read_demo_state()
    entry = {
        "time": _now(),
        "source": source,
        "stage": stage,
        "message": message,
        "extra": extra or {},
    }
    history = state.setdefault("history", [])
    history.append(entry)
    state["history"] = history[-25:]
    write_demo_state(state)


def update_agent(stage: str, message: str, extra: dict[str, Any] | None = None) -> None:
    state = read_demo_state()
    current = state.get("agent", {})
    merged_extra = dict(current.get("extra", {}))
    if extra:
        merged_extra.update(extra)
    state["agent"] = {
        "stage": stage,
        "message": message,
        "updated_at": _now(),
        "extra": merged_extra,
    }
    write_demo_state(state)
    append_history("agent", stage, message, merged_extra)


def update_server(
    status: str,
    message: str,
    last_request: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    state = read_demo_state()
    current = state.get("server", {})
    state["server"] = {
        "status": status,
        "message": message,
        "last_request": last_request if last_request is not None else current.get("last_request"),
        "updated_at": _now(),
        "extra": extra or {},
    }
    write_demo_state(state)
    append_history("server", status, message, extra)


def update_result(result: dict[str, Any] | None) -> None:
    state = read_demo_state()
    state["result"] = result
    write_demo_state(state)
    if result is not None:
        append_history("agent", "result", "Result summary updated.", {"schema_name": result.get("schema_name")})


def reset_demo_state() -> None:
    write_demo_state(_default_state())
