from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RESULT_DIR = Path("agent_results").resolve()


def save_agent_result(result: dict[str, Any]) -> str:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    schema_name = _safe_filename(str(result.get("schema_name", "he_result")))
    path = RESULT_DIR / f"{timestamp}_{schema_name}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return str(path)


def list_agent_results(limit: int = 20) -> list[dict[str, Any]]:
    if not RESULT_DIR.exists():
        return []
    paths = sorted(RESULT_DIR.glob("*.json"), reverse=True)[:limit]
    return [
        {
            "path": str(path),
            "name": path.name,
            "size_kb": round(path.stat().st_size / 1024, 2),
        }
        for path in paths
    ]


def _safe_filename(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return name[:80] or "he_result"
