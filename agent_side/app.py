from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent_side.input_data import resolve_task_and_data
from agent_side.preflight import agent_limits, estimate_payload_bytes, preflight_input_vector
from agent_side.result_store import list_agent_results
from agent_side.runner import run_agent_task
from he_common.demo_state import read_demo_state, reset_demo_state, update_agent
from he_common.operations import data_profile


AGENT_HOST = os.environ.get("HE_AGENT_HOST", "127.0.0.1")
AGENT_PORT = int(os.environ.get("HE_AGENT_PORT", "8081"))

app = FastAPI(title="Trusted HE Agent")


class AgentRunRequest(BaseModel):
    task_prompt: str
    manual_values: str | None = None
    csv_text: str | None = None
    encrypt_formula_constants: bool = False


@app.on_event("startup")
def startup() -> None:
    reset_demo_state()
    update_agent("idle", "Trusted agent UI is ready.")


@app.get("/", response_class=HTMLResponse)
def agent_dashboard() -> str:
    return """
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Trusted HE Agent</title>
  <style>
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0b1020;
      color: #e5e7eb;
      padding: 24px;
    }
    h1 { margin: 0 0 8px 0; }
    p { color: #94a3b8; }
    main { max-width: 1320px; margin: 0 auto; }
    .pipeline {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
      margin: 20px 0 16px 0;
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
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }
    .input-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    .input-card {
      width: 100%;
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
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      color: #cbd5e1;
      margin: 14px 0 6px;
    }
    textarea, input {
      width: 100%;
      max-width: 100%;
      box-sizing: border-box;
      display: block;
      border: 1px solid #334155;
      border-radius: 10px;
      padding: 12px;
      background: #0f172a;
      color: #e5e7eb;
      font: 15px ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .file-input-hidden {
      display: none;
    }
    .file-upload-row {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-top: 6px;
      flex-wrap: wrap;
    }
    .file-upload-button {
      margin-top: 0;
      padding: 10px 16px;
      box-shadow: none;
      background: #1e293b;
      border: 1px solid #334155;
    }
    .file-upload-name {
      color: #cbd5e1;
      font-size: 14px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      word-break: break-all;
    }

    textarea { min-height: 96px; resize: vertical; }
    button {
      margin-top: 16px;
      background: #1d4ed8;
      color: #ffffff;
      border: 0;
      border-radius: 999px;
      padding: 12px 18px;
      font-weight: 800;
      cursor: pointer;
      box-shadow: 0 10px 22px rgba(29, 78, 216, .24);
    }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .note {
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 10px;
      background: #0f172a;
      color: #cbd5e1;
      font-size: 14px;
    }
    .note.error {
      border: 1px solid #7f1d1d;
      color: #fecaca;
    }
    .note.success {
      border: 1px solid #14532d;
      color: #bbf7d0;
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
      margin: 0 8px 8px 0;
    }
    .saved-item {
      padding: 10px 0;
      border-bottom: 1px solid #1f2937;
    }
    .saved-item:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }
    @media (max-width: 960px) {
      .pipeline {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
      .input-card {
        width: 100%;
      }
    }
  </style>
</head>
<body>
<main>
  <h1>Trusted HE Agent Dashboard</h1>
  <p>This page owns plaintext input, encrypts locally, sends only ciphertext to the compute service, then decrypts the returned result on the agent side.</p>

  <div class=\"pipeline\">
    <div class=\"pipeline-step\" id=\"step-input\">Input</div>
    <div class=\"pipeline-step\" id=\"step-planning\">Planning</div>
    <div class=\"pipeline-step\" id=\"step-encrypting\">Encrypting</div>
    <div class=\"pipeline-step\" id=\"step-server\">Server Eval</div>
    <div class=\"pipeline-step\" id=\"step-decrypting\">Decrypting</div>
    <div class=\"pipeline-step\" id=\"step-result\">Result</div>
  </div>

  <section class=\"input-grid\">
    <section class=\"card input-card\">
      <div class=\"label\">Run Private Task</div>
      <div class=\"value\">Submit input from the trusted side</div>
      <div class=\"muted\">If the request exceeds local limits, the agent will block it before anything is sent to the server.</div>

      <label for=\"task-prompt\">Task prompt</label>
      <textarea id=\"task-prompt\">Sum all salary into a scalar. data=[100, 90000, 95000]</textarea>

      <label for=\"manual-values\">Manual values, if not included in prompt</label>
      <input id=\"manual-values\" placeholder=\"[100, 90000, 95000]\" />

      <label for=\"csv-file\">CSV upload</label>
      <input id=\"csv-file\" class=\"file-input-hidden\" type=\"file\" accept=\".csv,text/csv\" onchange=\"updateSelectedFileName()\" />
      <div class=\"file-upload-row\">
        <button type=\"button\" class=\"file-upload-button\" onclick=\"document.getElementById('csv-file').click()\">Choose CSV File</button>
        <span id=\"csv-file-name\" class=\"file-upload-name\">No file selected</span>
      </div>

      <label for=\"encrypt-formula-constants\">
        <input id=\"encrypt-formula-constants\" type=\"checkbox\" style=\"width:auto; display:inline-block; margin-right:8px;\" />
        Encrypt eligible formula constants before sending the plan to the server
      </label>
      <div class=\"muted\">For operations like x+5, x-5, or x*5, the constant can be turned into ciphertext so the server only sees an encrypted operand.</div>

      <button id=\"run-button\" onclick=\"runAgent()\">Run Trusted Agent</button>

      <div id=\"run-message\" class=\"note\">Ready for a new encrypted computation.</div>
    </section>
  </section>

  <section class=\"grid\">
    <section class=\"card\">
      <div class=\"label\">Agent</div>
      <div class=\"value\" id=\"agent-stage\">Loading...</div>
      <div class=\"muted\" id=\"agent-message\"></div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Schema Name</td><td id=\"agent-schema-name\">-</td></tr>
          <tr><td>Input Profile</td><td id=\"agent-input-profile\">-</td></tr>
          <tr><td>Estimated Payload</td><td id=\"agent-payload-estimate\">-</td></tr>
        </tbody>
      </table>
    </section>

    <section class=\"card\">
      <div class=\"label\">Server</div>
      <div class=\"value\" id=\"server-stage\">Loading...</div>
      <div class=\"muted\" id=\"server-message\"></div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Payload Size (KB)</td><td id=\"server-payload-kb\">-</td></tr>
          <tr><td>Hex Preview</td><td id=\"server-hex-preview\" class=\"mono-wrap\">-</td></tr>
        </tbody>
      </table>
    </section>

    <section class=\"card\">
      <div class=\"label\">Result</div>
      <div class=\"value\" id=\"result-title\">No result yet</div>
      <div class=\"muted\" id=\"result-summary\">Waiting for agent decryption...</div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Vector Length</td><td id=\"result-vector-length\">-</td></tr>
          <tr><td>Poly Modulus Degree</td><td id=\"result-poly-degree\">-</td></tr>
          <tr><td>Saved JSON</td><td id=\"result-saved-path\" class=\"mono-wrap\">-</td></tr>
        </tbody>
      </table>
    </section>
  </section>

  <section class=\"grid\">
    <section class=\"card\">
      <div class=\"label\">Benchmarks</div>
      <table class=\"kv-table\">
        <tbody>
          <tr><td>Encryption Time</td><td id=\"result-encryption\">-</td></tr>
          <tr><td>Server Eval Time</td><td id=\"result-evaluation\">-</td></tr>
          <tr><td>Round-trip Time</td><td id=\"result-roundtrip\">-</td></tr>
          <tr><td>Decryption Time</td><td id=\"result-decryption\">-</td></tr>
          <tr><td>Accuracy Check</td><td id=\"result-accuracy\">-</td></tr>
        </tbody>
      </table>
    </section>

    <section class=\"card\">
      <div class=\"label\">Local Limits</div>
      <div id=\"limits\"></div>
      <div class=\"muted\">Requests that exceed these limits are rejected locally and never sent to the compute service.</div>
    </section>

    <section class=\"card\">
      <div class=\"label\">Saved Results</div>
      <div id=\"saved-results\" class=\"muted\">No saved results yet.</div>
    </section>
  </section>

  <section class=\"grid\">
    <section class=\"card\">
      <div class=\"label\">Sample Outputs</div>
      <table>
        <thead><tr><th>Index</th><th>Input</th><th>Expected</th><th>Decrypted</th></tr></thead>
        <tbody id=\"samples-body\"><tr><td colspan=\"4\" class=\"muted\">No samples yet.</td></tr></tbody>
      </table>
    </section>
  </section>
</main>

<script>
async function csvTextFromFile() {
  const fileInput = document.getElementById('csv-file');
  if (!fileInput.files.length) return null;
  return await fileInput.files[0].text();
}

function updateSelectedFileName() {
  const fileInput = document.getElementById('csv-file');
  const label = document.getElementById('csv-file-name');
  label.textContent = fileInput.files.length ? fileInput.files[0].name : 'No file selected';
}

async function runAgent() {
  const button = document.getElementById('run-button');
  const message = document.getElementById('run-message');
  button.disabled = true;
  message.className = 'note';
  message.textContent = 'Running local preflight, planning, encryption, server compute, and local decryption...';
  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        task_prompt: document.getElementById('task-prompt').value,
        manual_values: document.getElementById('manual-values').value,
        csv_text: await csvTextFromFile(),
        encrypt_formula_constants: document.getElementById('encrypt-formula-constants').checked,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Agent run failed.');
    message.className = 'note success';
    message.textContent = 'Done. The result was decrypted locally, displayed below, and saved on the agent side.';
    renderRunResult(data.result_summary);
  } catch (err) {
    message.className = 'note error';
    message.textContent = err.message;
  } finally {
    button.disabled = false;
    refreshStatus();
  }
}

function setText(id, value) {
  document.getElementById(id).textContent = value ?? '-';
}

function seconds(value) {
  return value === undefined || value === null ? '-' : `${Number(value).toFixed(4)} sec`;
}

function renderRunResult(result) {
  const title = result
    ? `${result.schema_name} (${result.scheme}${result.encrypt_formula_constants ? ', encrypted constants' : ''})`
    : 'No result yet';
  setText('result-title', title);
  setText('result-summary', result?.formula || 'Waiting for agent decryption...');
  setText('result-vector-length', result?.vector_length ?? '-');
  setText('result-poly-degree', result?.poly_modulus_degree ?? '-');
  setText('result-saved-path', result?.saved_result_path ?? '-');
  setText('result-encryption', seconds(result?.encryption_time_sec));
  setText('result-evaluation', seconds(result?.evaluation_time_sec));
  setText('result-roundtrip', seconds(result?.roundtrip_time_sec));
  setText('result-decryption', seconds(result?.decryption_time_sec));
  const accuracy = !result
    ? '-'
    : result.scheme === 'CKKS'
      ? `Max abs error ${Number(result.max_abs_error ?? 0).toExponential(3)}`
      : `${result.exact_mismatches ?? 0} exact mismatches`;
  setText('result-accuracy', accuracy);
  const samples = result.samples || [];
  document.getElementById('samples-body').innerHTML = samples.length
    ? samples.map(s => `<tr><td>${s.index}</td><td>${s.input}</td><td>${s.expected}</td><td>${s.decrypted}</td></tr>`).join('')
    : '<tr><td colspan=\"4\" class=\"muted\">No samples yet.</td></tr>';
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

  if (agentStage === 'idle' || agentStage === 'collecting_input' || agentStage === 'preflight') {
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
    if (agentStage !== 'decrypting' && agentStage !== 'reporting' && agentStage !== 'done') {
      return;
    }
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
  if (agentStage === 'blocked' || agentStage === 'error') {
    markActive('step-input');
  }
}

function renderSavedResults(saved) {
  document.getElementById('saved-results').innerHTML = saved.length
    ? saved.map(r => `
        <div class="saved-item">
          <div>${r.name}</div>
          <div class="muted">${r.size_kb} KB</div>
        </div>
      `).join('')
    : 'No saved results yet.';
}

function inputProfile(extra) {
  const length = extra?.vector_length;
  const kind = extra?.numeric_kind;
  if (length === undefined && !kind) return '-';
  const pieces = [];
  if (length !== undefined) pieces.push(`${length} values`);
  if (kind) pieces.push(kind);
  return pieces.join(' | ');
}

function payloadEstimate(extra) {
  const payloadKb = extra?.estimated_payload_kb ?? extra?.conservative_payload_kb;
  return payloadKb === undefined ? '-' : `${payloadKb} KB`;
}

async function refreshStatus() {
  const res = await fetch('/api/status');
  const data = await res.json();
  const state = data.state || {};
  const agent = state.agent || {};
  const server = state.server || {};
  const agentStage = agent.stage || 'idle';
  const serverStage = server.status || 'idle';

  setPipelineStage(agentStage, serverStage);

  setText('agent-stage', agentStage);
  setText('agent-message', agent.message || '');
  setText('agent-schema-name', agent.extra?.schema_name ?? '-');
  setText('agent-input-profile', inputProfile(agent.extra));
  setText('agent-payload-estimate', payloadEstimate(agent.extra));

  setText('server-stage', serverStage);
  setText('server-message', server.message || '');
  const rawHexPreview = server.last_request?.hex_preview;
  const hexPreview = rawHexPreview
    ? (rawHexPreview.length > 96 ? `${rawHexPreview.slice(0, 96)}...` : rawHexPreview)
    : '-';
  setText('server-payload-kb', server.last_request?.payload_kb ?? '-');
  setText('server-hex-preview', hexPreview);

  renderRunResult(state.result);
  renderSavedResults(data.saved_results || []);
}

async function refreshLimits() {
  const res = await fetch('/api/limits');
  const data = await res.json();
  document.getElementById('limits').innerHTML = `
    <div class=\"pill\">Max vector: ${data.max_vector_length.toLocaleString()}</div>
    <div class=\"pill\">Max CKKS depth: ${data.max_ckks_depth}</div>
    <div class=\"pill\">Max BFV depth: ${data.max_bfv_depth}</div>
    <div class=\"pill\">Max ops: ${data.max_operation_count}</div>
    <div class=\"pill\">Payload limit: ${(data.max_estimated_payload_bytes / 1024 / 1024).toFixed(0)} MB</div>
  `;
}

refreshLimits();
refreshStatus();
setInterval(refreshStatus, 750);
</script>
</body>
</html>
    """


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {"state": read_demo_state(), "saved_results": list_agent_results()}


@app.get("/api/limits")
def limits() -> dict[str, Any]:
    return agent_limits()


@app.post("/api/run")
def run_task(req: AgentRunRequest) -> dict[str, Any]:
    try:
        reset_demo_state()
        _, redacted_prompt, data, input_metadata = _resolve_web_input(req)
        preflight_input_vector(data)
        profile = data_profile(data, input_metadata)
        conservative_payload = estimate_payload_bytes("CKKS", len(data))
        update_agent(
            "preflight",
            "Agent preflight passed. Raw values remain local to the trusted agent.",
            {
                "vector_length": len(data),
                "numeric_kind": profile["numeric_kind"],
                "conservative_payload_kb": round(conservative_payload / 1024, 2),
                "input_kind": profile.get("input_kind"),
                "selected_column": profile.get("selected_column"),
            },
        )
        result = run_agent_task(
            redacted_prompt,
            data,
            input_metadata=input_metadata,
            reset_state=False,
            encrypt_formula_constants=req.encrypt_formula_constants,
        )
        return {
            "status": "success",
            "result_summary": result["result_summary"],
            "plan": result["plan"],
        }
    except ValueError as exc:
        update_agent("blocked", str(exc))
        raise HTTPException(400, str(exc))
    except Exception as exc:
        update_agent("error", str(exc))
        raise HTTPException(500, str(exc))


def _resolve_web_input(req: AgentRunRequest) -> tuple[str, str, list[float], dict[str, Any]]:
    task_prompt = req.task_prompt.strip()
    if not task_prompt:
        raise ValueError("Task prompt is required.")
    return resolve_task_and_data(task_prompt, req.manual_values, req.csv_text)


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=AGENT_HOST, port=AGENT_PORT)
