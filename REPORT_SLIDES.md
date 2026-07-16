# Homomorphic Encryption Agent Architecture

- Goal: compute on private numeric data without exposing plaintext to the compute service
- Trusted side: agent holds plaintext, secret key, local encryption, local decryption
- Untrusted side: server receives only public context, ciphertext, and bounded operation schema
- Privacy claim: the server never receives plaintext data or a secret key

---

# Two-Process System Design

- Agent UI on `:8081`
  - accepts task prompt, manual values, or CSV
  - runs preflight checks before planning or upload
  - encrypts locally and decrypts locally
- Compute server on `:8080`
  - receives file paths plus operation schema
  - loads ciphertext from `he_shared/`
  - evaluates on ciphertext only
- Shared state
  - control plane: REST JSON
  - data plane: binary artifacts in `he_shared/`

---

# End-to-End Flow

1. User enters task prompt and numeric input on the trusted agent UI
2. Agent runs local preflight checks for input size, payload estimate, and unsupported tasks
3. Agent redacts raw values before the Azure OpenAI planner call
4. Planner returns a bounded HE operation schema
5. Agent validates the plan and chooses BFV or CKKS
6. Agent encrypts the input vector locally
7. Server evaluates the schema over ciphertext and writes encrypted output
8. Agent decrypts locally, shows results and benchmarks, and saves a JSON summary

---

# Execution Model

- Supported schemes
  - BFV: exact integer arithmetic
  - CKKS: approximate real-number arithmetic
- Supported operations
  - `add_scalar`
  - `sub_scalar`
  - `mul_scalar`
  - `square`
  - bounded `polynomial` with powers `1, 2, 4, 8, 16`
- Safety constraint
  - server executes only a bounded DSL, not arbitrary code

---

# Benchmark Methodology

- Script: `python3 scripts/benchmark_boundary.py`
- No server required; runs local TenSEAL measurements
- What it measures
  - slot-capacity boundary
  - payload growth
  - ~1.9 GB serialization boundary
  - context size vs parameter size
  - CKKS multiplicative-depth limit
  - runtime scaling for representative BFV and CKKS workloads

---

# Runtime Scaling Results

**BFV workload:** `(x - 90000) * 2`

| Batch | Payload MB | Encrypt s | Eval s | Decrypt s |
|------:|-----------:|----------:|-------:|----------:|
| 16 | 0.08 | 0.0008 | 0.0002 | 0.0002 |
| 4,096 | 0.08 | 0.0011 | 0.0004 | 0.0002 |
| 8,192 | 0.41 | 0.0026 | 0.0007 | 0.0008 |

**CKKS workload:** `0.0001*x^2 + 0.01*x`

| Batch | Payload MB | Encrypt s | Eval s | Decrypt s | Max Error |
|------:|-----------:|----------:|-------:|----------:|----------:|
| 16 | 1.00 | 0.0062 | 0.0096 | 0.0016 | 0.000001 |
| 1,024 | 1.01 | 0.0065 | 0.0095 | 0.0015 | 0.000132 |
| 4,096 | 1.01 | 0.0067 | 0.0096 | 0.0015 | 0.000132 |

---

# Operating Limits

- Slot capacity is a soft boundary
  - payload grows after ciphertext packing capacity is exceeded
- Serialization is a hard boundary
  - server rejects payloads above `1.9 GB`
- CKKS depth is the main practical limit
  - degree `16384` chain: success at depth `4`, fails at depth `5`
  - degree `32768` chain: success at depth `5`, fails at depth `6`
- Larger `poly_modulus_degree` increases context size
  - `4096`: `0.39 MB`
  - `16384`: `7.54 MB`
  - `32768`: `20.22 MB`

---

# Current System Limitations

- Input is limited to one numeric vector, not matrices or general dataframes
- Computation is element-wise, not general analytics or arbitrary ML inference
- Unsupported tasks: sorting, median, min/max, branching, encrypted division, ranking, general classifiers
- Salary comparison is implemented as offset or score, not true encrypted boolean comparison
- Medical and financial examples are polynomial scoring demos, not production models
- Full multi-party federated aggregation is not implemented
- `he_shared/` is a local demo transport, not a production remote-storage architecture
- CKKS is approximate and error grows with multiplicative depth
