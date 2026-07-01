from __future__ import annotations

import ast
import csv
import re
from pathlib import Path
from typing import Any


def collect_task_and_data() -> tuple[str, str, list[float]]:
    task_prompt = input(
        "\nTask prompt (you may include data=[1, 2, 3], or leave data out for CSV):\n> "
    ).strip()
    data, redacted_prompt = extract_inline_data(task_prompt)
    if data is not None:
        return task_prompt, redacted_prompt, data

    csv_path = input("\nCSV path with a 'value' column (blank to enter values manually): ").strip()
    if csv_path:
        return task_prompt, redacted_prompt, load_csv_vector(csv_path)

    manual_values = input("\nEnter values as a Python-style list, e.g. [1, 2, 3]: ").strip()
    data = coerce_numeric_vector(ast.literal_eval(manual_values))
    return task_prompt, redacted_prompt, data


def extract_inline_data(task_prompt: str) -> tuple[list[float] | None, str]:
    """
    Pull data=[...] / values=[...] out locally and redact it before the LLM call.
    The model sees the task intent, not the raw sensitive values.
    """
    patterns = [
        r"(?is)\b(?:data|values|input)\s*[:=]\s*(\[[^\]]+\])",
        r"(?is)(\[[\s\d,\.\-+eE]+\])",
    ]
    for pattern in patterns:
        match = re.search(pattern, task_prompt)
        if not match:
            continue
        literal = match.group(1)
        try:
            data = coerce_numeric_vector(ast.literal_eval(literal))
        except (SyntaxError, ValueError, TypeError):
            continue
        redacted = task_prompt[: match.start(1)] + "[REDACTED_DATA]" + task_prompt[match.end(1) :]
        return data, redacted
    return None, task_prompt


def load_csv_vector(path_str: str) -> list[float]:
    """
    CSV format:
      value
      85000
      90000

    A headerless one-column CSV is also accepted.
    """
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = [row for row in csv.reader(fh) if row]

    if not rows:
        raise ValueError("CSV file is empty.")

    first_row = [cell.strip().lower() for cell in rows[0]]
    if "value" in first_row:
        value_idx = first_row.index("value")
        raw_values = [row[value_idx] for row in rows[1:] if len(row) > value_idx]
    else:
        raw_values = [row[0] for row in rows]

    return coerce_numeric_vector(raw_values)


def coerce_numeric_vector(values: Any) -> list[float]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("Input data must be a list/vector of numbers.")
    if not values:
        raise ValueError("Input data cannot be empty.")

    numeric: list[float] = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError("Boolean values are not supported.")
        if isinstance(value, (int, float)):
            numeric.append(float(value))
            continue
        if isinstance(value, str):
            numeric.append(float(value.strip()))
            continue
        raise ValueError(f"Unsupported value: {value!r}")
    return numeric
