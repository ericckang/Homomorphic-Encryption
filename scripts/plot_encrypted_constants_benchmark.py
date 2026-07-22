from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit(
        "matplotlib is required for plotting. Install it with: pip install matplotlib"
    ) from exc

INPUT_CSV = PROJECT_ROOT / "benchmark_results" / "encrypted_constants_benchmark.csv"
OUTPUT_DIR = PROJECT_ROOT / "benchmark_results"
OPERATION_FAMILIES = ("add", "sub", "mul")
SCHEME = "BFV"


def main() -> None:
    rows = [row for row in load_rows(INPUT_CSV) if row["scheme"] == SCHEME]
    for operation_family in OPERATION_FAMILIES:
        filtered_rows = [row for row in rows if case_matches_operation(row["case_name"], operation_family)]

        eval_png = OUTPUT_DIR / f"bfv_eval_time_{operation_family}_vs_vector_length.png"
        plot_metric(
            filtered_rows,
            metric_key="evaluation_time_sec",
            ylabel="Evaluation Time (sec)",
            title=f"BFV {operation_family.upper()} Evaluation Time vs. Vector Length",
            output_path=eval_png,
        )
        print(f"Saved {eval_png}")

    mul_rows = [row for row in rows if case_matches_operation(row["case_name"], "mul")]
    payload_png = OUTPUT_DIR / "bfv_payload_mul_vs_vector_length.png"
    plot_metric(
        mul_rows,
        metric_key="total_payload_kb",
        ylabel="Total Payload (KB)",
        title="BFV MUL Payload vs. Vector Length",
        output_path=payload_png,
    )
    print(f"Saved {payload_png}")


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(
            f"Benchmark CSV not found: {path}\n"
            "Run python3 scripts/benchmark_encrypted_constants.py first."
        )
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def case_matches_operation(case_name: str, operation_family: str) -> bool:
    return case_name.endswith(f"_{operation_family}")


def plot_metric(
    rows: list[dict[str, str]],
    *,
    metric_key: str,
    ylabel: str,
    title: str,
    output_path: Path,
) -> None:
    grouped: dict[bool, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))

    for row in rows:
        encrypted_constants = row["encrypted_constants"].lower() == "true"
        vector_length = int(row["vector_length"])
        value = float(row[metric_key])
        grouped[encrypted_constants][vector_length].append(value)

    fig, axis = plt.subplots(figsize=(7, 5))
    colors = {False: "#2563eb", True: "#dc2626"}
    labels = {False: "Plaintext scalar", True: "Encrypted scalar"}

    for encrypted_constants in (False, True):
        series = grouped.get(encrypted_constants, {})
        if not series:
            continue
        x_values = sorted(series.keys())
        y_values = [statistics.mean(series[x]) for x in x_values]
        axis.plot(
            x_values,
            y_values,
            marker="o",
            linewidth=2,
            color=colors[encrypted_constants],
            label=labels[encrypted_constants],
        )

    axis.set_title(title)
    axis.set_xlabel("Vector Length")
    axis.set_ylabel(ylabel)
    axis.set_xticks(sorted({int(row["vector_length"]) for row in rows}))
    axis.grid(True, linestyle="--", alpha=0.35)
    axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
