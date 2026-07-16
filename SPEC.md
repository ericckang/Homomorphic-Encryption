# Homomorphic Encryption Agent Specification

## 1. Project Goal

This project demonstrates a generalizable homomorphic encryption (HE) agent
architecture. A trusted agent owns private numeric data, encrypts it locally,
and sends only ciphertext to an untrusted compute server. The server evaluates
approved operations over encrypted vectors and returns an encrypted result.
Only the agent can decrypt the final answer.

The core privacy claim is:

```text
The server never receives user plaintext data or a secret key.
```

## 2. System Components

```text
agent.py                 Trusted data-owner agent UI; CLI mode with --cli
server.py                Thin entrypoint for the untrusted compute service
agent_side/              Agent-side input, planning, encryption, transport, reporting
server_side/             Server-side API, validation, encrypted compute pipeline
he_common/               Shared non-sensitive config and operation schema helpers
data/sample_data.csv     Example CSV input
scripts/smoke_test.py    End-to-end BFV/CKKS smoke test, no Azure key required
scripts/benchmark_boundary.py
BENCHMARK.md             Benchmark summary and presentation notes
```

### Agent Side

The agent side is trusted. It handles:

- User task prompt and numeric input parsing.
- Agent-side web UI for prompt, manual vector input, and CSV upload.
- Azure OpenAI planning from a redacted task prompt.
- Early preflight checks before LLM planning and server transfer.
- HE parameter selection.
- Key/context generation.
- Local encryption and decryption.
- Sending ciphertext metadata to the server.
- Printing decrypted results, timings, and CKKS approximation error.
- Saving local JSON result summaries under `agent_results/`.

Important files:

- `agent_side/cli.py`: orchestrates the full agent workflow.
- `agent_side/app.py`: trusted agent web UI and API.
- `agent_side/input_data.py`: parses inline data or CSV input.
- `agent_side/planner.py`: calls Azure OpenAI to produce an operation schema.
- `agent_side/preflight.py`: rejects unsupported or impractical plans before encryption.
- `agent_side/crypto.py`: creates TenSEAL contexts and encrypts/decrypts vectors.
- `agent_side/transport.py`: writes ciphertext artifacts and calls the server.
- `agent_side/reporting.py`: prints result and performance reports.
- `agent_side/result_store.py`: saves local agent-side JSON result summaries.

### Server Side

The server side is untrusted. It handles:

- FastAPI `/compute` requests.
- Read-only dashboard status monitoring.
- Public context and ciphertext loading.
- Secret-key rejection.
- Path confinement to `he_shared/`.
- Operation execution over ciphertext.
- Encrypted result writing.
- Audit logging that previews ciphertext bytes.

Important files:

- `server_side/app.py`: FastAPI app and `/compute` endpoint.
- `server_side/security.py`: shared-directory path checks and secret-key checks.
- `server_side/pipeline.py`: executes the approved operation DSL.
- `server_side/results.py`: writes encrypted result files.
- `server_side/types.py`: shared server-side result data structures.

The dashboard served by `server.py` does not collect plaintext input and does
not execute trusted agent code. It only polls `he_shared/demo_status.json` and
displays status written by the separate agent process and server compute
endpoint.

### Shared Code

`he_common/` contains non-sensitive helpers used by both sides:

- `he_common/config.py`: shared directory and server URL defaults.
- `he_common/operations.py`: operation schema validation and plaintext simulation
  used for expected-result checks on the agent side.

## 3. Data Flow

The project uses two transfer planes.

### Control Plane

The control plane is HTTP JSON. The agent sends a small request to the server:

```json
{
  "computation_type": "general_bfv",
  "scheme": "BFV",
  "context_path": ".../he_shared/<run_id>_context.bin",
  "payload_path": ".../he_shared/<run_id>_payload.bin",
  "result_path": ".../he_shared/<run_id>_result.bin",
  "params": {
    "schema_name": "salary_difference",
    "operations": [
      {"op": "sub_scalar", "value": 90000},
      {"op": "mul_scalar", "value": 2}
    ],
    "result_label": "salary difference"
  }
}
```

### Data Plane

The data plane is the local shared directory `he_shared/`.

The agent writes:

```text
he_shared/<run_id>_context.bin   Public HE context, no secret key
he_shared/<run_id>_payload.bin   Encrypted user data
```

The server writes:

```text
he_shared/<run_id>_result.bin    Encrypted result
```

`he_shared/` is ignored by git because it contains generated ciphertext
artifacts.

## 4. Privacy Boundary

The trusted boundary is:

```text
Trusted:   agent.py and agent_side/
Untrusted: server.py and server_side/
```

The agent owns:

- Plaintext user data.
- The secret key.
- The decrypted final result.

The server receives:

- Public HE context.
- Encrypted payload.
- Operation schema and public constants.

The server does not receive:

- User plaintext data.
- The secret key.
- Decrypted output.

The operation schema may include public constants such as a threshold, scale, or
polynomial coefficient. These constants are not treated as private user data in
this demo. If a future use case requires private thresholds or private
coefficients, those values must also be encrypted on the agent side.

## 5. LLM Planning Model

The LLM does not receive raw user data. The agent redacts inline values before
calling Azure OpenAI.

Example user prompt:

```text
Compare each salary to 90000 and double the difference. data=[85000, 90000, 95000]
```

Prompt sent to the LLM:

```text
Compare each salary to 90000 and double the difference. data=[REDACTED_DATA]
```

The LLM also receives non-sensitive metadata:

```json
{
  "vector_length": 3,
  "numeric_kind": "integer",
  "raw_values_shared_with_model": false
}
```

The LLM returns an operation schema. The agent validates it before sending it to
the server.

The agent also runs preflight checks before encryption. These checks reject
tasks that are not supported by the current HE pipeline, such as sorting,
median, min/max, boolean thresholding, branching, encrypted division, and
general classification models.

## 6. Operation DSL

The operation DSL is a small JSON language for HE-safe vector operations. It is
not Python code.

Allowed operations:

```text
add_scalar     x + c
sub_scalar     x - c
mul_scalar     x * c
square         x * x
polynomial     bounded polynomial from powers 1, 2, 4, 8, 16
```

The server executes only this bounded DSL. It does not execute arbitrary code
from the LLM or from the client.

The server does not contain scenario-specific plugins for salary, medical,
financial, energy, or other domains. A new scenario should not require server
code changes as long as the LLM can express it using the supported operation
schema.

### BFV

BFV is used for exact integer arithmetic.

Good fits:

- Salary offsets.
- Integer scores.
- Count-like exact values.
- Exact add/subtract/multiply-by-scalar pipelines.

Supported DSL operations:

- `add_scalar`
- `sub_scalar`
- `mul_scalar`
- `square`, with depth cost
- `polynomial`, if coefficients and results fit the plaintext modulus

### CKKS

CKKS is used for approximate real-number arithmetic.

Good fits:

- Medical risk scores.
- Weighted numeric scores.
- Floating-point values.
- Bounded-depth polynomial scoring.

Supported DSL operations:

- `add_scalar`
- `sub_scalar`
- `mul_scalar`
- `square`, with depth and approximation-error cost
- `polynomial`, with approximation error reported by the agent

## 7. Compute Flow

```text
1. User starts server.py.
2. User starts agent.py.
3. User opens the trusted agent UI on port 8081.
4. Agent reads task prompt and numeric data.
5. Agent runs early preflight checks for empty input, vector size, and payload estimate.
6. Agent redacts raw data before the LLM planner call.
7. LLM returns an operation schema.
8. Agent validates the schema.
9. Agent runs plan preflight checks for operation count and HE depth.
10. Agent selects BFV or CKKS and creates a TenSEAL context.
11. Agent encrypts the input vector locally.
12. Agent writes public context and ciphertext to he_shared/.
13. Agent sends file paths, scheme, and operations to server /compute.
14. Server verifies paths are inside he_shared/.
15. Server rejects contexts containing a secret key.
16. Server executes operations over ciphertext.
17. Server writes encrypted result to he_shared/.
18. Agent reads encrypted result and decrypts locally.
19. Agent shows decrypted samples, timings, CKKS error when applicable, and the saved result path.
```

## 8. How to Run

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the server in terminal 1:

```bash
python3 server.py
```

Optional dashboard monitor:

```text
http://127.0.0.1:8080
```

Run the agent in terminal 2:

```bash
export AZURE_OPENAI_KEY="<your-key>"
python3 agent.py
```

Open the trusted agent UI:

```text
http://127.0.0.1:8081
```

Example inline BFV prompt:

```text
Compare each salary to 90000 and double the difference. data=[85000, 90000, 95000]
```

Example CSV flow:

```text
Compare each salary to 90000 and double the difference.
```

When prompted for a CSV path:

```text
data/sample_data.csv
```

The old terminal-only agent is still available:

```bash
python3 agent.py --cli
```

Example CKKS prompt:

```text
Compute a nonlinear medical risk score using x^8 + x^4 + x^2. data=[1.05, 1.10, 1.15]
```

## 9. How to Test

### Syntax Check

```bash
python3 -m compileall agent.py server.py agent_side server_side he_common scripts
```

### End-to-End Smoke Test

This test does not require an Azure OpenAI key. It bypasses the LLM planner and
uses fixed operation schemas for BFV and CKKS.

Start the server:

```bash
python3 server.py
```

In a second terminal:

```bash
python3 scripts/smoke_test.py
```

Expected behavior:

- BFV salary-difference test decrypts exactly to `[-10000, 0, 10000]`.
- CKKS polynomial test reports a small approximation error.
- Server logs show `BLIND-EVAL` entries containing ciphertext byte previews.

### Agent Preflight Checks

Before encrypting data or calling the server, the agent checks:

- Empty input vectors.
- Very large vectors.
- Estimated ciphertext payload size.
- Too many operations.
- CKKS multiplication depth above the demo limit.
- BFV multiplication depth above the demo limit.
- Unsupported task hints such as median, sort, min/max, branching, boolean
  comparison, encrypted division, and general classification.

These checks are conservative. The server still performs its own validation and
payload-size enforcement.

### Boundary Benchmark

The boundary benchmark does not require the server:

```bash
python3 scripts/benchmark_boundary.py
```

It measures approximate operating limits such as slot capacity, payload growth,
serialization boundary, and CKKS multiplicative-depth behavior.

See `BENCHMARK.md` for the presentation-oriented benchmark summary and current
system limitations.

## 10. Current Limitations

This project is a capstone prototype, not a production HE platform.

- Inputs are limited to one numeric vector from inline data or a one-column CSV.
- The generic operation schema is element-wise; it does not support arbitrary
  table joins, multi-column feature matrices, or general dataframes.
- Supported operations are limited to scalar addition/subtraction/multiplication,
  squaring, and bounded polynomials.
- Unsupported computations include sorting, median, min/max, branching,
  boolean thresholding, encrypted division, ranking, and general classifiers.
- Salary comparison can be demonstrated as an offset or score, but exact
  encrypted greater-than/less-than comparison is not implemented.
- Financial and medical examples are polynomial scoring demos, not full ML
  fraud/risk models.
- Full multi-party federated aggregation is not implemented; the current server
  accepts one ciphertext payload per compute request.
- `he_shared/` is a local demo transport. A production system would use a
  remote object store, upload API, or message queue for ciphertext artifacts.
- CKKS results are approximate, and error grows with multiplicative depth.
- Large vectors create large ciphertext payloads and slower encryption,
  evaluation, transfer, and decryption.

## 11. Git Hygiene

Do not commit:

- `.venv/`
- `__pycache__/`
- `*.pyc`
- `.env`
- API keys
- `he_shared/`
- `agent_results/`
- `.DS_Store`
- IDE settings

These are already covered by `.gitignore`.
