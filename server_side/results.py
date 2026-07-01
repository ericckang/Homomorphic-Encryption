from __future__ import annotations

from pathlib import Path

from server_side.security import resolve_in_shared
from server_side.types import ComputeResult


def write_results(result_path: str, results: list[ComputeResult]) -> tuple[str, list[dict]]:
    written: list[dict] = []

    if len(results) == 1:
        out = resolve_in_shared(result_path, must_exist=False)
        out.write_bytes(results[0].data)
        written.append({"label": results[0].label, "depth": results[0].depth, "path": str(out)})
        return str(out), written

    base = result_path[:-4] if result_path.endswith(".bin") else result_path
    base_path = resolve_in_shared(base, must_exist=False)
    for idx, result in enumerate(results, start=1):
        depth = result.depth if result.depth is not None else idx
        out = Path(f"{base_path}_d{depth}.bin")
        out.write_bytes(result.data)
        written.append({"label": result.label, "depth": depth, "path": str(out)})
    return str(base_path), written
