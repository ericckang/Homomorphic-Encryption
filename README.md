# Homomorphic Encryption — Blind-Evaluator Compute Service

A demonstration of **secure outsourced computation** using homomorphic encryption (HE).
An untrusted compute server runs real math on encrypted data **without ever being able
to decrypt it**, and proves it from its own logs.

This repo is the server/transport + compute half of a larger
"Generalizable HE Agent Architecture."

## Architecture

| Component | File | Role |
|-----------|------|------|
| **Blind-evaluator server** | `server.py` | Untrusted FastAPI compute node. Operates entirely on ciphertext; holds no secret key and refuses any context that carries one. Plugin-based: each scenario is one isolated class. |
| **Agent / client** | `agent.py` | Trusted client. Generates keys, encrypts the input, calls the server, and is the only party that can decrypt the result. Includes benchmark scenarios. |
| **Chat client** | `chat_agent.py` | Standalone Azure OpenAI chat loop (LLM-orchestration prototype). |

**Two planes:**
- **Control plane** — lightweight JSON instructions over REST (`computation_type`, paths, params).
- **Data plane** — heavy binary blobs (the public crypto context + ciphertext payloads)
  exchanged via a shared directory (`./he_shared`), bypassing HTTP body-size limits.

### Compute scenarios (server plugins)

| `computation_type` | Scheme | Operation |
|--------------------|--------|-----------|
| `salary_benchmark` | BFV (exact integers) | element-wise `(x - median) * scale` |
| `medical_risk` | CKKS (approx. reals) | depth-3 polynomial `x^8 + x^4 + x^2` |
| `ckks_error_scaling` | CKKS | iterative squaring, one ciphertext per depth (charts error vs. multiplicative depth) |

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

The server is meaningless on its own — the agent generates the keys and ciphertext.
Run them in **two terminals**.

**Terminal 1 — the untrusted server:**
```bash
python server.py
# serves http://127.0.0.1:8080  (docs at /docs)
```
On boot it logs `This node holds NO secret key and cannot decrypt any payload.`
and registers the three plugins.

**Terminal 2 — the client / benchmark suite:**
```bash
python agent.py
# enter a batch size when prompted (e.g. 100, 4000)
```
The agent runs all three scenarios and prints benchmark reports. Watch the **server**
terminal: every request logs a `BLIND-EVAL` line with the ciphertext size and a hex
preview — the proof that the server only ever sees gibberish.

### Configuration

The server reads optional environment variables (all have defaults):

| Variable | Default | Meaning |
|----------|---------|---------|
| `HE_SHARED_DIR` | `./he_shared` | shared data-plane directory |
| `HE_HOST` / `HE_PORT` | `127.0.0.1` / `8080` | bind address |
| `HE_MAX_PAYLOAD_BYTES` | `1900000000` | reject payloads near TenSEAL's ~2 GiB serialization ceiling |

### Chat client

`chat_agent.py` reads its key from the environment — set it before running:

```bash
export AZURE_OPENAI_KEY="<your-key>"
python chat_agent.py
```

## Notes on HE parameters

- **BFV** gives exact integer results; **CKKS** gives approximate real results, and the
  approximation error grows with multiplicative depth (see `ckks_error_scaling`).
- `poly_modulus_degree` sets both security and capacity: larger degree = more
  multiplicative depth and more SIMD slots, but quadratically larger/slower ciphertexts.
  A ciphertext holds at most `degree` (BFV) or `degree/2` (CKKS) values per request.
- Galois keys are intentionally omitted (no slot rotations are used) to keep contexts small.
