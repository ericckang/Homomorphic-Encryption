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
  <title>HE Demo Dashboard</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0b1020;
      color: #e5e7eb;
      margin: 0;
      padding: 24px;
    }
    h1 { margin: 0 0 8px 0; }
    p { color: #94a3b8; }
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
      background: #0f172a;
      border: 1px solid #334155;
      color: #94a3b8;
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
      background: #6a9b86;
      border-color: #6a9b86;
      color: #f8fffb;
    }
    .card {
      background: #111827;
      border: 1px solid #1f2937;
      border-radius: 14px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,.2);
      box-sizing: border-box;
      overflow: hidden;
    }
    .label {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: #93c5fd;
      margin-bottom: 8px;
    }
    .value {
      font-size: 20px;
      font-weight: 700;
      margin-bottom: 6px;
    }
    .muted { color: #94a3b8; font-size: 14px; }
    textarea, input {
      width: 100%;
      max-width: 100%;
      box-sizing: border-box;
      display: block;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: #0f172a;
      padding: 12px;
      border-radius: 10px;
      overflow: auto;
      color: #cbd5e1;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      padding: 8px;
      border-bottom: 1px solid #1f2937;
      text-align: left;
      vertical-align: top;
    }
    .kv-table td:first-child {
      width: 42%;
      color: #93c5fd;
      font-weight: 600;
    }
    .mono-wrap {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      word-break: break-all;
      white-space: normal;
    }
    .pill {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      background: #1d4ed8;
      font-size: 12px;
      font-weight: 700;
    }
  </style>
</head>
<body>
  <h1>Homomorphic Encryption Demo Dashboard</h1>

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
      <div class=\"label\">Two-Process Demo</div>
      <div class=\"value\">Run the trusted agent separately</div>
      <div class=\"muted\">This dashboard belongs to the untrusted server process. It monitors <code>he_shared/demo_status.json</code> and the server compute log, but it does not execute agent code.</div>
      <pre># Terminal 1: untrusted compute server
python server.py

# Terminal 2: trusted data-owner agent
export AZURE_OPENAI_KEY=\"&lt;your-key&gt;\"
python agent.py</pre>
      <div class=\"muted\">Example prompt for the agent:</div>
      <pre>Compare each salary to 90000 and double the difference. data=[85000, 90000, 95000]</pre>
    </section>

    <section class=\"card\">
      <div class=\"label\">Agent</div>
      <div class=\"value\" id=\"agent-stage\">Loading...</div>
      <div class=\"muted\" id=\"agent-message\"></div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Schema Name</td><td id=\"agent-schema-name\">-</td></tr>
          <tr><td>Scheme</td><td id=\"agent-scheme\">-</td></tr>
          <tr><td>Estimated Depth</td><td id=\"agent-depth\">-</td></tr>
        </tbody>
      </table>
    </section>

    <section class=\"card\">
      <div class=\"label\">Server</div>
      <div class=\"value\" id=\"server-stage\">Loading...</div>
      <div class=\"muted\" id=\"server-message\"></div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Computation Type</td><td id=\"server-computation-type\">-</td></tr>
          <tr><td>Scheme</td><td id=\"server-scheme\">-</td></tr>
          <tr><td>Payload Size (KB)</td><td id=\"server-payload-kb\">-</td></tr>
          <tr><td>Hex Preview</td><td id=\"server-hex-preview\" class=\"mono-wrap\">-</td></tr>
        </tbody>
      </table>
    </section>

    <section class=\"card\">
      <div class=\"label\">Privacy Boundary</div>
      <div class=\"value\" id=\"privacy-title\">Server never decrypts</div>
      <div class=\"muted\" id=\"privacy-summary\">This untrusted node can audit ciphertext size and evaluate the requested schema, but decrypted values remain on the trusted agent side.</div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Secret Key Present</td><td>No</td></tr>
          <tr><td>Decrypted Result Visible Here</td><td>No</td></tr>
          <tr><td>Trusted Decryption Location</td><td>Agent UI on port 8081</td></tr>
          <tr><td>Server Eval Time (sec)</td><td id=\"server-evaluation-time\">-</td></tr>
        </tbody>
      </table>
    </section>
  </div>

  <script>
    function setText(id, value) {
      document.getElementById(id).textContent = value;
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
      setText('agent-schema-name', data.agent?.extra?.schema_name ?? '-');
      setText('agent-scheme', data.agent?.extra?.scheme ?? '-');
      setText('agent-depth', data.agent?.extra?.depth ?? '-');

      setText('server-stage', serverStage);
      setText('server-message', data.server?.message || '');
      const rawHexPreview = data.server?.last_request?.hex_preview;
      const hexPreview = rawHexPreview
        ? (rawHexPreview.length > 96 ? `${rawHexPreview.slice(0, 96)}...` : rawHexPreview)
        : '-';
      setText('server-computation-type', data.server?.last_request?.computation_type ?? '-');
      setText('server-scheme', data.server?.last_request?.scheme ?? '-');
      setText('server-payload-kb', data.server?.last_request?.payload_kb ?? '-');
      setText('server-hex-preview', hexPreview);
      setText('server-evaluation-time', data.server?.last_request?.evaluation_time_sec ?? '-');

    }

    refresh();
    setInterval(refresh, 250);
  </script>
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
        "operations": ["add_scalar", "sub_scalar", "mul_scalar", "square", "polynomial"],
    }


@app.post("/compute", response_model=ComputeResponse)
def compute(req: ComputeRequest) -> ComputeResponse:
    scheme = req.scheme.upper()
    log.info("Received generic compute request: computation_type=%s scheme=%s", req.computation_type, scheme)
    if scheme not in {"BFV", "CKKS"}:
        raise HTTPException(400, f"Unsupported scheme '{req.scheme}'. Available: ['BFV', 'CKKS']")

    payload_path = resolve_in_shared(req.payload_path, must_exist=True)
    last_request = {
        "computation_type": req.computation_type,
        "scheme": scheme,
        "schema_name": str(req.params.get("schema_name", req.computation_type)),
        "payload_path": str(payload_path),
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
    update_server("audited", "Server audited ciphertext payload and confirmed blind evaluation input.", last_request)

    try:
        vector = _deserialize(scheme, context, raw_payload)
        t0 = time.perf_counter()
        operations = req.params.get("operations")
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


def _deserialize(scheme: str, context, raw: bytes):
    if scheme == "BFV":
        return ts.bfv_vector_from(context, raw)
    if scheme == "CKKS":
        return ts.ckks_vector_from(context, raw)
    raise HTTPException(500, f"Unknown scheme: {scheme}")


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
