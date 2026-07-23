from __future__ import annotations

import time

import tenseal as ts
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from he_common.demo_state import read_demo_state, update_server
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
    update_server("idle", "Server is ready and waiting for compute requests.")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Untrusted HE Server Dashboard</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      background: #f5f7fb;
      color: #17202a;
      margin: 0;
      padding: 24px;
    }
    h1 { margin: 0 0 8px 0; color: #0f172a; font-size: 32px; letter-spacing: -.02em; }
    p { color: #64748b; }
    main { max-width: 1680px; margin: 0 auto; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
      margin-top: 20px;
    }
    .pipeline {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
      margin: 20px 0 8px 0;
    }
    .pipeline-step {
      background: #f8fafc;
      border: 1px solid #d8e1ec;
      color: #64748b;
      border-radius: 999px;
      padding: 10px 12px;
      text-align: center;
      font-size: 13px;
      font-weight: 700;
    }
    .pipeline-step.active {
      background: #6c96b6;
      border-color: #6c96b6;
      color: #ffffff;
    }
    .pipeline-step.done {
      background: #87af9e;
      border-color: #87af9e;
      color: #ffffff;
    }
    .card {
      background: #ffffff;
      border: 1px solid #dbe3ee;
      border-radius: 14px;
      padding: 16px;
      box-shadow: 0 12px 28px rgba(15, 23, 42, .06), 0 2px 6px rgba(15, 23, 42, .04);
      box-sizing: border-box;
      overflow: hidden;
    }
    .label {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: #53789b;
      margin-bottom: 8px;
    }
    .value {
      font-size: 20px;
      font-weight: 700;
      margin-bottom: 6px;
    }
    .muted { color: #64748b; font-size: 14px; }
    textarea, input {
      width: 100%;
      max-width: 100%;
      box-sizing: border-box;
      display: block;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: #f8fafc;
      padding: 12px;
      border-radius: 10px;
      overflow: auto;
      color: #334155;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      padding: 8px;
      border-bottom: 1px solid #dbe3ee;
      text-align: left;
      vertical-align: top;
    }
    th {
      background: #f8fafc;
      color: #334155;
      font-weight: 700;
    }
    .kv-table td:first-child {
      width: 42%;
      color: #53789b;
      font-weight: 600;
    }
    .mono-wrap {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      word-break: break-all;
      white-space: normal;
    }
    .server-hidden {
      color: #6b7280;
    }
    .pill {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      background: #6c96b6;
      font-size: 12px;
      font-weight: 700;
    }
  </style>
</head>
<body>
<main>
  <h1>Untrusted HE Server Dashboard</h1>

  <div class=\"pipeline\">
    <div class=\"pipeline-step\" id=\"step-input\">Input</div>
    <div class=\"pipeline-step\" id=\"step-planning\">Planning</div>
    <div class=\"pipeline-step\" id=\"step-encrypting\">Encrypting</div>
    <div class=\"pipeline-step\" id=\"step-server\">Server Eval</div>
    <div class=\"pipeline-step\" id=\"step-decrypting\">Decrypting</div>
    <div class=\"pipeline-step\" id=\"step-result\">Result</div>
  </div>

  <div class=\"grid\">
    <section class=\"card\">
      <div class=\"label\">Agent</div>
      <div class=\"value\" id=\"agent-stage\">Loading...</div>
      <div class=\"muted\" id=\"agent-message\"></div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Planned Task</td><td id=\"agent-planned-task\">-</td></tr>
          <tr><td>HE Scheme</td><td id=\"agent-he-scheme\">-</td></tr>
          <tr><td>Estimated Depth</td><td id=\"agent-depth\">-</td></tr>
          <tr><td>Input Summary</td><td id=\"agent-input-summary\" class=\"server-hidden\">not visible on server</td></tr>
          <tr><td>Estimated Payload (KB)</td><td id=\"agent-payload-estimate\" class=\"server-hidden\">not visible on server</td></tr>
        </tbody>
      </table>
    </section>

    <section class=\"card\">
      <div class=\"label\">Server</div>
      <div class=\"value\" id=\"server-stage\">Loading...</div>
      <div class=\"muted\" id=\"server-message\"></div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Planned Task</td><td id=\"server-planned-task\">-</td></tr>
          <tr><td>HE Scheme</td><td id=\"server-he-scheme\">-</td></tr>
          <tr><td>Estimated Depth</td><td id=\"server-depth\">-</td></tr>
          <tr><td>Input Summary</td><td id=\"server-input-summary\" class=\"server-hidden\">not visible on server</td></tr>
          <tr><td>Estimated Payload (KB)</td><td id=\"server-estimated-payload\" class=\"server-hidden\">not visible on server</td></tr>
          <tr><td>Computation Type</td><td id=\"server-computation-type\">-</td></tr>
          <tr><td>Encrypted Constants</td><td id=\"server-encrypted-constants\">-</td></tr>
          <tr><td>Formula Path</td><td id=\"server-formula-path\">-</td></tr>
          <tr><td>Encrypted Inputs</td><td id=\"server-encrypted-inputs\">-</td></tr>
          <tr><td>Server View Formula</td><td id=\"server-display-formula\" class=\"mono-wrap\">-</td></tr>
          <tr><td>Payload (KB)</td><td id=\"server-payload-kb\">-</td></tr>
          <tr><td>Hex Preview</td><td id=\"server-hex-preview\" class=\"mono-wrap\">-</td></tr>
          <tr><td>Server Eval Time (sec)</td><td id=\"server-evaluation-time\">-</td></tr>
        </tbody>
      </table>
    </section>

    <section class=\"card\">
      <div class=\"label\">Privacy Boundary</div>
      <div class=\"value\" id=\"privacy-title\">Server never decrypts</div>
      <div class=\"muted\" id=\"privacy-summary\">This untrusted node can audit ciphertext size and evaluate the requested schema, but decrypted values remain on the trusted agent side.</div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Decryption Key Present</td><td>No</td></tr>
          <tr><td>Decrypted Result Visible Here</td><td>No</td></tr>
          <tr><td>Trusted Decryption Location</td><td>Agent on port 8081</td></tr>
        </tbody>
      </table>
    </section>
  </div>

  <script>
    function setText(id, value) {
      document.getElementById(id).textContent = value;
    }

    function formatServerFormula(value) {
      if (!value) return '-';
      return value;
    }

    function setPipelineStage(agentStage, serverStage) {
      const steps = [
        'step-input',
        'step-planning',
        'step-encrypting',
        'step-server',
        'step-decrypting',
        'step-result',
      ];
      steps.forEach(id => {
        const el = document.getElementById(id);
        el.classList.remove('active', 'done');
      });

      const markDone = ids => ids.forEach(id => document.getElementById(id).classList.add('done'));
      const markActive = id => document.getElementById(id).classList.add('active');

      if (agentStage === 'idle' || agentStage === 'collecting_input') {
        markActive('step-input');
        return;
      }
      if (agentStage === 'planning' || agentStage === 'planned') {
        markDone(['step-input']);
        markActive('step-planning');
        return;
      }
      if (agentStage === 'encrypting') {
        markDone(['step-input', 'step-planning']);
        markActive('step-encrypting');
        return;
      }
      if (agentStage === 'sending' || serverStage === 'received' || serverStage === 'audited' || serverStage === 'completed') {
        markDone(['step-input', 'step-planning', 'step-encrypting']);
        markActive('step-server');
      }
      if (agentStage === 'decrypting' || agentStage === 'reporting') {
        markDone(['step-input', 'step-planning', 'step-encrypting', 'step-server']);
        markActive('step-decrypting');
        return;
      }
      if (agentStage === 'done') {
        markDone(['step-input', 'step-planning', 'step-encrypting', 'step-server', 'step-decrypting', 'step-result']);
        return;
      }
      if (agentStage === 'error') {
        markActive('step-input');
      }
    }

    async function refresh() {
      const res = await fetch('/demo/status');
      const data = await res.json();

      const agentStage = data.agent?.stage || 'unknown';
      const serverStage = data.server?.status || 'unknown';
      setPipelineStage(agentStage, serverStage);

      setText('agent-stage', agentStage);
      setText('agent-message', data.agent?.message || '');
      setText('agent-planned-task', data.agent?.extra?.schema_name ?? '-');
      setText('agent-he-scheme', data.agent?.extra?.scheme ?? '-');
      setText('agent-depth', data.agent?.extra?.depth ?? '-');
      setText('agent-input-summary', 'not visible on server');
      setText('agent-payload-estimate', 'not visible on server');

      setText('server-stage', serverStage);
      setText('server-message', data.server?.message || '');
      const rawHexPreview = data.server?.last_request?.hex_preview;
      const hexPreview = rawHexPreview
        ? (rawHexPreview.length > 96 ? `${rawHexPreview.slice(0, 96)}...` : rawHexPreview)
        : '-';
      const encryptedOperandCount = data.server?.last_request?.encrypted_operand_count;
      const encryptedInputCount = data.server?.last_request?.encrypted_input_count;
      setText('server-planned-task', data.server?.last_request?.schema_name ?? data.agent?.extra?.schema_name ?? '-');
      setText('server-he-scheme', data.server?.last_request?.scheme ?? data.agent?.extra?.scheme ?? '-');
      setText('server-depth', data.server?.last_request?.depth ?? data.agent?.extra?.depth ?? '-');
      setText('server-input-summary', 'not visible on server');
      setText('server-estimated-payload', 'not visible on server');
      setText('server-computation-type', data.server?.last_request?.computation_type ?? '-');
      setText('server-encrypted-constants', encryptedOperandCount === undefined ? '-' : (encryptedOperandCount > 0 ? `Yes (${encryptedOperandCount})` : 'No'));
      setText('server-formula-path', data.server?.last_request?.formula_path ?? '-');
      setText('server-encrypted-inputs', encryptedInputCount === undefined ? '-' : `${encryptedInputCount}`);
      setText('server-display-formula', formatServerFormula(data.server?.last_request?.server_display_formula));
      setText('server-payload-kb', data.server?.last_request?.payload_kb ?? '-');
      setText('server-hex-preview', hexPreview);
      setText('server-evaluation-time', data.server?.last_request?.evaluation_time_sec ?? '-');

    }

    refresh();
    setInterval(refresh, 250);
  </script>
</main>
</body>
</html>
    """


@app.get("/demo/status")
def demo_status() -> dict:
    return read_demo_state()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "schemes": ["BFV", "CKKS"]}


@app.get("/capabilities")
def capabilities() -> dict:
    return {
        "schemes": ["BFV", "CKKS"],
        "operations": [
            "add_scalar",
            "sub_scalar",
            "mul_scalar",
            "add_encrypted_scalar",
            "sub_encrypted_scalar",
            "mul_encrypted_scalar",
            "square",
            "polynomial",
            "sum_reduce",
            "mean_reduce",
            "dot_product_public",
        ],
    }


@app.post("/compute", response_model=ComputeResponse)
def compute(req: ComputeRequest) -> ComputeResponse:
    scheme = req.scheme.upper()
    log.info("Received generic compute request: computation_type=%s scheme=%s", req.computation_type, scheme)
    if scheme not in {"BFV", "CKKS"}:
        raise HTTPException(400, f"Unsupported scheme '{req.scheme}'. Available: ['BFV', 'CKKS']")

    payload_path = resolve_in_shared(req.payload_path, must_exist=True)
    encrypted_operand_paths = req.params.get("encrypted_operand_paths") or {}
    encrypted_input_paths = req.params.get("encrypted_input_paths") or {}
    last_request = {
        "computation_type": req.computation_type,
        "scheme": scheme,
        "schema_name": str(req.params.get("schema_name", req.computation_type)),
        "payload_path": str(payload_path),
        "encrypted_operand_count": len(encrypted_operand_paths) if isinstance(encrypted_operand_paths, dict) else 0,
        "encrypted_input_count": len(encrypted_input_paths) if isinstance(encrypted_input_paths, dict) else 0,
        "server_display_formula": str(req.params.get("server_display_formula", "-"))[:300],
        "formula_path": str(req.params.get("formula_path", "planner"))[:80],
    }
    update_server("received", "Server received a compute request.", last_request)

    context = ts.context_from(resolve_in_shared(req.context_path, must_exist=True).read_bytes())
    if secret_key_present(context):
        audit.error("REFUSED | context carries a secret key; blind evaluator must never receive sk")
        raise HTTPException(403, "Context contains a secret key; refusing to evaluate.")

    raw_payload = payload_path.read_bytes()
    if len(raw_payload) > settings.MAX_PAYLOAD_BYTES:
        raise HTTPException(
            413,
            f"Payload {len(raw_payload)} bytes exceeds limit {settings.MAX_PAYLOAD_BYTES}.",
        )
    audit_meta = audit_payload(req.computation_type, raw_payload)
    last_request["payload_kb"] = audit_meta.get("payload_kb")
    last_request["hex_preview"] = audit_meta.get("hex_preview")
    encrypted_operands = _load_encrypted_operands(encrypted_operand_paths)
    encrypted_inputs = _load_encrypted_inputs(scheme, context, encrypted_input_paths)
    update_server("audited", "Server audited ciphertext payload and confirmed blind evaluation input.", last_request)

    try:
        vector = _deserialize(scheme, context, raw_payload)
        t0 = time.perf_counter()
        operations = req.params.get("operations")
        req.params["encrypted_operands"] = encrypted_operands
        req.params["encrypted_inputs"] = encrypted_inputs
        result, depth = run_pipeline(vector, req.params, integer=(scheme == "BFV"))
        eval_time = time.perf_counter() - t0
        last_request["evaluation_time_sec"] = round(eval_time, 4)
        last_request["depth"] = depth
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
    last_request["result_path"] = primary
    update_server(
        "completed",
        "Server finished homomorphic evaluation and returned result ciphertext it cannot decrypt.",
        last_request,
    )

    return ComputeResponse(
        status="success",
        computation_type=req.computation_type,
        scheme=scheme,
        result_path=primary,
        results=written,
        evaluation_time_sec=eval_time,
        audit=audit_meta,
    )


def _load_encrypted_operands(operand_paths: dict[str, str]) -> dict[str, bytes]:
    if not isinstance(operand_paths, dict):
        raise HTTPException(400, "params.encrypted_operand_paths must be an object when provided.")
    loaded: dict[str, bytes] = {}
    total_bytes = 0
    for key, path_str in operand_paths.items():
        if not isinstance(key, str) or not key.strip():
            raise HTTPException(400, "Encrypted operand keys must be non-empty strings.")
        if not isinstance(path_str, str) or not path_str.strip():
            raise HTTPException(400, f"Encrypted operand path for key '{key}' must be a non-empty string.")
        raw = resolve_in_shared(path_str, must_exist=True).read_bytes()
        total_bytes += len(raw)
        if total_bytes > settings.MAX_PAYLOAD_BYTES:
            raise HTTPException(413, "Combined encrypted operand payloads exceed the configured limit.")
        loaded[key.strip()] = raw
    return loaded


def _load_encrypted_inputs(scheme: str, context, input_paths: dict[str, str]) -> dict[str, object]:
    if not isinstance(input_paths, dict):
        raise HTTPException(400, "params.encrypted_input_paths must be an object when provided.")
    loaded: dict[str, object] = {}
    total_bytes = 0
    for key, path_str in input_paths.items():
        if not isinstance(key, str) or not key.strip():
            raise HTTPException(400, "Encrypted input keys must be non-empty strings.")
        if not isinstance(path_str, str) or not path_str.strip():
            raise HTTPException(400, f"Encrypted input path for key '{key}' must be a non-empty string.")
        raw = resolve_in_shared(path_str, must_exist=True).read_bytes()
        total_bytes += len(raw)
        if total_bytes > settings.MAX_PAYLOAD_BYTES:
            raise HTTPException(413, "Combined encrypted input payloads exceed the configured limit.")
        loaded[key.strip()] = _deserialize(scheme, context, raw)
    return loaded


def _deserialize(scheme: str, context, raw: bytes):
    if scheme == "BFV":
        return ts.bfv_vector_from(context, raw)
    if scheme == "CKKS":
        return ts.ckks_vector_from(context, raw)
    raise HTTPException(500, f"Unknown scheme: {scheme}")


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
