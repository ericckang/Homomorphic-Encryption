"""
Structured benchmark runner for the HE compute prototype.

This version keeps the original boundary-style measurements, but also writes
machine-readable outputs and generates presentation-ready plots.

Run:
  ./.venv/bin/python scripts/benchmark_boundary.py
"""
from __future__ import annotations

import csv
import gc
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import tenseal as ts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "benchmark_results"
RUNTIME_CSV = OUTPUT_DIR / "boundary_runtime_scaling.csv"
SLOTS_CSV = OUTPUT_DIR / "boundary_slot_capacity.csv"
SERIALIZATION_CSV = OUTPUT_DIR / "boundary_serialization_limit.csv"
CONTEXT_CSV = OUTPUT_DIR / "boundary_context_size.csv"
DEPTH_CSV = OUTPUT_DIR / "boundary_ckks_depth.csv"
SUMMARY_JSON = OUTPUT_DIR / "boundary_summary.json"

HARD_2GB = 1_900_000_000
RUNTIME_REPEATS = 3
BFV_BATCHES = [16, 64, 256, 1024, 4096, 8192]
CKKS_BATCHES = [16, 64, 256, 1024, 4096, 8192]


def bfv_ctx(deg: int):
    context = ts.context(ts.SCHEME_TYPE.BFV, poly_modulus_degree=deg, plain_modulus=1032193)
    context.generate_relin_keys()
    context.generate_galois_keys()
    return context


def ckks_ctx(deg: int, coeff: list[int]):
    context = ts.context(ts.SCHEME_TYPE.CKKS, poly_modulus_degree=deg, coeff_mod_bit_sizes=coeff)
    context.global_scale = 2**40
    context.generate_relin_keys()
    context.generate_galois_keys()
    return context


def payload_bytes(scheme: str, ctx, batch: int) -> int:
    if scheme == "BFV":
        vector = ts.bfv_vector(ctx, [85000 + i for i in range(batch)])
    else:
        vector = ts.ckks_vector(ctx, [1.05 + i * 1e-4 for i in range(batch)])
    return len(vector.serialize())


def degree_for_bfv_batch(batch: int) -> int:
    return 4096 if batch <= 4096 else 8192


def build_ckks_runtime_context():
    return ckks_ctx(16384, [60, 40, 40, 40, 40, 60])


def benchmark_slot_capacity() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_name, scheme, ctx, slots in [
        ("BFV deg=8192", "BFV", bfv_ctx(8192), 8192),
        ("CKKS deg=16384", "CKKS", ckks_ctx(16384, [60, 40, 40, 40, 40, 60]), 8192),
    ]:
        for batch in [slots, slots * 2, slots * 4]:
            rows.append(
                {
                    "config_name": config_name,
                    "scheme": scheme,
                    "slots": slots,
                    "batch_size": batch,
                    "payload_mb": round(payload_bytes(scheme, ctx, batch) / 1024 / 1024, 4),
                }
            )
        del ctx
        gc.collect()
    return rows


def benchmark_serialization_boundary() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_name, scheme, ctx in [
        ("BFV deg=8192", "BFV", bfv_ctx(8192)),
        ("CKKS deg=16384", "CKKS", ckks_ctx(16384, [60, 40, 40, 40, 40, 60])),
        ("CKKS deg=32768", "CKKS", ckks_ctx(32768, [60, 40, 40, 40, 40, 40, 60])),
    ]:
        bytes_10k = payload_bytes(scheme, ctx, 10000)
        bytes_50k = payload_bytes(scheme, ctx, 50000)
        marginal_bytes_per_element = (bytes_50k - bytes_10k) / 40000
        rows.append(
            {
                "config_name": config_name,
                "scheme": scheme,
                "marginal_bytes_per_element": round(marginal_bytes_per_element, 4),
                "max_batch_at_1_9gb": int(HARD_2GB / marginal_bytes_per_element),
            }
        )
        del ctx
        gc.collect()
    return rows


def benchmark_context_sizes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for degree, coeff in [
        (4096, [40, 28, 40]),
        (8192, [50, 30, 30, 50]),
        (16384, [60, 40, 40, 40, 40, 60]),
        (32768, [60, 40, 40, 40, 40, 40, 60]),
    ]:
        ctx = ckks_ctx(degree, coeff)
        rows.append(
            {
                "scheme": "CKKS",
                "poly_modulus_degree": degree,
                "coeff_mod_chain_bits": sum(coeff),
                "public_context_mb": round(len(ctx.serialize(save_secret_key=False)) / 1024 / 1024, 4),
            }
        )
        del ctx
        gc.collect()
    return rows


def benchmark_ckks_depth() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_name, degree, coeff in [
        ("CKKS deg=16384 [60,40x4,60]", 16384, [60, 40, 40, 40, 40, 60]),
        ("CKKS deg=32768 [60,40x5,60]", 32768, [60, 40, 40, 40, 40, 40, 60]),
    ]:
        ctx = ckks_ctx(degree, coeff)
        encrypted = ts.ckks_vector(ctx, [1.05])
        exact = 1.05
        successful_depth = 0

        while True:
            try:
                encrypted = encrypted.square()
                successful_depth += 1
                exact = exact**2
                he_value = encrypted.decrypt()[0]
                rows.append(
                    {
                        "config_name": config_name,
                        "poly_modulus_degree": degree,
                        "depth": successful_depth,
                        "exponent": 2**successful_depth,
                        "exact_value": exact,
                        "he_value": he_value,
                        "abs_error": abs(exact - he_value),
                        "status": "ok",
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "config_name": config_name,
                        "poly_modulus_degree": degree,
                        "depth": successful_depth + 1,
                        "exponent": 2 ** (successful_depth + 1),
                        "exact_value": "",
                        "he_value": "",
                        "abs_error": "",
                        "status": f"limit: {str(exc).splitlines()[0]}",
                    }
                )
                break

        del ctx
        gc.collect()
    return rows


def benchmark_runtime_scaling() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    runtime_cases = [
        {
            "case_name": "bfv_affine",
            "scheme": "BFV",
            "batch_sizes": BFV_BATCHES,
            "error_metric": "exact_mismatches",
            "factory": lambda batch: benchmark_runtime_case(
                case_name="bfv_affine",
                scheme="BFV",
                batch=batch,
                context_builder=lambda: bfv_ctx(degree_for_bfv_batch(batch)),
                poly_modulus_degree=degree_for_bfv_batch(batch),
                data_builder=lambda n: [85000 + (i % 5000) for i in range(n)],
                evaluator=lambda encrypted, _data: (encrypted - ([90000] * batch)) * 2,
                expected_builder=lambda data: [(x - 90000) * 2 for x in data],
                error_builder=lambda expected, actual: sum(
                    int(round(e)) != int(round(a)) for e, a in zip(expected, actual)
                ),
            ),
        },
        {
            "case_name": "ckks_polynomial",
            "scheme": "CKKS",
            "batch_sizes": CKKS_BATCHES,
            "error_metric": "max_abs_error",
            "factory": lambda batch: benchmark_runtime_case(
                case_name="ckks_polynomial",
                scheme="CKKS",
                batch=batch,
                context_builder=build_ckks_runtime_context,
                poly_modulus_degree=16384,
                data_builder=lambda n: [20.0 + (i % 1000) * 0.5 for i in range(n)],
                evaluator=lambda encrypted, _data: (encrypted.square() * 0.0001) + (encrypted * 0.01),
                expected_builder=lambda data: [(x * x * 0.0001) + (x * 0.01) for x in data],
                error_builder=lambda expected, actual: max(abs(e - a) for e, a in zip(expected, actual)),
            ),
        },
        {
            "case_name": "ckks_mean_reduce",
            "scheme": "CKKS",
            "batch_sizes": CKKS_BATCHES,
            "error_metric": "abs_error",
            "factory": lambda batch: benchmark_runtime_case(
                case_name="ckks_mean_reduce",
                scheme="CKKS",
                batch=batch,
                context_builder=build_ckks_runtime_context,
                poly_modulus_degree=16384,
                data_builder=lambda n: [1.0 + (i % 200) * 0.01 for i in range(n)],
                evaluator=lambda encrypted, data: encrypted.sum() * (1.0 / len(data)),
                expected_builder=lambda data: [sum(data) / len(data)],
                error_builder=lambda expected, actual: abs(expected[0] - actual[0]),
            ),
        },
        {
            "case_name": "ckks_dot_product_public",
            "scheme": "CKKS",
            "batch_sizes": CKKS_BATCHES,
            "error_metric": "abs_error",
            "factory": lambda batch: benchmark_runtime_case(
                case_name="ckks_dot_product_public",
                scheme="CKKS",
                batch=batch,
                context_builder=build_ckks_runtime_context,
                poly_modulus_degree=16384,
                data_builder=lambda n: [1.0 + (i % 100) * 0.02 for i in range(n)],
                evaluator=lambda encrypted, data: encrypted.dot(
                    [0.1 + ((i % 5) * 0.05) for i in range(len(data))]
                ),
                expected_builder=lambda data: [
                    sum(
                        x * (0.1 + ((i % 5) * 0.05))
                        for i, x in enumerate(data)
                    )
                ],
                error_builder=lambda expected, actual: abs(expected[0] - actual[0]),
            ),
        },
    ]

    for case in runtime_cases:
        print(f"Running {case['case_name']} ...")
        for batch in case["batch_sizes"]:
            for repeat in range(1, RUNTIME_REPEATS + 1):
                row = case["factory"](batch)
                row["repeat"] = repeat
                row["error_metric"] = case["error_metric"]
                rows.append(row)
                print(
                    f"  batch={batch:>5} repeat={repeat} "
                    f"eval={row['evaluation_time_sec']:.4f}s "
                    f"error={row['error_value']}"
                )
    return rows


def benchmark_runtime_case(
    *,
    case_name: str,
    scheme: str,
    batch: int,
    context_builder: Callable[[], Any],
    poly_modulus_degree: int,
    data_builder: Callable[[int], list[float]],
    evaluator: Callable[[Any, list[float]], Any],
    expected_builder: Callable[[list[float]], list[float]],
    error_builder: Callable[[list[float], list[float]], float | int],
) -> dict[str, Any]:
    ctx = context_builder()
    data = data_builder(batch)

    t0 = time.perf_counter()
    if scheme == "BFV":
        encrypted = ts.bfv_vector(ctx, data)
    else:
        encrypted = ts.ckks_vector(ctx, data)
    encryption_time = time.perf_counter() - t0

    payload_mb = len(encrypted.serialize()) / 1024 / 1024

    t0 = time.perf_counter()
    result = evaluator(encrypted, data)
    evaluation_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    decrypted = result.decrypt()
    decryption_time = time.perf_counter() - t0

    expected = expected_builder(data)
    error_value = error_builder(expected, decrypted)

    row = {
        "case_name": case_name,
        "scheme": scheme,
        "batch_size": batch,
        "poly_modulus_degree": poly_modulus_degree,
        "payload_mb": round(payload_mb, 6),
        "encryption_time_sec": encryption_time,
        "evaluation_time_sec": evaluation_time,
        "decryption_time_sec": decryption_time,
        "error_value": error_value,
    }

    del ctx, encrypted, result
    gc.collect()
    return row


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize_runtime_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["case_name"]), int(row["batch_size"]))].append(row)

    summary_rows: list[dict[str, Any]] = []
    for (case_name, batch_size), group in sorted(grouped.items()):
        summary_rows.append(
            {
                "case_name": case_name,
                "scheme": group[0]["scheme"],
                "batch_size": batch_size,
                "poly_modulus_degree": group[0]["poly_modulus_degree"],
                "payload_mb": sum(float(item["payload_mb"]) for item in group) / len(group),
                "encryption_time_sec": sum(float(item["encryption_time_sec"]) for item in group) / len(group),
                "evaluation_time_sec": sum(float(item["evaluation_time_sec"]) for item in group) / len(group),
                "decryption_time_sec": sum(float(item["decryption_time_sec"]) for item in group) / len(group),
                "error_metric": group[0]["error_metric"],
                "error_value": sum(float(item["error_value"]) for item in group) / len(group),
            }
        )
    return summary_rows


def plot_bfv_eval_vs_batch(summary_rows: list[dict[str, Any]]) -> Path:
    rows = [row for row in summary_rows if row["case_name"] == "bfv_affine"]
    output_path = OUTPUT_DIR / "batch_size_vs_eval_time_bfv.svg"
    write_line_chart_svg(
        output_path,
        title="BFV Batch Size vs Evaluation Time",
        x_label="Batch Size",
        y_label="Evaluation Time (sec)",
        series=[
            {
                "label": "BFV affine",
                "color": "#1d4ed8",
                "points": [(row["batch_size"], row["evaluation_time_sec"]) for row in rows],
            }
        ],
        x_scale="log2",
        y_scale="linear",
    )
    return output_path


def plot_ckks_eval_vs_batch(summary_rows: list[dict[str, Any]]) -> Path:
    labels = {
        "ckks_polynomial": ("Polynomial", "#2563eb"),
        "ckks_mean_reduce": ("Mean Reduce", "#16a34a"),
        "ckks_dot_product_public": ("Dot Product", "#dc2626"),
    }
    series = []
    for case_name, (label, color) in labels.items():
        rows = [row for row in summary_rows if row["case_name"] == case_name]
        series.append(
            {
                "label": label,
                "color": color,
                "points": [(row["batch_size"], row["evaluation_time_sec"]) for row in rows],
            }
        )
    output_path = OUTPUT_DIR / "batch_size_vs_eval_time_ckks.svg"
    write_line_chart_svg(
        output_path,
        title="CKKS Batch Size vs Evaluation Time",
        x_label="Batch Size",
        y_label="Evaluation Time (sec)",
        series=series,
        x_scale="log2",
        y_scale="linear",
    )
    return output_path


def plot_ckks_error_vs_batch(summary_rows: list[dict[str, Any]]) -> Path:
    labels = {
        "ckks_polynomial": ("Polynomial max abs error", "#2563eb"),
        "ckks_mean_reduce": ("Mean abs error", "#16a34a"),
        "ckks_dot_product_public": ("Dot-product abs error", "#dc2626"),
    }
    series = []
    for case_name, (label, color) in labels.items():
        rows = [row for row in summary_rows if row["case_name"] == case_name]
        series.append(
            {
                "label": label,
                "color": color,
                "points": [(row["batch_size"], max(float(row["error_value"]), 1e-12)) for row in rows],
            }
        )
    output_path = OUTPUT_DIR / "ckks_error_vs_data_size.svg"
    write_line_chart_svg(
        output_path,
        title="CKKS Error Growth as Data Size Increases",
        x_label="Batch Size",
        y_label="Absolute Error",
        series=series,
        x_scale="log2",
        y_scale="log10",
    )
    return output_path


def plot_payload_vs_batch(summary_rows: list[dict[str, Any]]) -> Path:
    labels = {
        "bfv_affine": ("BFV affine", "#1d4ed8"),
        "ckks_polynomial": ("CKKS polynomial", "#7c3aed"),
    }
    series = []
    for case_name, (label, color) in labels.items():
        rows = [row for row in summary_rows if row["case_name"] == case_name]
        series.append(
            {
                "label": label,
                "color": color,
                "points": [(row["batch_size"], row["payload_mb"]) for row in rows],
            }
        )
    output_path = OUTPUT_DIR / "batch_size_vs_payload.svg"
    write_line_chart_svg(
        output_path,
        title="Batch Size vs Ciphertext Payload",
        x_label="Batch Size",
        y_label="Payload (MB)",
        series=series,
        x_scale="log2",
        y_scale="linear",
    )
    return output_path


def plot_ckks_depth_error(depth_rows: list[dict[str, Any]]) -> Path:
    series = []
    for config_name, color in [
        ("CKKS deg=16384 [60,40x4,60]", "#2563eb"),
        ("CKKS deg=32768 [60,40x5,60]", "#dc2626"),
    ]:
        rows = [
            row for row in depth_rows
            if row["config_name"] == config_name and row["status"] == "ok"
        ]
        series.append(
            {
                "label": config_name,
                "color": color,
                "points": [(row["depth"], max(float(row["abs_error"]), 1e-12)) for row in rows],
            }
        )
    output_path = OUTPUT_DIR / "ckks_depth_vs_error.svg"
    write_line_chart_svg(
        output_path,
        title="CKKS Multiplicative Depth vs Error",
        x_label="Successful Depth",
        y_label="Absolute Error",
        series=series,
        x_scale="linear",
        y_scale="log10",
    )
    return output_path


def write_line_chart_svg(
    output_path: Path,
    *,
    title: str,
    x_label: str,
    y_label: str,
    series: list[dict[str, Any]],
    x_scale: str,
    y_scale: str,
) -> None:
    width = 900
    height = 560
    left = 90
    right = 28
    top = 60
    bottom = 72
    plot_width = width - left - right
    plot_height = height - top - bottom

    all_points = [point for line in series for point in line["points"]]
    x_values = [float(point[0]) for point in all_points]
    y_values = [float(point[1]) for point in all_points]
    x_ticks = sorted({float(value) for value in x_values})

    def transform(value: float, scale: str) -> float:
        if scale == "log2":
            return math.log2(value)
        if scale == "log10":
            return math.log10(max(value, 1e-12))
        return value

    tx_values = [transform(value, x_scale) for value in x_values]
    ty_values = [transform(value, y_scale) for value in y_values]
    min_tx, max_tx = min(tx_values), max(tx_values)
    min_ty, max_ty = min(ty_values), max(ty_values)
    if math.isclose(min_tx, max_tx):
        max_tx += 1.0
    if math.isclose(min_ty, max_ty):
        max_ty += 1.0

    def x_pos(value: float) -> float:
        tx = transform(value, x_scale)
        return left + ((tx - min_tx) / (max_tx - min_tx)) * plot_width

    def y_pos(value: float) -> float:
        ty = transform(value, y_scale)
        return top + plot_height - ((ty - min_ty) / (max_ty - min_ty)) * plot_height

    y_tick_values = build_y_ticks(y_values, y_scale)
    legend_x = width - 250
    legend_y = top + 8
    output_path.parent.mkdir(parents=True, exist_ok=True)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="{width / 2}" y="30" text-anchor="middle" font-size="22" font-family="Arial, sans-serif" fill="#0f172a">{escape_xml(title)}</text>',
        f'<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" fill="#ffffff" stroke="#cbd5e1"/>',
    ]

    for tick in y_tick_values:
        y = y_pos(tick)
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" y2="{y:.2f}" stroke="#e2e8f0" stroke-dasharray="4 4"/>')
        parts.append(
            f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" font-size="12" font-family="Arial, sans-serif" fill="#475569">{format_tick(tick, y_scale)}</text>'
        )

    for tick in x_ticks:
        x = x_pos(tick)
        parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + plot_height}" stroke="#f1f5f9"/>')
        parts.append(
            f'<text x="{x:.2f}" y="{top + plot_height + 22}" text-anchor="middle" font-size="12" font-family="Arial, sans-serif" fill="#475569">{format_tick(tick, x_scale)}</text>'
        )

    parts.append(f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#64748b"/>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#64748b"/>')

    for index, line in enumerate(series):
        points = " ".join(f"{x_pos(float(x)):.2f},{y_pos(float(y)):.2f}" for x, y in line["points"])
        parts.append(
            f'<polyline fill="none" stroke="{line["color"]}" stroke-width="3" points="{points}"/>'
        )
        for x, y in line["points"]:
            cx = x_pos(float(x))
            cy = y_pos(float(y))
            parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="4.5" fill="{line["color"]}" stroke="#ffffff" stroke-width="1.5"/>')
        ly = legend_y + index * 22
        parts.append(f'<line x1="{legend_x}" y1="{ly}" x2="{legend_x + 26}" y2="{ly}" stroke="{line["color"]}" stroke-width="3"/>')
        parts.append(
            f'<text x="{legend_x + 34}" y="{ly + 4}" font-size="12" font-family="Arial, sans-serif" fill="#334155">{escape_xml(str(line["label"]))}</text>'
        )

    parts.append(
        f'<text x="{left + plot_width / 2}" y="{height - 18}" text-anchor="middle" font-size="14" font-family="Arial, sans-serif" fill="#334155">{escape_xml(x_label)}</text>'
    )
    parts.append(
        f'<text x="24" y="{top + plot_height / 2}" text-anchor="middle" font-size="14" font-family="Arial, sans-serif" fill="#334155" transform="rotate(-90 24 {top + plot_height / 2})">{escape_xml(y_label)}</text>'
    )
    parts.append("</svg>")

    output_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def build_y_ticks(values: list[float], scale: str) -> list[float]:
    min_value = min(values)
    max_value = max(values)
    if scale == "log10":
        min_power = math.floor(math.log10(max(min_value, 1e-12)))
        max_power = math.ceil(math.log10(max_value))
        return [10**power for power in range(min_power, max_power + 1)]
    if math.isclose(min_value, max_value):
        return [min_value]
    step = (max_value - min_value) / 4
    return [min_value + step * idx for idx in range(5)]


def format_tick(value: float, scale: str) -> str:
    if scale == "log10":
        power = int(round(math.log10(max(value, 1e-12))))
        return f"1e{power}"
    if value >= 1000 or float(value).is_integer():
        return f"{int(value)}"
    if value >= 1:
        return f"{value:.2f}"
    return f"{value:.4g}"


def escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def write_summary_json(
    *,
    slot_rows: list[dict[str, Any]],
    serialization_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    depth_rows: list[dict[str, Any]],
    runtime_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    plot_paths: list[Path],
) -> None:
    payload = {
        "slot_capacity": slot_rows,
        "serialization_boundary": serialization_rows,
        "context_sizes": context_rows,
        "ckks_depth": depth_rows,
        "runtime_scaling_raw": runtime_rows,
        "runtime_scaling_summary": summary_rows,
        "plots": [str(path) for path in plot_paths],
    }
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Benchmark 1/5: slot-capacity boundary")
    slot_rows = benchmark_slot_capacity()
    write_csv(SLOTS_CSV, slot_rows)

    print("Benchmark 2/5: serialization boundary")
    serialization_rows = benchmark_serialization_boundary()
    write_csv(SERIALIZATION_CSV, serialization_rows)

    print("Benchmark 3/5: context-size growth")
    context_rows = benchmark_context_sizes()
    write_csv(CONTEXT_CSV, context_rows)

    print("Benchmark 4/5: CKKS multiplicative depth")
    depth_rows = benchmark_ckks_depth()
    write_csv(DEPTH_CSV, depth_rows)

    print("Benchmark 5/5: runtime and error scaling")
    runtime_rows = benchmark_runtime_scaling()
    write_csv(RUNTIME_CSV, runtime_rows)
    summary_rows = summarize_runtime_rows(runtime_rows)

    plot_paths = [
        plot_bfv_eval_vs_batch(summary_rows),
        plot_ckks_eval_vs_batch(summary_rows),
        plot_ckks_error_vs_batch(summary_rows),
        plot_payload_vs_batch(summary_rows),
        plot_ckks_depth_error(depth_rows),
    ]

    write_summary_json(
        slot_rows=slot_rows,
        serialization_rows=serialization_rows,
        context_rows=context_rows,
        depth_rows=depth_rows,
        runtime_rows=runtime_rows,
        summary_rows=summary_rows,
        plot_paths=plot_paths,
    )

    print("\nSaved benchmark artifacts:")
    for path in [
        SLOTS_CSV,
        SERIALIZATION_CSV,
        CONTEXT_CSV,
        DEPTH_CSV,
        RUNTIME_CSV,
        SUMMARY_JSON,
        *plot_paths,
    ]:
        print(f"  - {path}")


if __name__ == "__main__":
    main()
