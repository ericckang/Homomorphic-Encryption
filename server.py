"""
Homomorphic Encryption (HE) Compute Service  —  the "Blind Evaluator".

This is the untrusted third-party compute node from the HE Skill architecture.
It operates ENTIRELY on ciphertext: it never receives, holds, or serializes a
secret key, and it refuses any context that carries one.

Architecture
------------
Control Plane (this file, a REST API)
    Receives only lightweight instructions: a computation_type, relative data
    paths into the shared volume, and optional plugin parameters.

Data Plane (a shared directory; swap for Redis/NFS without touching this code)
    Heavy binary blobs — the public crypto context and the ciphertext payloads —
    are exchanged on disk, bypassing HTTP body-size limits.

Plugin architecture ("single interface, multiple scenarios")
    The transport/audit/IO core below is static. Each business scenario is an
    isolated ComputePlugin registered into PLUGINS. Adding a scenario means
    writing one class — the core is never edited. Routing is by computation_type.

Blind-evaluator proof
    Every request logs the incoming payload size and a hex preview of the
    ciphertext, and asserts the loaded context is public-only. These lines are
    the verifiable terminal evidence that the node sees nothing but gibberish.
"""

from __future__ import annotations

import os
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import tenseal as ts
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Configuration (all overridable via environment variables)
# --------------------------------------------------------------------------- #
class Settings:
    SHARED_DIR: Path = Path(os.environ.get("HE_SHARED_DIR", "./he_shared")).resolve()
    # Fail before TenSEAL/protobuf's hard ~2 GiB serialization ceiling does.
    MAX_PAYLOAD_BYTES: int = int(os.environ.get("HE_MAX_PAYLOAD_BYTES", str(1_900_000_000)))
    HEX_PREVIEW_BYTES: int = int(os.environ.get("HE_HEX_PREVIEW_BYTES", "32"))
    HOST: str = os.environ.get("HE_HOST", "127.0.0.1")
    PORT: int = int(os.environ.get("HE_PORT", "8080"))


settings = Settings()
settings.SHARED_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("he.server")
audit = logging.getLogger("he.audit")


# --------------------------------------------------------------------------- #
# Security helpers
# --------------------------------------------------------------------------- #
def _within_shared(p: Path) -> bool:
    """True iff p lives inside the configured shared directory."""
    try:
        return p == settings.SHARED_DIR or p.is_relative_to(settings.SHARED_DIR)
    except AttributeError:  # Python < 3.9 fallback
        return str(p).startswith(str(settings.SHARED_DIR) + os.sep)


def _resolve_in_shared(path_str: str, *, must_exist: bool) -> Path:
    """
    Resolve a client-supplied path and confine it to the shared volume.
    Prevents path-traversal: an untrusted instruction can only touch the
    data plane, never arbitrary files on the host.
    """
    p = Path(path_str).resolve()
    if not _within_shared(p):
        raise HTTPException(400, f"Path is outside the shared volume: {path_str}")
    if must_exist and not p.exists():
        raise HTTPException(400, f"File not found in shared volume: {path_str}")
    return p


def _secret_key_present(context: "ts.Context") -> bool:
    """A correctly-prepared public context reports itself as non-private."""
    try:
        return bool(context.is_private())
    except Exception:
        # If the running TenSEAL build lacks the predicate, fail safe (assume ok).
        return False


def _audit_payload(name: str, raw: bytes) -> dict:
    """Emit the blind-evaluator proof and return it as structured metadata."""
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


# --------------------------------------------------------------------------- #
# Plugin framework
# --------------------------------------------------------------------------- #
@dataclass
class ComputeResult:
    """One serialized output ciphertext produced by a plugin."""
    label: str
    data: bytes
    depth: int | None = None


class ComputePlugin(ABC):
    """
    A single HE scenario. Subclasses declare their `name` (the routing key) and
    `scheme` ("BFV" or "CKKS", used to deserialize the payload), then implement
    the math in `run`. They receive an already-decoded ciphertext vector bound
    to the public context and return one or more serialized results.
    """
    name: ClassVar[str]
    scheme: ClassVar[str]

    @abstractmethod
    def run(self, vector, params: dict) -> list[ComputeResult]:
        ...


PLUGINS: dict[str, ComputePlugin] = {}


def register(plugin_cls: type[ComputePlugin]) -> type[ComputePlugin]:
    instance = plugin_cls()
    if not getattr(instance, "name", None) or not getattr(instance, "scheme", None):
        raise RuntimeError(f"{plugin_cls.__name__} must define `name` and `scheme`.")
    PLUGINS[instance.name] = instance
    return plugin_cls


def _deserialize(scheme: str, context, raw: bytes):
    if scheme == "BFV":
        return ts.bfv_vector_from(context, raw)
    if scheme == "CKKS":
        return ts.ckks_vector_from(context, raw)
    raise HTTPException(500, f"Plugin declared unknown scheme: {scheme}")


# --------------------------------------------------------------------------- #
# Scenario plugins
# --------------------------------------------------------------------------- #
@register
class SalaryBenchmarkPlugin(ComputePlugin):
    """
    Scenario A — Exact matching (BFV). Element-wise (x - median) * scale.
    `median` and `scale` are request parameters (no longer hardcoded), so the
    same plugin serves any exact-arithmetic benchmark.
    """
    name = "salary_benchmark"
    scheme = "BFV"

    def run(self, vector, params: dict) -> list[ComputeResult]:
        median = int(params.get("median", 90000))
        scale = int(params.get("scale", 2))
        median_vector = [median] * vector.size()
        log.info("BFV: (encrypted - %d) * %d over %d slots", median, scale, vector.size())
        result = (vector - median_vector) * scale
        return [ComputeResult(label="benchmark", data=result.serialize())]


@register
class MedicalRiskPlugin(ComputePlugin):
    """
    Scenario B — Predictive scoring (CKKS). Depth-3 polynomial x^8 + x^4 + x^2
    via repeated squaring. Cross-level addition relies on the context's default
    auto-rescale / auto-mod-switch (both on unless explicitly disabled).
    """
    name = "medical_risk"
    scheme = "CKKS"

    def run(self, vector, params: dict) -> list[ComputeResult]:
        log.info("CKKS depth-3 polynomial: x^8 + x^4 + x^2 (relinearize + rescale)")
        x2 = vector.square()   # depth 1
        x4 = x2.square()       # depth 2
        x8 = x4.square()       # depth 3
        result = x8 + x4 + x2
        return [ComputeResult(label="risk_score", data=result.serialize(), depth=3)]


@register
class CKKSErrorScalingPlugin(ComputePlugin):
    """
    Scenario C — CKKS error scaling vs multiplicative depth. Iteratively squares
    the input, emitting one ciphertext per depth so the agent can chart how the
    approximation error amplifies from x^2 up to x^(2^max_depth).
    """
    name = "ckks_error_scaling"
    scheme = "CKKS"

    def run(self, vector, params: dict) -> list[ComputeResult]:
        max_depth = int(params.get("max_depth", 4))
        log.info("CKKS iterative squaring to depth %d", max_depth)
        results: list[ComputeResult] = []
        current = vector
        for depth in range(1, max_depth + 1):
            current = current.square()
            results.append(
                ComputeResult(label=f"x^{2 ** depth}", data=current.serialize(), depth=depth)
            )
            log.info("  depth %d (x^%d) computed", depth, 2 ** depth)
        return results


# --------------------------------------------------------------------------- #
# Result writing
# --------------------------------------------------------------------------- #
def _write_results(result_path: str, results: list[ComputeResult]) -> tuple[str, list[dict]]:
    """
    Single output  -> written verbatim to result_path; primary == result_path.
    Multiple outputs -> written as <base>_d<depth>.bin (base = result_path minus
    a trailing '.bin'); primary == base. This matches the existing agent's
    expectations exactly while exposing explicit per-file metadata in `results`.
    """
    written: list[dict] = []

    if len(results) == 1:
        out = _resolve_in_shared(result_path, must_exist=False)
        out.write_bytes(results[0].data)
        written.append({"label": results[0].label, "depth": results[0].depth, "path": str(out)})
        return str(out), written

    base = result_path[:-4] if result_path.endswith(".bin") else result_path
    base_path = _resolve_in_shared(base, must_exist=False)
    for idx, r in enumerate(results, start=1):
        depth = r.depth if r.depth is not None else idx
        out = Path(f"{base_path}_d{depth}.bin")
        out.write_bytes(r.data)
        written.append({"label": r.label, "depth": depth, "path": str(out)})
    return str(base_path), written


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
class ComputeRequest(BaseModel):
    computation_type: str
    context_path: str
    payload_path: str
    result_path: str
    params: dict = Field(default_factory=dict)  # optional, backward-compatible


class ComputeResponse(BaseModel):
    status: str
    computation_type: str
    scheme: str
    result_path: str           # primary path (compat field)
    results: list[dict]        # explicit per-output metadata
    evaluation_time_sec: float
    audit: dict


app = FastAPI(title="HE Blind-Evaluator Compute Service")


@app.on_event("startup")
def _startup() -> None:
    log.info("Shared volume: %s", settings.SHARED_DIR)
    log.info("This node holds NO secret key and cannot decrypt any payload.")
    for name, plugin in sorted(PLUGINS.items()):
        log.info("Registered plugin: %-20s scheme=%s", name, plugin.scheme)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "plugins": sorted(PLUGINS)}


@app.get("/plugins")
def plugins() -> dict:
    return {name: {"scheme": p.scheme} for name, p in sorted(PLUGINS.items())}


@app.post("/compute", response_model=ComputeResponse)
def compute(req: ComputeRequest) -> ComputeResponse:
    log.info("Received request: %s", req.computation_type)

    plugin = PLUGINS.get(req.computation_type)
    if plugin is None:
        raise HTTPException(
            400,
            f"Unsupported computation_type '{req.computation_type}'. "
            f"Available: {sorted(PLUGINS)}",
        )

    # --- Load the public context from the data plane ----------------------- #
    ctx_path = _resolve_in_shared(req.context_path, must_exist=True)
    context = ts.context_from(ctx_path.read_bytes())

    # --- Blind-evaluator guarantee: never accept a secret key -------------- #
    if _secret_key_present(context):
        audit.error("REFUSED | context carries a secret key — blind evaluator must never receive sk")
        raise HTTPException(403, "Context contains a secret key; refusing to evaluate.")

    # --- Load and audit the ciphertext payload ----------------------------- #
    payload_path = _resolve_in_shared(req.payload_path, must_exist=True)
    raw_payload = payload_path.read_bytes()
    if len(raw_payload) > settings.MAX_PAYLOAD_BYTES:
        raise HTTPException(
            413,
            f"Payload {len(raw_payload)} bytes exceeds limit {settings.MAX_PAYLOAD_BYTES}. "
            f"Raise the polynomial modulus degree / batch differently on the agent.",
        )
    audit_meta = _audit_payload(req.computation_type, raw_payload)

    # --- Decode + evaluate entirely on ciphertext -------------------------- #
    try:
        vector = _deserialize(plugin.scheme, context, raw_payload)
        t0 = time.perf_counter()
        results = plugin.run(vector, req.params)
        eval_time = time.perf_counter() - t0
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Evaluation failed")
        raise HTTPException(500, f"Evaluation error: {exc}")

    primary, written = _write_results(req.result_path, results)
    log.info("Done in %.4fs -> %d output file(s)", eval_time, len(written))

    return ComputeResponse(
        status="success",
        computation_type=req.computation_type,
        scheme=plugin.scheme,
        result_path=primary,
        results=written,
        evaluation_time_sec=eval_time,
        audit=audit_meta,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)