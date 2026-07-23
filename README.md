# Homomorphic Encryption — Blind-Evaluator Compute Service

A demonstration of **secure outsourced computation** using homomorphic encryption (HE).
An untrusted compute server runs real math on encrypted data **without ever being able
to decrypt it**, and proves it from its own logs.

This repo contains the full demo stack for a larger
"Generalizable HE Agent Architecture":
- a trusted agent that owns plaintext and the secret key,
- an untrusted compute server that evaluates ciphertext,
- shared helpers for validation, reporting, and demo state.

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
agent_side/              # input parsing, LLM planning, formula validation, encryption, transport, reporting
server_side/             # FastAPI app, security checks, generic HE operations
he_common/               # shared config, operation-plan helpers, demo state
data/sample_data.csv     # example CSV input
scripts/smoke_test.py    # end-to-end test with fixed operation schemas
scripts/benchmark_boundary.py
```

### First-read mental model

If you are new to this repo, read the runtime flow like this:

```text
prompt + local data
  -> agent_side/input_data.py
  -> agent_side/planner.py and/or agent_side/formula_parser.py
  -> agent_side/runner.py
  -> agent_side/transport.py
  -> server_side/app.py
  -> server_side/pipeline.py / server_side/expression_eval.py
  -> encrypted result back to agent
  -> agent_side/reporting.py
```

### Code tour for teammates

#### Trusted agent side

| File | Purpose |
|------|---------|
| `agent.py` | Starts the trusted agent UI or CLI. |
| `agent_side/app.py` | Trusted FastAPI dashboard and `/api/run` endpoint. Also handles frontend validation such as missing input data. |
| `agent_side/input_data.py` | Parses inline/manual/CSV input, calls LLM table-intent parsing for CSV tasks, and decides whether a request is a planner task, reduction task, or formula task. |
| `agent_side/planner.py` | Azure OpenAI integration. Used for both generic HE planning and LLM-based table intent parsing. |
| `agent_side/formula_parser.py` | Deterministic validator/parser for supported CSV arithmetic formulas. This is the safety layer after LLM intent parsing. |
| `agent_side/runner.py` | Main orchestration path: build plan, encrypt locally, call server, decrypt locally, and build the result summary. |
| `agent_side/crypto.py` | Creates TenSEAL contexts and performs encryption/decryption. |
| `agent_side/transport.py` | Writes shared artifacts and sends the JSON compute request to the server. |
| `agent_side/reporting.py` | Builds output samples, result summaries, and dashboard-friendly reporting objects. |

#### Untrusted server side

| File | Purpose |
|------|---------|
| `server.py` | Starts the untrusted compute service. |
| `server_side/app.py` | FastAPI server, dashboard, request audit, and `/compute` endpoint. |
| `server_side/pipeline.py` | Executes the validated HE DSL or restricted formula tree on ciphertext. |
| `server_side/expression_eval.py` | Evaluates serialized formula AST nodes over encrypted inputs. |
| `server_side/security.py` | Rejects secret-key-bearing contexts and constrains file access to the shared directory. |
| `server_side/results.py` | Writes encrypted result files back to disk. |

#### Shared helpers

| File | Purpose |
|------|---------|
| `he_common/operations.py` | Shared operation helpers, plaintext simulation, server display formula generation, and result normalization. |
| `he_common/demo_state.py` | Shared dashboard status state used by agent and server. |
| `he_common/config.py` | Shared URL and shared-directory defaults. |

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

The current multi-column CSV support works like this:
- the agent reads the CSV locally,
- the LLM sees only non-sensitive table metadata such as column names and numeric types,
- the agent first asks the LLM to classify the request as a formula intent, reduction intent, or generic planner request,
- if your prompt names **one target numeric column**, the agent can still encrypt that column directly and use the generic planner flow,
- if your prompt gives a supported arithmetic CSV formula such as `salary^2 + 5 * age + 6`, the deterministic formula parser validates it,
- once validated, the agent encrypts each referenced numeric column separately and sends those ciphertext vectors to the server for encrypted formula evaluation.

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

- Prefer exact column names such as `salary`, `age`, `height`, `weight`, or `risk_score`.
- If multiple numeric columns exist and you do not clearly name one, the agent may fall back to a default numeric column for some single-column planner tasks.
- Non-numeric columns such as `department` cannot be encrypted with the current pipeline.
- Supported CSV formulas are limited to numeric columns, constants, and `+`, `-`, `*`, `^`.
- Division, comparisons, function calls such as `log(...)`, and conditionals are intentionally rejected.
- For single-column requests, the agent can still encrypt one selected column and run the normal HE pipeline.
- For validated formula requests, the agent encrypts each referenced numeric column separately and the server evaluates the formula over ciphertext.
- If a prompt references an unknown column, the request should be rejected on the trusted side before server execution.

Example:

```text
compute risk score = height^2 + 5 * weight + 6
```

This prompt style is also supported:

```text
prompt: compute risk score for each data, risk score func: height^2 + 5 * weight + 6
```

With a CSV containing `salary` and `age`, a prompt like `compute risk score = salary^2 + 5 * age + 6` causes the agent to encrypt both `salary` and `age` separately and the server computes the risk score formula directly on ciphertext before returning the encrypted result.

The agent also blocks malformed CSV input locally before any server call, including:
- missing values in required numeric columns,
- non-numeric values in numeric columns,
- blank rows,
- mismatched row widths,
- unnamed header columns.

## Main request paths

There are three main request families in this codebase.

### 1. Generic planner path

Examples:
- `Compare each salary to 90000 and double the difference.`
- `Sum all salary into a scalar.`
- `Compute the mean of the salary column in this CSV.`

Flow:
1. Agent parses local input.
2. Agent sends only redacted prompt text plus metadata to Azure OpenAI.
3. Azure OpenAI returns a bounded HE operation schema.
4. Agent validates and sanitizes that schema.
5. Agent encrypts one primary vector.
6. Server evaluates the generic DSL.
7. Agent decrypts and reports.

### 2. Validated CSV formula path

Examples:
- `Compute risk score salary * 3 + age`
- `Use salary^2 + 5 * age + 6 as the risk score`
- `Compute score salary * 2 + 3`

Flow:
1. Agent loads the CSV locally.
2. Agent asks Azure OpenAI for a table intent.
3. If the request is a formula intent, the deterministic formula parser validates the expression.
4. Agent encrypts each referenced numeric column separately.
5. Server evaluates the restricted formula AST over ciphertext.
6. Agent decrypts and reports.

### 3. Rejected request path

Examples:
- unknown CSV columns such as `bonus`,
- unsupported syntax such as `/`, `>`, `<`, `log(...)`, or `if ... else`,
- missing CSV/manual/inline data,
- malformed CSV input.

These requests should be blocked on the trusted side before server compute.

### Currently supported multi-column CSV requests

These are good fits for the current HE pipeline:
- mean/average of one numeric column,
- sum of one numeric column,
- element-wise add/subtract/multiply by a public scalar on one numeric column,
- square of one numeric column,
- polynomial scoring on one numeric column,
- public-weight dot product on one numeric column,
- rule-based multi-column encrypted formulas using multiple numeric CSV columns with only constants, `+`, `-`, `*`, and integer powers `^`.

These are **not** supported in this version:
- formulas with division, boolean comparisons, conditionals, or function calls,
- filtering rows such as `department = Sales`,
- sorting, min/max, median, or arbitrary branching logic,
- general planner-driven multi-input DAGs beyond the current rule-based CSV formula path.

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

## What each dashboard is supposed to prove

### Trusted agent dashboard
Shows information that only the trusted side should know or reconstruct:
- plaintext input summary,
- expected plaintext output,
- decrypted output,
- encryption/decryption timings,
- local saved result path.

### Untrusted server dashboard
Shows only what the server can know:
- ciphertext payload size,
- ciphertext hex preview,
- scheme and computation type,
- encrypted-input count,
- encrypted-constant count,
- server-visible formula string,
- evaluation time.

If the architecture is behaving correctly, readable user values should appear only on the trusted agent side after decryption.

## Development notes for teammates

When debugging, first identify which request path was taken:

1. **Planner path** -> `operations` list exists.
2. **Formula path** -> `formula_ast` and `formula_columns` exist.
3. **Reduction path** -> planner path with final `sum_reduce` or `mean_reduce`.
4. **Rejected path** -> trusted side should stop before server compute.

Useful files by symptom:
- Prompt classified incorrectly -> `agent_side/input_data.py`, `agent_side/planner.py`
- Formula parse/validation issue -> `agent_side/formula_parser.py`
- Wrong server evaluation -> `server_side/pipeline.py`, `server_side/expression_eval.py`
- Wrong dashboard display -> `agent_side/app.py`, `agent_side/reporting.py`, `server_side/app.py`
- Context / encryption problems -> `agent_side/crypto.py`, `agent_side/runner.py`

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
