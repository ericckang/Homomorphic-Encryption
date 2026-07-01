from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ComputeResult:
    label: str
    data: bytes
    depth: int | None = None
