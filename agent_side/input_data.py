from __future__ import annotations

import ast
import csv
import re
from pathlib import Path
from typing import Any


def collect_task_and_data() -> tuple[str, str, list[float], dict[str, Any]]:
    task_prompt = input(
        "\nTask prompt (you may include data=[1, 2, 3], or leave data out for CSV):\n> "
    ).strip()
    return resolve_task_and_data(task_prompt)


def resolve_task_and_data(
    task_prompt: str,
    manual_values: str | None = None,
    csv_text: str | None = None,
) -> tuple[str, str, list[float], dict[str, Any]]:
    data, redacted_prompt = extract_inline_data(task_prompt)
    if data is not None:
        return task_prompt, redacted_prompt, data, {"input_kind": "vector"}

    if manual_values is not None and manual_values.strip():
        data = coerce_numeric_vector(ast.literal_eval(manual_values.strip()))
        return task_prompt, redacted_prompt, data, {"input_kind": "vector"}

    if csv_text is not None and csv_text.strip():
        return _resolve_csv_data(task_prompt, redacted_prompt, load_csv_table_from_text(csv_text))

    csv_path = input("\nCSV path with one or more columns (blank to enter values manually): ").strip()
    if csv_path:
        return _resolve_csv_data(task_prompt, redacted_prompt, load_csv_table(csv_path))

    manual_values = input("\nEnter values as a Python-style list, e.g. [1, 2, 3]: ").strip()
    data = coerce_numeric_vector(ast.literal_eval(manual_values))
    return task_prompt, redacted_prompt, data, {"input_kind": "vector"}


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
    return load_csv_table(path_str)["numeric_vector"]


def load_csv_table(path_str: str) -> dict[str, Any]:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = [row for row in csv.reader(fh) if row]
    return parse_csv_rows(rows)


def load_csv_table_from_text(csv_text: str) -> dict[str, Any]:
    rows = [row for row in csv.reader(csv_text.splitlines()) if row]
    return parse_csv_rows(rows)


def parse_csv_rows(rows: list[list[str]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("CSV file is empty.")

    header = [cell.strip() for cell in rows[0]]
    normalized_header = [cell.lower() for cell in header]
    has_header = _looks_like_header(rows[0], rows[1:])

    if not has_header:
        raw_values = [row[0] for row in rows]
        return {
            "columns": [{"name": "value", "kind": infer_numeric_kind(raw_values)}],
            "row_count": len(raw_values),
            "selected_column": "value",
            "numeric_vector": coerce_numeric_vector(raw_values),
            "table_columns": {"value": raw_values},
        }

    table_columns: dict[str, list[str]] = {name: [] for name in header if name}
    for row in rows[1:]:
        for idx, name in enumerate(header):
            if not name:
                continue
            table_columns[name].append(row[idx] if idx < len(row) else "")

    if "value" in normalized_header:
        value_idx = normalized_header.index("value")
        selected_column = header[value_idx]
        numeric_vector = coerce_numeric_vector(table_columns[selected_column])
    else:
        selected_column = _default_numeric_column(table_columns)
        numeric_vector = coerce_numeric_vector(table_columns[selected_column])

    columns = []
    for name, values in table_columns.items():
        columns.append({"name": name, "kind": infer_column_kind(values)})

    return {
        "columns": columns,
        "row_count": len(rows) - 1,
        "selected_column": selected_column,
        "numeric_vector": numeric_vector,
        "table_columns": table_columns,
    }


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
            stripped = value.strip()
            if not stripped:
                raise ValueError("Empty CSV cells are not supported in numeric columns.")
            numeric.append(float(stripped))
            continue
        raise ValueError(f"Unsupported value: {value!r}")
    return numeric


def infer_column_kind(values: list[str]) -> str:
    try:
        return infer_numeric_kind(values)
    except ValueError:
        return "string"


def infer_numeric_kind(values: list[str]) -> str:
    numeric = coerce_numeric_vector(values)
    return "integer" if all(float(x).is_integer() for x in numeric) else "float"


def _looks_like_header(first_row: list[str], remaining_rows: list[list[str]]) -> bool:
    lowered = [cell.strip().lower() for cell in first_row]
    if "value" in lowered:
        return True
    if not remaining_rows:
        return True
    first_is_numeric = [_is_numeric_like(cell) for cell in first_row]
    next_is_numeric = [_is_numeric_like(cell) for cell in remaining_rows[0][: len(first_row)]]
    return any(not is_num for is_num in first_is_numeric) and any(next_is_numeric)


def _is_numeric_like(value: str) -> bool:
    try:
        float(value.strip())
        return True
    except Exception:
        return False


def _default_numeric_column(table_columns: dict[str, list[str]]) -> str:
    numeric_candidates = [name for name, values in table_columns.items() if infer_column_kind(values) != "string"]
    if not numeric_candidates:
        raise ValueError("CSV does not contain any numeric column that can be encrypted.")
    return numeric_candidates[0]


def _resolve_csv_data(
    task_prompt: str,
    redacted_prompt: str,
    table_info: dict[str, Any],
) -> tuple[str, str, list[float], dict[str, Any]]:
    metadata = {
        "input_kind": "table",
        "row_count": table_info["row_count"],
        "columns": table_info["columns"],
        "selected_column": table_info["selected_column"],
        "table_columns": table_info["table_columns"],
    }
    return task_prompt, redacted_prompt, table_info["numeric_vector"], metadata
