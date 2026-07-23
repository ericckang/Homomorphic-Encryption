# Architecture Guide

## 1. High-level goal

This project demonstrates a trusted-agent / untrusted-server homomorphic encryption architecture.

The main idea is:

```text
plaintext data stays on the trusted agent
ciphertext is sent to the untrusted server
the server computes on ciphertext without decrypting
only the trusted agent decrypts the result
```

## 2. Trust boundary

```text
Trusted:
- agent.py
- agent_side/
- local plaintext input
- secret key
- decrypted result

Untrusted:
- server.py
- server_side/
- ciphertext payloads
- public context only
- encrypted result files
```

This is the most important architectural boundary in the repo.

## 3. Main runtime paths

There are three major request paths.

### A. Generic planner path

Used for requests such as:
- compare values to a threshold
- apply a polynomial to one vector
- sum a column
- mean of a column
- dot product with public weights

Flow:
1. Agent parses prompt and local input.
2. Agent sends only redacted prompt text plus metadata to Azure OpenAI.
3. Azure OpenAI returns a bounded HE operation schema.
4. Agent validates and sanitizes the schema.
5. Agent encrypts one primary vector.
6. Server executes the generic operation DSL.
7. Agent decrypts and reports.

### B. Validated CSV formula path

Used for requests such as:
- `Compute risk score salary * 3 + age`
- `Use salary^2 + 5 * age + 6 as the risk score`
- `Compute score salary * 2 + 3`

Flow:
1. Agent loads CSV locally.
2. Agent asks Azure OpenAI for table intent.
3. If the intent is `formula`, deterministic code validates the formula.
4. Agent encrypts each referenced numeric column separately.
5. Server evaluates the serialized formula AST over ciphertext.
6. Agent decrypts and reports.

### C. Rejected path

Used for requests that should never reach server compute, such as:
- missing input data
- malformed CSV rows
- unknown CSV columns
- unsupported formula syntax like `/`, `>`, `log(...)`, or `if ... else`

These are blocked on the trusted side.

## 4. End-to-end sequence

```text
User
  -> agent_side/app.py
  -> agent_side/input_data.py
  -> agent_side/planner.py and/or agent_side/formula_parser.py
  -> agent_side/runner.py
  -> agent_side/crypto.py
  -> agent_side/transport.py
  -> server_side/app.py
  -> server_side/pipeline.py / server_side/expression_eval.py
  -> server_side/results.py
  -> agent_side/runner.py
  -> agent_side/reporting.py
  -> dashboard JSON / UI
```

## 5. Key files by responsibility

## Entry points

- `agent.py`
  - starts the trusted agent UI by default
  - CLI mode available with `--cli`

- `server.py`
  - starts the untrusted compute server

## Trusted agent modules

- `agent_side/app.py`
  - FastAPI app for the trusted dashboard
  - validates missing prompt/data in web requests
  - returns decrypted result summaries to the frontend

- `agent_side/input_data.py`
  - parses inline vectors, manual values, and CSV files
  - detects request type
  - calls LLM table intent parsing for CSV tasks
  - runs deterministic validation for formula requests

- `agent_side/planner.py`
  - Azure OpenAI integration
  - generic HE planner
  - CSV table-intent parser

- `agent_side/formula_parser.py`
  - deterministic formula parsing and validation
  - supports numeric constants, variables, `+`, `-`, `*`, `^`
  - rejects unsupported syntax

- `agent_side/runner.py`
  - central orchestration logic
  - decides planner path vs formula path
  - builds encrypted operands/inputs
  - calls transport
  - decrypts result
  - builds final summary

- `agent_side/crypto.py`
  - creates TenSEAL BFV/CKKS contexts
  - encrypts vectors and scalar operands
  - decrypts result ciphertexts

- `agent_side/transport.py`
  - writes artifacts into `he_shared/`
  - sends the control-plane JSON request to `/compute`

- `agent_side/reporting.py`
  - builds output preview rows
  - computes error summaries for CKKS/BFV
  - prepares result JSON for UI

## Untrusted server modules

- `server_side/app.py`
  - FastAPI app and `/compute`
  - request auditing
  - demo-status updates
  - dashboard rendering

- `server_side/security.py`
  - validates all artifact paths stay within `he_shared/`
  - rejects contexts containing a secret key

- `server_side/pipeline.py`
  - executes generic HE DSL operations
  - loads encrypted operands
  - materializes encrypted constants for formula evaluation

- `server_side/expression_eval.py`
  - evaluates serialized formula ASTs on ciphertext
  - supports variables, constants, encrypted constants, add/sub/mul/pow/neg

- `server_side/results.py`
  - writes encrypted result files

## Shared modules

- `he_common/operations.py`
  - shared schema validation
  - plaintext simulation for expected outputs
  - server display formula helpers

- `he_common/demo_state.py`
  - shared dashboard state store

- `he_common/config.py`
  - shared config defaults

## 6. Data transport model

The system uses two planes.

### Control plane

Small JSON request over HTTP.

Contains:
- computation type
- scheme
- file paths
- operations or formula metadata
- server display metadata

### Data plane

Binary artifacts written to `he_shared/`.

Examples:
- context file
- encrypted primary vector
- encrypted extra formula inputs
- encrypted scalar operands
- encrypted result

This avoids very large ciphertext payloads being sent directly in the HTTP body.

## 7. Why both LLM and deterministic validation are used

The current architecture intentionally combines both.

### LLM is used for
- understanding natural-language requests
- generic HE planning
- CSV table intent parsing

### Deterministic code is used for
- formula AST validation
- supported-operator enforcement
- unknown-column rejection
- CSV hygiene checks
- multiplicative-depth checks
- server-safe execution constraints

This design prevents the untrusted server from executing arbitrary model output.

## 8. What the dashboards mean

### Agent dashboard

Should show things only the trusted side can know:
- decrypted output
- expected plaintext output
- sample input preview
- local timing and saved-result path

### Server dashboard

Should show only what the untrusted side can know:
- ciphertext payload size
- ciphertext hex preview
- scheme/computation type
- encrypted input count
- encrypted constant count
- server-visible formula string
- evaluation time

## 9. Common debugging workflow

If something goes wrong, first ask: which path did the request take?

### If it is a planner-path bug
Check:
- `agent_side/input_data.py`
- `agent_side/planner.py`
- `agent_side/runner.py`
- `he_common/operations.py`

### If it is a formula-path bug
Check:
- `agent_side/input_data.py`
- `agent_side/formula_parser.py`
- `agent_side/runner.py`
- `server_side/expression_eval.py`
- `server_side/pipeline.py`

### If it is a UI/debug-display bug
Check:
- `agent_side/app.py`
- `agent_side/reporting.py`
- `server_side/app.py`

### If it is an HE/runtime issue
Check:
- `agent_side/crypto.py`
- `agent_side/runner.py`
- `server_side/pipeline.py`

## 10. Current architectural limitations

- Generic planner path still centers on one primary encrypted vector.
- Multi-column encrypted compute is currently limited to the validated formula path.
- Unsupported operations include division, comparison, sorting, branching, function calls, and general conditionals.
- CKKS is approximate and error grows with multiplicative depth.
- The shared-directory transport is a local demo mechanism, not a production deployment pattern.
