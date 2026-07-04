# Homomorphic Encryption — Blind-Evaluator Compute Service

A demonstration of **secure outsourced computation** using homomorphic encryption (HE).
An untrusted compute server runs real math on encrypted data **without ever being able
to decrypt it**, and proves it from its own logs.

This repo is the server/transport + compute half of a larger
"Generalizable HE Agent Architecture."

## Architecture

| Component | File | Role |
|-----------|------|------|
| **Agent / client** | `agent.py`, `agent_side/` | Trusted data-owner side. Uses Azure OpenAI to plan an HE operation schema from a task prompt, generates keys, encrypts input data locally, calls the server, and is the only party that can decrypt the result. |
| **Blind-evaluator server** | `server.py`, `server_side/` | Untrusted FastAPI compute node. Operates entirely on ciphertext; holds no secret key, refuses any context that carries one, and runs only the generic BFV/CKKS operation schema. |
| **Shared definitions** | `he_common/` | Non-sensitive config and operation schema validation shared by both sides. |

### File layout

```text
agent.py                 # thin entrypoint for the trusted data-owner agent
server.py                # thin entrypoint for the untrusted compute service
agent_side/              # input parsing, LLM planning, encryption, transport, reporting
server_side/             # FastAPI app, security checks, generic HE operations
he_common/               # shared config and operation-plan helpers
data/sample_data.csv     # example CSV input
scripts/smoke_test.py    # end-to-end test with fixed operation schemas
scripts/benchmark_boundary.py
```

**Two planes:**
- **Control plane** — lightweight JSON instructions over REST (`computation_type`, paths, params).
- **Data plane** — heavy binary blobs (the public crypto context + ciphertext payloads)
  exchanged via a shared directory (`./he_shared`), bypassing HTTP body-size limits.

### Generic Compute Capability

The server does not contain scenario-specific code for salary, medical,
financial, energy, or other domains. New scenarios are handled by the LLM
planner producing a bounded operation schema that the generic server pipeline
can execute.

| Scheme | Operation style |
|--------|-----------------|
| `BFV` | exact integer element-wise pipelines |
| `CKKS` | approximate real-number element-wise pipelines, including bounded polynomials |

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

The easiest way to demo the system is through the **web dashboard**. The server
hosts both the untrusted compute service and a small dashboard that can trigger
the trusted agent flow in the background.

### Option A — Recommended: web dashboard demo

Start the server in one terminal. Since the dashboard-triggered agent run happens
inside the server process, Azure OpenAI credentials must be available in the
same shell before launching `server.py`.

```bash
export AZURE_OPENAI_KEY="<your-key>"
python server.py
# serves http://127.0.0.1:8080  (docs at /docs)
```

If your Azure setup also requires endpoint / deployment / API version, export
those too:

```bash
export AZURE_OPENAI_KEY="<your-key>"
export AZURE_OPENAI_ENDPOINT="https://<your-resource>.openai.azure.com/"
export AZURE_OPENAI_DEPLOYMENT="<your-deployment>"
export AZURE_OPENAI_API_VERSION="2024-12-01-preview"
python server.py
```

Then open:

```text
http://127.0.0.1:8080
```

Use the **Run Demo Task** box and include inline data directly in the prompt, for example:

```text
Compare each salary to 90000 and double the difference. data=[85000, 90000, 95000]
```

The dashboard shows:
- a live HE pipeline progress bar,
- the agent's chosen schema and HE scheme,
- the server's ciphertext payload size and hex preview,
- the final decrypted result and timing metrics,
- sample input / expected / decrypted values.

This dashboard is designed to make the privacy boundary visible: the server only
sees ciphertext bytes and cannot decrypt them; readable numbers appear only after
the agent decrypts the returned result.

### Option B — CLI agent + server in two terminals

You can still run the original interactive CLI flow.

**Terminal 1 — the untrusted server:**
```bash
python server.py
```

**Terminal 2 — the client / generalized HE agent:**
```bash
export AZURE_OPENAI_KEY="<your-key>"
python agent.py
```

The agent asks for a natural-language task prompt. You can include data inline:

```text
Compare each salary to 90000 and double the difference. data=[85000, 90000, 95000]
```

Or leave the data out and provide a CSV path when prompted:

```text
Compute a nonlinear medical risk score using x^8 + x^4 + x^2.
```

CSV format is one numeric vector in a `value` column:

```csv
value
85000
90000
95000
```

See `data/sample_data.csv` for a ready-to-run example.

The LLM receives only the task text with raw data redacted plus basic metadata
like vector length and integer-vs-float type. It returns a JSON operation schema
using a bounded DSL (`add_scalar`, `sub_scalar`, `mul_scalar`, `square`,
`polynomial`). The agent encrypts locally, sends the schema plus ciphertext to
the compute service, decrypts the returned ciphertext, and prints result samples,
performance, and CKKS approximation error when applicable. Watch the server log:
every request logs a `BLIND-EVAL` line with the ciphertext size and a hex preview
— the proof that the server only ever sees gibberish.

Before encryption, the agent runs preflight checks for unsupported tasks,
excessive multiplication depth, large input vectors, and estimated payload size.
Unsupported requests such as sorting, median, min/max, boolean comparison,
branching, encrypted division, and general classifiers are rejected early with a
clear explanation.

## Testing

Run a syntax check:

```bash
python -m compileall agent.py server.py agent_side server_side he_common scripts
```

Run the end-to-end smoke test without an Azure OpenAI key:

```bash
# Terminal 1
python server.py

# Terminal 2
python scripts/smoke_test.py
```

The smoke test sends fixed BFV and CKKS operation schemas directly to the
server. It verifies exact BFV decryption and bounded CKKS approximation error.

Run the HE boundary benchmark:

```bash
python scripts/benchmark_boundary.py
```

See `SPEC.md` for the full architecture, privacy model, and testing notes.

### Configuration

The server reads optional environment variables (all have defaults):

| Variable | Default | Meaning |
|----------|---------|---------|
| `HE_SHARED_DIR` | `./he_shared` | shared data-plane directory |
| `HE_HOST` / `HE_PORT` | `127.0.0.1` / `8080` | bind address |
| `HE_MAX_PAYLOAD_BYTES` | `1900000000` | reject payloads near TenSEAL's ~2 GiB serialization ceiling |

## Notes on HE parameters

- **BFV** gives exact integer results; **CKKS** gives approximate real results, and the
  approximation error grows with multiplicative depth.
- `poly_modulus_degree` sets both security and capacity: larger degree = more
  multiplicative depth and more SIMD slots, but quadratically larger/slower ciphertexts.
  A ciphertext holds at most `degree` (BFV) or `degree/2` (CKKS) values per request.
- Galois keys are intentionally omitted (no slot rotations are used) to keep contexts small.
