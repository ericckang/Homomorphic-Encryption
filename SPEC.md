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
- Azure OpenAI table-intent parsing for CSV tasks.
- Deterministic validation for supported CSV arithmetic formulas.
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
- `agent_side/input_data.py`: parses inline/manual/CSV input, routes requests, asks the LLM for CSV table intent, and applies deterministic validation.
- `agent_side/formula_parser.py`: parses and validates supported CSV arithmetic formulas.
- `agent_side/input_models.py`: typed agent-side CSV/input structures.
- `agent_side/planner.py`: calls Azure OpenAI both for generic HE planning and for CSV table-intent parsing.
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
- Restricted rule-based multi-input formula evaluation over ciphertext.
- Encrypted result writing.
- Audit logging that previews ciphertext bytes.

Important files:

- `server_side/app.py`: FastAPI app and `/compute` endpoint.
- `server_side/security.py`: shared-directory path checks and secret-key checks.
- `server_side/pipeline.py`: executes the approved operation DSL or restricted formula tree.
- `server_side/expression_eval.py`: evaluates serialized encrypted formula trees.
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

For the restricted multi-column formula path, the request may also include
serialized expression-tree metadata and additional encrypted input file paths.

### Data Plane

The data plane is the local shared directory `he_shared/`.

The agent writes:

```text
he_shared/<run_id>_context.bin          Public HE context, no secret key
he_shared/<run_id>_payload.bin          Primary encrypted user vector
he_shared/<run_id>_input_<name>.bin     Additional encrypted input vectors for supported multi-column formulas
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
- Optional additional encrypted input vectors for supported multi-column formulas.
- Operation schema and public constants.

The server does not receive:

- User plaintext data.
- The secret key.
- Decrypted output.

The operation schema may include public constants such as a threshold, scale, or
polynomial coefficient. These constants are not treated as private user data in
this demo. If a future use case requires private thresholds or private
coefficients, those values must also be encrypted on the agent side.

## 5. LLM Planning and Validation Model

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

For generic single-vector tasks, the LLM returns an operation schema. The agent validates it before sending it to the server.

For CSV tasks, the current prototype uses a two-stage model:

1. **LLM table intent parsing**
   - The model classifies a CSV request as one of:
     - `formula`
     - `reduction`
     - `planner`
2. **Deterministic validation**
   - If the model proposes a formula, the agent validates it locally.
   - Validation checks supported operators, referenced columns, numeric-column hygiene, and known unsupported syntax.

For supported CSV arithmetic formulas such as:

```text
compute risk score = salary^2 + 5 * age + 6
```

the current prototype does not directly trust the LLM to execute semantics.
Instead, the LLM proposes intent, the agent validates the formula locally,
encrypts each referenced column separately, and sends a restricted serialized
expression tree to the server.

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
polynomial     bounded polynomial from positive integer powers
sum_reduce     sum an encrypted vector into one encrypted scalar
mean_reduce    average an encrypted vector into one encrypted scalar (CKKS only)
dot_product_public  weighted score against a public weight vector
```

The server executes only this bounded DSL for planner-driven requests. It does
not execute arbitrary code from the LLM or from the client.

In addition, the current prototype supports a restricted validated CSV formula
path. In that path, the agent validates arithmetic expressions such as
`salary^2 + 5 * age + 6`, encrypts each referenced CSV column separately, and
sends a serialized expression tree plus multiple ciphertext vectors to the
server.

### BFV

BFV is used for exact integer arithmetic.

Good fits:

- Salary offsets.
- Integer scores.
- Count-like exact values.
- Exact add/subtract/multiply-by-scalar pipelines.
- Integer sum reductions.

Supported DSL operations:

- `add_scalar`
- `sub_scalar`
- `mul_scalar`
- `square`, with depth cost
- `polynomial`, if coefficients and results fit the plaintext modulus
- `sum_reduce`

### CKKS

CKKS is used for approximate real-number arithmetic.

Good fits:

- Medical risk scores.
- Weighted numeric scores.
- Floating-point values.
- Bounded-depth polynomial scoring.
- Weighted averages and vector-to-scalar reductions.
- Restricted multi-column encrypted arithmetic formulas over CSV numeric columns.

Supported DSL operations:

- `add_scalar`
- `sub_scalar`
- `mul_scalar`
- `square`, with depth and approximation-error cost
- `polynomial`, with approximation error reported by the agent
- `sum_reduce`
- `mean_reduce`
- `dot_product_public`

Supported restricted multi-column formula operators:

- numeric variables bound to CSV columns
- numeric constants
- `+`
- `-`
- `*`
- positive integer powers via `^`

## 7. Request Paths and Compute Flow

There are three important request families in the current architecture.

### A. Generic planner path
- Input is a vector or a single chosen CSV numeric column.
- Azure OpenAI returns the bounded HE DSL.
- The server executes `operations`.

### B. Validated CSV formula path
- Input is a CSV with one or more referenced numeric columns.
- Azure OpenAI first proposes a table intent.
- The trusted agent validates the formula locally.
- The server executes a restricted serialized formula tree over ciphertext.

### C. Rejected path
- Unknown columns, unsupported syntax, missing data, and malformed CSV input should be rejected on the trusted side before compute.

### Detailed compute flow

```text
1. User starts server.py.
2. User starts agent.py.
3. User opens the trusted agent UI on port 8081.
4. Agent reads task prompt and numeric data.
5. Agent runs early preflight checks for empty input, vector size, and payload estimate.
6. If the request is a normal single-vector task, the agent redacts raw data before the LLM planner call.
7. If the request is a CSV task, the agent may first ask the LLM for table intent classification.
8. If the request is a supported CSV arithmetic formula, the trusted agent validates the formula locally.
9. Agent validates the schema or formula tree.
10. Agent runs plan/depth checks.
11. Agent selects BFV or CKKS and creates a TenSEAL context.
12. Agent encrypts the input vector locally.
13. For supported formula requests, the agent also encrypts each referenced CSV numeric column separately.
14. Agent writes public context and ciphertext artifacts to he_shared/.
15. Agent sends file paths, scheme, and operations or formula tree to server /compute.
16. Server verifies paths are inside he_shared/.
17. Server rejects contexts containing a secret key.
18. Server executes the approved DSL or the restricted formula tree over ciphertext.
19. Server writes encrypted result to he_shared/.
20. Agent reads encrypted result and decrypts locally.
21. Agent shows decrypted samples, timings, CKKS error when applicable, and the saved result path.
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

Example inline BFV reduction prompt:

```text
Sum all salary into a scalar. data=[100, 90000, 95000]
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

Example CKKS weighted-score prompt:

```text
Compute a weighted risk score with weights [0.2, 0.3, 0.5]. data=[1.0, 2.0, 3.0]
```

Example supported CSV encrypted formula:

```text
compute risk score = salary^2 + 5 * age + 6
```

Another natural-language style that should map into the same validated formula path is:

```text
Compute risk score salary * 3 + age
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
- BFV sum-reduction test decrypts exactly to `185100`.
- CKKS polynomial and reduction tests report small approximation error.
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
- Unsupported formula syntax such as `/`, `>`, `<`, `log(...)`, and `if ... else`.
- Missing web input data when no CSV, manual values, or inline vector is provided.
- CSV hygiene errors such as blank rows, mismatched row widths, missing numeric
  values, non-numeric values in numeric columns, and unnamed headers.

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

- Inputs support one encrypted vector for the generic planner-driven DSL, plus a restricted validated CSV formula path for arithmetic formulas.
- The generic operation schema still centers on one primary encrypted vector per request plus an
  optional final vector-to-scalar reduction; it does not yet support arbitrary table
  joins, planner-driven multi-input encrypted DAGs, multi-column encrypted feature matrices, or general dataframes.
- Supported operations are limited to scalar addition/subtraction/multiplication,
  squaring, bounded polynomials, encrypted sums, encrypted means, public-weight
  dot products, and restricted multi-column encrypted arithmetic formulas with only numeric columns, constants, `+`, `-`, `*`, and integer powers.
- Unsupported computations include sorting, median, min/max, branching,
  boolean thresholding, encrypted division, ranking, general classifiers, function calls, and general planner-produced multi-input formulas.
- Salary comparison can be demonstrated as an offset or score, but exact
  encrypted greater-than/less-than comparison is not implemented.
- Financial and medical examples are polynomial scoring demos, not full ML
  fraud/risk models.
- Full multi-party federated aggregation is not implemented; the current server
  accepts one primary ciphertext payload per compute request, with optional extra
  ciphertext inputs only for the restricted formula path.
- LLM intent parsing can still be imperfect, so the architecture depends on deterministic validation on the trusted side to reject unsupported or hallucinated formula requests.
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
