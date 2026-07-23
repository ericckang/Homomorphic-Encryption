# Homomorphic Encryption — Blind-Evaluator Compute Service

A demonstration of **secure outsourced computation** using homomorphic encryption (HE).
An untrusted compute server runs real math on encrypted data **without ever being able
to decrypt it**, and proves it from its own logs.

This repo is the server/transport + compute half of a larger
"Generalizable HE Agent Architecture."

## Architecture

| Component | File | Role |
|-----------|------|------|
| **Agent / client** | `agent.py`, `agent_side/` | Trusted data-owner side. Hosts the agent UI, uses Azure OpenAI to plan an HE operation schema from a task prompt, generates keys, encrypts input data locally, calls the server, stores local results, and is the only party that can decrypt the result. |
| **Blind-evaluator server** | `server.py`, `server_side/` | Untrusted FastAPI compute node. Operates entirely on ciphertext; holds no secret key, refuses any context that carries one, and runs only the generic BFV/CKKS operation schema. |
| **Shared definitions** | `he_common/` | Non-sensitive config and operation schema validation shared by both sides. |

### File layout

```text
agent.py                 # trusted data-owner agent web UI by default, CLI with --cli
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
| `BFV` | exact integer vector pipelines, including integer reductions such as `sum_reduce` |
| `CKKS` | approximate real-number vector pipelines, including bounded polynomials and reductions such as `mean_reduce` / `dot_product_public` |

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

The recommended demo uses two independent processes and two browser views: one
untrusted compute server and one trusted data-owner agent. This matches the
privacy boundary in the project spec.

### Terminal 1 — untrusted compute server

Start the server in one terminal:

```bash
python3 server.py
# serves http://127.0.0.1:8080  (docs at /docs)
```

Then open:

```text
http://127.0.0.1:8080
```

The server dashboard is read-only. It shows server-side ciphertext audit data,
but it does not collect plaintext input and does not run trusted agent code.

### Terminal 2 — trusted agent UI

Run the trusted agent in a second terminal. Azure OpenAI credentials must be
available only in the agent shell:

```bash
export AZURE_OPENAI_KEY="<your-key>"
python3 agent.py
# serves http://127.0.0.1:8081
```

If your Azure setup also requires endpoint / deployment / API version, export
those too before running `agent.py`:

```bash
export AZURE_OPENAI_KEY="<your-key>"
export AZURE_OPENAI_ENDPOINT="https://<your-resource>.openai.azure.com/"
export AZURE_OPENAI_DEPLOYMENT="<your-deployment>"
export AZURE_OPENAI_API_VERSION="2024-12-01-preview"
python3 agent.py
```

Then open:

```text
http://127.0.0.1:8081
```

The agent UI accepts a natural-language task prompt and inline/manual/CSV data.
It runs local preflight checks before calling the LLM or sending anything to the
server. If the task is unsupported or the estimated payload is too large, the
agent blocks the request locally and shows a warning.

You can include data inline:

```text
Compare each salary to 90000 and double the difference. data=[85000, 90000, 95000]
```

Or request an encrypted reduction directly:

```text
Sum all salary into a scalar. data=[100, 90000, 95000]
```

```text
Compute a weighted risk score with weights [0.2, 0.3, 0.5]. data=[1.0, 2.0, 3.0]
```

Or leave the data out and use the manual values or CSV upload field:

```text
Compute a nonlinear medical risk score using x^8 + x^4 + x^2.
```

The agent UI shows:
- live HE pipeline status,
- the agent's schema name, input profile, and payload estimate,
- the server's ciphertext payload size and hex preview,
- the final decrypted result, timings, and accuracy check,
- sample input / expected / decrypted values,
- the saved local JSON result path under `agent_results/`.

The dashboards are designed to make the privacy boundary visible: the server only
sees ciphertext bytes and cannot decrypt them; readable numbers appear only after
the agent decrypts the returned result.

CSV input can be used in two ways.

### 1. Single-column CSV

A one-column numeric vector in a `value` column still works:

```csv
value
85000
90000
95000
```

See `data/sample_data.csv` for a ready-to-run example.

### 2. Multi-column CSV

The first version of multi-column CSV support works like this:
- the agent reads the CSV locally,
- the planner sees only non-sensitive table metadata such as column names and numeric types,
- your prompt should clearly name **one target numeric column**,
- the agent extracts that column locally and sends only the encrypted vector for that column to the server.

A ready-to-run example is included at:

```text
data/sample_employee_metrics.csv
```

Example file:

```csv
employee_id,salary,age,risk_score,department
1001,85000,29,1.05,Sales
1002,90000,34,1.10,Finance
1003,95000,41,1.15,Engineering
1004,99000,38,1.20,Marketing
```

### How to write prompts for multi-column CSVs

Be explicit about the column name. Good prompt patterns are:

```text
Compute the mean of the salary column in this CSV.
```

```text
Sum all values in the age column.
```


```text
Apply 0.5x^2 + 1.2x + 3 to the risk_score column.
```


### Prompt-writing tips

- **Name exactly one numeric column** whenever the CSV has multiple columns.
- Prefer exact column names such as `salary`, `age`, or `risk_score`.
- If multiple numeric columns exist and you do not clearly name one, the agent may reject the request as ambiguous.
- Non-numeric columns such as `department` cannot be encrypted with the current pipeline.
- This first version supports **one selected column at a time**, not multi-column formulas like `salary + age` or `salary * risk_score`.

### Currently supported multi-column CSV requests

These are good fits for the current HE pipeline:
- mean/average of one numeric column,
- sum of one numeric column,
- element-wise add/subtract/multiply by a public scalar on one numeric column,
- square of one numeric column,
- polynomial scoring on one numeric column,
- public-weight dot product on one numeric column.

These are **not** supported in this first version:
- combining two CSV columns in one encrypted computation,
- filtering rows such as `department = Sales`,
- sorting, min/max, median, or arbitrary branching logic.

To use the older terminal-only agent flow instead of the web UI:

```bash
export AZURE_OPENAI_KEY="<your-key>"
python3 agent.py --cli
```

The LLM receives only the task text with raw data redacted plus basic metadata
like vector length and integer-vs-float type. It returns a JSON operation schema
using a bounded DSL (`add_scalar`, `sub_scalar`, `mul_scalar`, `square`,
`polynomial`, `sum_reduce`, `mean_reduce`, `dot_product_public`). The agent
encrypts locally, sends the schema plus ciphertext to the compute service,
decrypts the returned ciphertext, and prints result samples, performance, and
CKKS approximation error when applicable. Watch the server log: every request
logs a `BLIND-EVAL` line with the ciphertext size and a hex preview — the proof
that the server only ever sees gibberish.

Before encryption, the agent runs preflight checks for unsupported tasks,
excessive multiplication depth, large input vectors, and estimated payload size.
Unsupported requests such as sorting, median, min/max, boolean comparison,
branching, encrypted division, and general classifiers are rejected early with a
clear explanation.

## Testing

Run a syntax check:

```bash
python3 -m compileall agent.py server.py agent_side server_side he_common scripts
```

Run the end-to-end smoke test without an Azure OpenAI key:

```bash
# Terminal 1
python3 server.py

# Terminal 2
python3 scripts/smoke_test.py
```

The smoke test sends fixed BFV and CKKS operation schemas directly to the
server. It verifies exact BFV decryption, BFV integer reduction, and bounded
CKKS approximation error for both polynomial and reduction workloads.

Run the HE boundary benchmark:

```bash
python3 scripts/benchmark_boundary.py
```

Read the benchmark summary:

```text
BENCHMARK.md
```

See `SPEC.md` for the full architecture, privacy model, and testing notes.

### Configuration

The server reads optional environment variables (all have defaults):

| Variable | Default | Meaning |
|----------|---------|---------|
| `HE_SHARED_DIR` | `./he_shared` | shared data-plane directory |
| `HE_HOST` / `HE_PORT` | `127.0.0.1` / `8080` | bind address |
| `HE_AGENT_HOST` / `HE_AGENT_PORT` | `127.0.0.1` / `8081` | trusted agent UI bind address |
| `HE_MAX_PAYLOAD_BYTES` | `1900000000` | reject payloads near TenSEAL's ~2 GiB serialization ceiling |

## Notes on HE parameters

- **BFV** gives exact integer results; **CKKS** gives approximate real results, and the
  approximation error grows with multiplicative depth.
- `poly_modulus_degree` sets both security and capacity: larger degree = more
  multiplicative depth and more SIMD slots, but quadratically larger/slower ciphertexts.
  A ciphertext holds at most `degree` (BFV) or `degree/2` (CKKS) values per request.
- Galois keys are included so the server can run slot-rotation-based reductions
  such as encrypted sums and weighted dot products. They increase context size
  compared with the original element-wise-only demo.
