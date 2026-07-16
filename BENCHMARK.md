# Homomorphic Encryption Benchmark Summary

This document summarizes the benchmark results used for the capstone demo. The
numbers were measured locally with:

```bash
python scripts/benchmark_boundary.py
```

The goal is not to claim production performance. The goal is to show where this
HE prototype works, where cost grows, and which limits are hard constraints.

## 1. Main Takeaways

- HE computation is practical for small demo vectors and bounded arithmetic.
- BFV is fast and exact for integer scalar arithmetic.
- CKKS supports real-number scoring, but results are approximate.
- Data size does not grow linearly inside one ciphertext slot capacity because
  BFV/CKKS use batching/SIMD-style packing.
- Once vector length exceeds slot capacity, TenSEAL auto-splits into multiple
  ciphertexts and payload size grows roughly linearly.
- Multiplicative depth is the most important hard limit for CKKS polynomial
  scoring. Too many chained multiplications eventually fail.
- The server rejects very large payloads before TenSEAL's approximate 2 GB
  serialization boundary.

## 2. Data Size vs Runtime

Representative BFV workload:

```text
(x - 90000) * 2
```

This is an exact integer salary-offset style workload.

| Batch Size | Payload MB | Encrypt Sec | Eval Sec | Decrypt Sec |
|-----------:|-----------:|------------:|---------:|------------:|
| 16 | 0.08 | 0.0008 | 0.0002 | 0.0002 |
| 128 | 0.08 | 0.0008 | 0.0001 | 0.0002 |
| 1,024 | 0.08 | 0.0008 | 0.0002 | 0.0002 |
| 4,096 | 0.08 | 0.0011 | 0.0004 | 0.0002 |
| 8,192 | 0.41 | 0.0026 | 0.0007 | 0.0008 |

Interpretation: BFV is very efficient for this demo workload. The first several
batch sizes fit inside one ciphertext capacity, so payload size and runtime stay
nearly flat. At 8,192 values, the parameter choice changes and payload grows.

Representative CKKS workload:

```text
0.0001*x^2 + 0.01*x
```

This is an approximate real-number financial risk scoring style workload.

| Batch Size | Payload MB | Encrypt Sec | Eval Sec | Decrypt Sec | Max Error |
|-----------:|-----------:|------------:|---------:|------------:|----------:|
| 16 | 1.00 | 0.0062 | 0.0096 | 0.0016 | 0.000001 |
| 128 | 1.00 | 0.0063 | 0.0095 | 0.0015 | 0.000004 |
| 1,024 | 1.01 | 0.0065 | 0.0095 | 0.0015 | 0.000132 |
| 4,096 | 1.01 | 0.0067 | 0.0096 | 0.0015 | 0.000132 |

Interpretation: CKKS has a higher fixed cost than BFV because it supports
approximate real-number arithmetic and deeper polynomial parameters. Within
slot capacity, increasing the vector size has little runtime impact. The error
stays small for this shallow polynomial.

## 3. Slot Capacity and Payload Growth

TenSEAL packs many values into one ciphertext. The slot capacity is a soft
boundary: exceeding it does not crash, but TenSEAL splits the input across
multiple ciphertexts and disables operations that require a single ciphertext.

| Config | Slots | Batch | Payload MB |
|--------|------:|------:|-----------:|
| BFV degree 8192 | 8,192 | 8,192 | 0.41 |
| BFV degree 8192 | 8,192 | 16,384 | 0.82 |
| BFV degree 8192 | 8,192 | 32,768 | 1.65 |
| CKKS degree 16384 | 8,192 | 8,192 | 1.00 |
| CKKS degree 16384 | 8,192 | 16,384 | 2.01 |
| CKKS degree 16384 | 8,192 | 32,768 | 4.02 |

Interpretation: after slot capacity is exceeded, payload size roughly doubles
when the batch size doubles.

## 4. Serialization Boundary

The server enforces:

```text
HE_MAX_PAYLOAD_BYTES = 1,900,000,000
```

This prevents requests near TenSEAL's approximate 2 GB serialization ceiling.

| Config | Approx Bytes Per Element | Approx Max Batch at 1.9 GB |
|--------|-------------------------:|----------------------------:|
| BFV degree 8192 | 54.1 | 35,150,181 |
| CKKS degree 16384 | 131.7 | 14,427,507 |
| CKKS degree 32768 | 187.8 | 10,118,635 |

Interpretation: the hard payload limit is large compared with the live demo
sizes, but it matters for realistic datasets. The agent preflight estimates
payload size before encrypting.

## 5. Context Size Cost

Increasing `poly_modulus_degree` gives more capacity/depth but increases context
size.

| Degree | Coefficient Chain Bits | Public Context MB |
|-------:|-----------------------:|------------------:|
| 4,096 | 108 | 0.39 |
| 8,192 | 160 | 1.47 |
| 16,384 | 280 | 7.54 |
| 32,768 | 320 | 20.22 |

Interpretation: deeper CKKS workloads require larger parameters. That makes the
public context heavier before any data is encrypted.

## 6. CKKS Multiplicative Depth

CKKS consumes one level with each ciphertext multiplication. The benchmark
repeatedly squares `1.05`.

| Config | Successful Depth | Failing Depth | Observed Error Near Limit |
|--------|-----------------:|--------------:|--------------------------:|
| CKKS degree 16384, `[60, 40, 40, 40, 40, 60]` | 4 | 5 | about 0.0001 |
| CKKS degree 32768, `[60, 40, 40, 40, 40, 40, 60]` | 5 | 6 | about 0.0004 |

Interpretation: CKKS can handle shallow polynomial scoring well, but deep
polynomials fail when the modulus chain is exhausted. This is why the agent
preflight rejects overly deep plans.

## 7. Current System Limits

The current system is intentionally bounded so that generalization stays safe
and explainable.

- Input format is one numeric vector, either inline or from a one-column CSV.
- Server computation is element-wise over encrypted vectors.
- Supported operations are `add_scalar`, `sub_scalar`, `mul_scalar`, `square`,
  and bounded `polynomial`.
- BFV supports exact integer arithmetic but not real numbers.
- CKKS supports real-number arithmetic but only approximately.
- Unsupported tasks include sorting, median, min/max, encrypted comparison,
  branching, encrypted division, ranking, and arbitrary classifiers.
- Salary comparison is represented as salary offset or scoring, not a true
  encrypted greater-than boolean.
- Medical/financial examples are polynomial scoring demos, not full ML models.
- Full multi-institution federated aggregation is not implemented yet; the
  current `/compute` endpoint accepts one ciphertext payload per request.
- The local `he_shared/` directory is a demo transport layer, not a production
  remote storage layer.

## 8. How to Present This

Suggested short explanation:

```text
The benchmark shows that HE cost is dominated by scheme choice, parameter size,
slot capacity, and multiplication depth. Small vector demos run quickly because
many values are packed into one ciphertext. Payload size grows once we exceed
slot capacity, and CKKS polynomial depth is the main hard limit because each
multiplication consumes part of the modulus chain. Our agent checks these limits
before sending work to the server.
```

