from __future__ import annotations

import tenseal as ts


def make_context(scheme: str, vector_size: int, depth: int):
    if scheme == "BFV":
        poly_mod_degree = 4096 if vector_size <= 4096 else 8192
        context = ts.context(
            ts.SCHEME_TYPE.BFV,
            poly_modulus_degree=poly_mod_degree,
            plain_modulus=1032193,
        )
        context.generate_relin_keys()
        context.generate_galois_keys()
        return context, poly_mod_degree

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
