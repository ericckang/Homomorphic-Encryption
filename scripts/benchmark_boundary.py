"""
Boundary benchmark for the HE compute system.

Empirically locates the three operating limits of the encrypted-compute pipeline:

  1. Slot capacity  — SOFT: TenSEAL auto-splits into multiple ciphertexts when
     batch > slots (payload grows linearly; matmul/rotation ops get disabled).
  2. ~2 GB serialization ceiling — HARD: the server refuses payloads above
     HE_MAX_PAYLOAD_BYTES (1.9 GB). Reported as max batch per config.
  3. Multiplicative depth — HARD: each CKKS multiply consumes one modulus level;
     exceeding the chain throws "scale out of bounds". This is the binding limit
     for useful computation.

Run:  python scripts/benchmark_boundary.py    (no server required)
"""
import tenseal as ts
import gc

HARD_2GB = 1_900_000_000  # mirrors the server's HE_MAX_PAYLOAD_BYTES guard


def bfv_ctx(deg):
    c = ts.context(ts.SCHEME_TYPE.BFV, poly_modulus_degree=deg, plain_modulus=1032193)
    c.generate_relin_keys()
    return c


def ckks_ctx(deg, coeff):
    c = ts.context(ts.SCHEME_TYPE.CKKS, poly_modulus_degree=deg, coeff_mod_bit_sizes=coeff)
    c.global_scale = 2 ** 40
    c.generate_relin_keys()
    return c


def payload_bytes(scheme, ctx, batch):
    if scheme == "BFV":
        v = ts.bfv_vector(ctx, [85000 + i for i in range(batch)])
    else:
        v = ts.ckks_vector(ctx, [1.05 + i * 1e-4 for i in range(batch)])
    return len(v.serialize())


def boundary_1_slots():
    print("### BOUNDARY 1 — Slot capacity is SOFT, not a crash")
    print("TenSEAL auto-splits when batch > slots (payload grows linearly).\n")
    print(f"{'config':28} {'slots':>7} {'batch':>7} {'payload_MB':>11}")
    for name, scheme, ctx, slots in [
        ("BFV deg=8192", "BFV", bfv_ctx(8192), 8192),
        ("CKKS deg=16384", "CKKS", ckks_ctx(16384, [60, 40, 40, 40, 40, 60]), 8192),
    ]:
        for batch in [slots, slots * 2, slots * 4]:
            mb = payload_bytes(scheme, ctx, batch) / 1024 / 1024
            print(f"{name:28} {slots:>7} {batch:>7} {mb:>11.2f}")
        del ctx
        gc.collect()


def boundary_2_serialization():
    print("\n### BOUNDARY 2 — Hard ~2GB serialization ceiling (bytes/element -> max batch)")
    print("Server refuses payloads above 1.90 GB (HE_MAX_PAYLOAD_BYTES).\n")
    print(f"{'config':28} {'bytes/elem':>11} {'max batch @1.9GB':>17}")
    for name, scheme, ctx in [
        ("BFV deg=8192", "BFV", bfv_ctx(8192)),
        ("CKKS deg=16384", "CKKS", ckks_ctx(16384, [60, 40, 40, 40, 40, 60])),
        ("CKKS deg=32768", "CKKS", ckks_ctx(32768, [60, 40, 40, 40, 40, 40, 60])),
    ]:
        b1 = payload_bytes(scheme, ctx, 10000)
        b2 = payload_bytes(scheme, ctx, 50000)
        per = (b2 - b1) / 40000  # marginal bytes per element
        max_batch = int(HARD_2GB / per)
        print(f"{name:28} {per:>11.1f} {max_batch:>17,}")
        del ctx
        gc.collect()


def boundary_3_context_size():
    print("\n### BOUNDARY 3 — Context size vs poly_modulus_degree (degree-valid chains)")
    print(f"{'degree':>7} {'chain (bits)':>16} {'context_MB':>11}")
    for deg, coeff in [(4096, [40, 28, 40]), (8192, [50, 30, 30, 50]),
                       (16384, [60, 40, 40, 40, 40, 60]), (32768, [60, 40, 40, 40, 40, 40, 60])]:
        ctx = ckks_ctx(deg, coeff)
        cmb = len(ctx.serialize(save_secret_key=False)) / 1024 / 1024
        print(f"{deg:>7} {sum(coeff):>11} bits {cmb:>11.2f}")
        del ctx
        gc.collect()


def boundary_4_depth():
    print("\n### BOUNDARY 4 — CKKS multiplicative-DEPTH limit (square until modulus exhausts)")
    print("Each square consumes one level; error compounds, then the op throws.\n")
    for name, deg, coeff in [
        ("medical_risk chain  deg=16384 [60,40x4,60]", 16384, [60, 40, 40, 40, 40, 60]),
        ("error_scaling chain deg=32768 [60,40x5,60]", 32768, [60, 40, 40, 40, 40, 40, 60]),
    ]:
        print(name)
        ctx = ckks_ctx(deg, coeff)
        cur = ts.ckks_vector(ctx, [1.05])
        exact = 1.05
        depth = 0
        print(f"  {'depth':>5} {'x^(2^d)':>9} {'exact':>14} {'HE':>14} {'abs_error':>12}")
        while True:
            try:
                cur = cur.square()
                depth += 1
                exact = exact ** 2
                he = cur.decrypt()[0]
                print(f"  {depth:>5} {2 ** depth:>9} {exact:>14.4f} {he:>14.4f} {abs(exact - he):>12.4f}")
            except Exception as e:
                print(f"  -> LIMIT reached: depth {depth + 1} fails: {str(e).splitlines()[0][:55]}\n")
                break
        del ctx
        gc.collect()


if __name__ == "__main__":
    boundary_1_slots()
    boundary_2_serialization()
    boundary_3_context_size()
    boundary_4_depth()
