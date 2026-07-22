from __future__ import annotations

import tenseal as ts


BFV_BATCHING_DEGREES = (4096, 8192, 16384, 32768)
BFV_BATCHING_PLAIN_MODULUS = {
    4096: 1032193,
    8192: 1032193,
    16384: 786433,
    32768: 786433,
}


def make_context(scheme: str, vector_size: int, depth: int):
    if scheme == "BFV":
        required_degree = next((degree for degree in BFV_BATCHING_DEGREES if vector_size <= degree), 32768)
        for poly_mod_degree in BFV_BATCHING_DEGREES:
            if poly_mod_degree < required_degree:
                continue
            plain_modulus = BFV_BATCHING_PLAIN_MODULUS[poly_mod_degree]
            try:
                context = ts.context(
                    ts.SCHEME_TYPE.BFV,
                    poly_modulus_degree=poly_mod_degree,
                    plain_modulus=plain_modulus,
                )
                context.generate_relin_keys()
                context.generate_galois_keys()
                ts.bfv_vector(context, [1, 2, 3, 4])
                return context, poly_mod_degree
            except ValueError as exc:
                if "batching" not in str(exc).lower():
                    raise
        raise ValueError("Unable to create a BFV batching context for the requested vector size.")

    poly_mod_degree = 16384 if depth <= 4 else 32768
    coeff_mod_bit_sizes = [60] + [40] * max(depth + 2, 3) + [60]
    context = ts.context(
        ts.SCHEME_TYPE.CKKS,
        poly_modulus_degree=poly_mod_degree,
        coeff_mod_bit_sizes=coeff_mod_bit_sizes,
    )
    context.global_scale = 2**40
    context.generate_relin_keys()
    context.generate_galois_keys()
    return context, poly_mod_degree


def encrypt_vector(context, scheme: str, data: list[float]):
    if scheme == "BFV":
        return ts.bfv_vector(context, [int(x) for x in data])
    return ts.ckks_vector(context, data)


def decrypt_vector(context, scheme: str, raw: bytes) -> list[float]:
    if scheme == "BFV":
        return ts.bfv_vector_from(context, raw).decrypt()
    return ts.ckks_vector_from(context, raw).decrypt()


def encrypt_scalar_operand(context, scheme: str, value: float, vector_size: int):
    repeated = [int(value)] * vector_size if scheme == "BFV" else [float(value)] * vector_size
    return encrypt_vector(context, scheme, repeated)
