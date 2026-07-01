from __future__ import annotations

import time

import tenseal as ts
from fastapi import FastAPI, HTTPException

from server_side.api_models import ComputeRequest, ComputeResponse
from server_side.logging_config import audit, log
from server_side.pipeline import run_pipeline
from server_side.results import write_results
from server_side.security import audit_payload, resolve_in_shared, secret_key_present
from server_side.settings import settings
from server_side.types import ComputeResult


app = FastAPI(title="HE Blind-Evaluator Compute Service")


@app.on_event("startup")
def startup() -> None:
    log.info("Shared volume: %s", settings.SHARED_DIR)
    log.info("This node holds NO secret key and cannot decrypt any payload.")
    log.info("Generic compute enabled for schemes: BFV, CKKS")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "schemes": ["BFV", "CKKS"]}


@app.get("/capabilities")
def capabilities() -> dict:
    return {
        "schemes": ["BFV", "CKKS"],
        "operations": ["add_scalar", "sub_scalar", "mul_scalar", "square", "polynomial"],
    }


@app.post("/compute", response_model=ComputeResponse)
def compute(req: ComputeRequest) -> ComputeResponse:
    scheme = req.scheme.upper()
    log.info("Received generic compute request: computation_type=%s scheme=%s", req.computation_type, scheme)
    if scheme not in {"BFV", "CKKS"}:
        raise HTTPException(400, f"Unsupported scheme '{req.scheme}'. Available: ['BFV', 'CKKS']")

    context = ts.context_from(resolve_in_shared(req.context_path, must_exist=True).read_bytes())
    if secret_key_present(context):
        audit.error("REFUSED | context carries a secret key; blind evaluator must never receive sk")
        raise HTTPException(403, "Context contains a secret key; refusing to evaluate.")

    payload_path = resolve_in_shared(req.payload_path, must_exist=True)
    raw_payload = payload_path.read_bytes()
    if len(raw_payload) > settings.MAX_PAYLOAD_BYTES:
        raise HTTPException(
            413,
            f"Payload {len(raw_payload)} bytes exceeds limit {settings.MAX_PAYLOAD_BYTES}.",
        )
    audit_meta = audit_payload(req.computation_type, raw_payload)

    try:
        vector = _deserialize(scheme, context, raw_payload)
        t0 = time.perf_counter()
        operations = req.params.get("operations")
        result, depth = run_pipeline(vector, req.params, integer=(scheme == "BFV"))
        eval_time = time.perf_counter() - t0
        label = str(req.params.get("schema_name", req.computation_type))
        results = [ComputeResult(label=label, data=result.serialize(), depth=depth)]
        log.info("%s generic schema=%s operations=%d", scheme, label, len(operations or []))
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Evaluation failed")
        raise HTTPException(500, f"Evaluation error: {exc}")

    primary, written = write_results(req.result_path, results)
    log.info("Done in %.4fs -> %d output file(s)", eval_time, len(written))

    return ComputeResponse(
        status="success",
        computation_type=req.computation_type,
        scheme=scheme,
        result_path=primary,
        results=written,
        evaluation_time_sec=eval_time,
        audit=audit_meta,
    )


def _deserialize(scheme: str, context, raw: bytes):
    if scheme == "BFV":
        return ts.bfv_vector_from(context, raw)
    if scheme == "CKKS":
        return ts.ckks_vector_from(context, raw)
    raise HTTPException(500, f"Unknown scheme: {scheme}")


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
