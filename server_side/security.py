from __future__ import annotations

import os
from pathlib import Path

import tenseal as ts
from fastapi import HTTPException

from server_side.logging_config import audit
from server_side.settings import settings


def resolve_in_shared(path_str: str, *, must_exist: bool) -> Path:
    """
    Resolve a client-supplied path and confine it to the shared volume.
    Prevents path traversal from the untrusted control plane.
    """
    p = Path(path_str).resolve()
    if not _within_shared(p):
        raise HTTPException(400, f"Path is outside the shared volume: {path_str}")
    if must_exist and not p.exists():
        raise HTTPException(400, f"File not found in shared volume: {path_str}")
    return p


def secret_key_present(context: ts.Context) -> bool:
    try:
        return bool(context.is_private())
    except Exception:
        return False


def audit_payload(name: str, raw: bytes) -> dict:
    n = settings.HEX_PREVIEW_BYTES
    preview = raw[:n].hex()
    meta = {
        "label": name,
        "payload_bytes": len(raw),
        "payload_kb": round(len(raw) / 1024, 2),
        "hex_preview": preview,
        "hex_preview_bytes": min(n, len(raw)),
    }
    audit.info(
        "BLIND-EVAL | %s | size=%.2f KB | first %d bytes (hex)=%s...",
        name, meta["payload_kb"], meta["hex_preview_bytes"], preview,
    )
    return meta


def _within_shared(p: Path) -> bool:
    try:
        return p == settings.SHARED_DIR or p.is_relative_to(settings.SHARED_DIR)
    except AttributeError:
        return str(p).startswith(str(settings.SHARED_DIR) + os.sep)
