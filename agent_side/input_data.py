from __future__ import annotations

import ast
import csv
import re
from pathlib import Path
from typing import Any

from agent_side.formula_parser import (
    evaluate_formula_ast,
    extract_formula_expression,
    infer_result_column_name,
    looks_like_unsupported_formula_prompt,
    maybe_parse_formula_expression,
    parse_formula_ast,
    referenced_variables,
    serialize_formula_node,
)
from agent_side.input_models import ColumnInfo, CsvTableInfo, ResolvedInput
from agent_side.planner import parse_table_intent_with_llm


def collect_task_and_data() -> tuple[str, str, list[float], dict[str, Any]]:
    task_prompt = input(
        "\nTask prompt (you may include data=[1, 2, 3], or leave data out for CSV):\n> "
    ).strip()
    resolved = _resolve_task_input(task_prompt)
    return resolved.task_prompt, resolved.redacted_prompt, resolved.data, resolved.input_metadata


def resolve_task_and_data(
    task_prompt: str,
    manual_values: str | None = None,
    csv_text: str | None = None,
) -> tuple[str, str, list[float], dict[str, Any]]:
    resolved = _resolve_task_input(task_prompt, manual_values, csv_text)
    return resolved.task_prompt, resolved.redacted_prompt, resolved.data, resolved.input_metadata


def _resolve_task_input(
    task_prompt: str,
    manual_values: str | None = None,
    csv_text: str | None = None,
) -> ResolvedInput:
    data, redacted_prompt = extract_inline_data(task_prompt)
    if data is not None:
        return ResolvedInput(task_prompt, redacted_prompt, data, {"input_kind": "vector"})

    if manual_values is not None and manual_values.strip():
        data = coerce_numeric_vector(ast.literal_eval(manual_values.strip()))
        return ResolvedInput(task_prompt, redacted_prompt, data, {"input_kind": "vector"})

    if csv_text is not None and csv_text.strip():
        return _resolve_csv_data(task_prompt, redacted_prompt, load_csv_table_from_text(csv_text))

    csv_path = input("\nCSV path with one or more columns (blank to enter values manually): ").strip()
    if csv_path:
        return _resolve_csv_data(task_prompt, redacted_prompt, load_csv_table(csv_path))

    manual_values = input("\nEnter values as a Python-style list, e.g. [1, 2, 3]: ").strip()
    data = coerce_numeric_vector(ast.literal_eval(manual_values))
    return ResolvedInput(task_prompt, redacted_prompt, data, {"input_kind": "vector"})


def extract_inline_data(task_prompt: str) -> tuple[list[float] | None, str]:
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
    return load_csv_table(path_str).numeric_vector


def load_csv_table(path_str: str) -> CsvTableInfo:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    return parse_csv_rows(rows)


def load_csv_table_from_text(csv_text: str) -> CsvTableInfo:
    rows = list(csv.reader(csv_text.splitlines()))
    return parse_csv_rows(rows)


def parse_csv_rows(rows: list[list[str]]) -> CsvTableInfo:
    if not rows:
        raise ValueError("CSV file is empty.")
    if any(not any(cell.strip() for cell in row) for row in rows):
        raise ValueError("CSV contains an empty row. Please remove blank lines before upload.")

    header = [cell.strip() for cell in rows[0]]
    normalized_header = [cell.lower() for cell in header]
    has_header = _looks_like_header(rows[0], rows[1:])

    if not has_header:
        raw_values = [row[0] for row in rows]
        return CsvTableInfo(
            columns=[ColumnInfo(name="value", kind=infer_numeric_kind(raw_values))],
            row_count=len(raw_values),
            selected_column="value",
            numeric_vector=coerce_numeric_vector(raw_values),
            table_columns={"value": raw_values},
        )

    if any(not name for name in header):
        raise ValueError("CSV header contains an empty column name. Please fill or remove unnamed columns.")

    table_columns: dict[str, list[str]] = {name: [] for name in header if name}
    expected_width = len(header)
    for row_number, row in enumerate(rows[1:], start=2):
        if len(row) != expected_width:
            raise ValueError(
                f"CSV row {row_number} has {len(row)} columns, but the header has {expected_width}. "
                "Please fix missing or extra values before upload."
            )
        for idx, name in enumerate(header):
            if not name:
                continue
            table_columns[name].append(row[idx])

    columns = [ColumnInfo(name=name, kind=infer_column_kind(values)) for name, values in table_columns.items()]

    if "value" in normalized_header:
        value_idx = normalized_header.index("value")
        selected_column = header[value_idx]
        numeric_vector = coerce_numeric_vector(table_columns[selected_column])
    else:
        selected_column = _default_numeric_column(table_columns, columns)
        numeric_vector = coerce_numeric_vector(table_columns[selected_column])

    return CsvTableInfo(
        columns=columns,
        row_count=len(rows) - 1,
        selected_column=selected_column,
        numeric_vector=numeric_vector,
        table_columns=table_columns,
    )


def coerce_numeric_vector(values: Any) -> list[float]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("Input data must be a list/vector of numbers.")
    if not values:
        raise ValueError("Input data cannot be empty.")

    numeric: list[float] = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, bool):
            raise ValueError(f"Boolean values are not supported. Invalid value at position {index}.")
        if isinstance(value, (int, float)):
            numeric.append(float(value))
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError(f"Empty numeric value found at position {index}.")
            try:
                numeric.append(float(stripped))
            except ValueError as exc:
                raise ValueError(f"Non-numeric value {value!r} found at position {index}.") from exc
            continue
        raise ValueError(f"Unsupported value {value!r} found at position {index}.")
    return numeric


def infer_column_kind(values: list[str]) -> str:
    if any(not str(value).strip() for value in values):
        return "string"
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


def _default_numeric_column(table_columns: dict[str, list[str]], columns: list[ColumnInfo] | None = None) -> str:
    numeric_candidates = [name for name, values in table_columns.items() if infer_column_kind(values) != "string"]
    if not numeric_candidates:
        raise ValueError("CSV does not contain any numeric column that can be encrypted.")

    if columns:
        non_identifier_numeric = [
            column.name
            for column in columns
            if column.kind != "string" and not _looks_like_identifier_column(column.name, table_columns[column.name])
        ]
        if non_identifier_numeric:
            return non_identifier_numeric[0]
    return numeric_candidates[0]


def _resolve_csv_data(task_prompt: str, redacted_prompt: str, table_info: CsvTableInfo) -> ResolvedInput:
    selected_column = _infer_prompt_target_column(task_prompt, redacted_prompt, table_info)
    metadata = table_info.metadata()

    if metadata.get("formula_ast") and metadata.get("formula_columns"):
        numeric_vector = coerce_numeric_vector(table_info.table_columns[selected_column])
        table_info.selected_column = selected_column
        table_info.numeric_vector = numeric_vector
        metadata["selected_column"] = selected_column
        return ResolvedInput(task_prompt, redacted_prompt, numeric_vector, metadata)

    numeric_vector = coerce_numeric_vector(table_info.table_columns[selected_column])
    table_info.selected_column = selected_column
    table_info.numeric_vector = numeric_vector
    return ResolvedInput(task_prompt, redacted_prompt, numeric_vector, table_info.metadata())


def _infer_prompt_target_column(task_prompt: str, redacted_prompt: str, table_info: CsvTableInfo) -> str:
    columns = table_info.columns
    all_column_names = [column.name for column in columns]
    numeric_columns = [column.name for column in columns if column.kind in {"integer", "float"}]
    prompt_lower = task_prompt.lower()
    named_any_columns = [name for name in all_column_names if re.search(rf"\b{re.escape(name.lower())}\b", prompt_lower)]
    named_numeric_columns = [name for name in numeric_columns if re.search(rf"\b{re.escape(name.lower())}\b", prompt_lower)]

    if looks_like_unsupported_formula_prompt(task_prompt):
        raise ValueError("Unsupported formula syntax. Use only numeric columns, constants, +, -, *, and ^.")

    llm_intent = _parse_table_intent(redacted_prompt, table_info)
    if llm_intent.get("intent_type") == "formula":
        formula_expression = str(llm_intent.get("formula_expression", "")).strip()
        if not formula_expression:
            raise ValueError("LLM formula intent did not include a valid formula_expression.")
        matched_column = _match_formula_columns(task_prompt, table_info, parse_formula_ast(formula_expression), formula_expression)
        if matched_column:
            return matched_column
    if llm_intent.get("intent_type") == "reduction":
        reduction_column = str(llm_intent.get("target_column", "")).strip()
        if reduction_column in numeric_columns:
            return reduction_column
        raise ValueError(f"Planner selected invalid reduction column '{reduction_column}'.")

    parsed_formula = maybe_parse_formula_expression(task_prompt)
    if parsed_formula is not None:
        matched_column = _match_formula_columns(task_prompt, table_info, parsed_formula)
        if matched_column:
            return matched_column

    if not numeric_columns:
        raise ValueError("CSV does not contain any numeric column that can be encrypted.")
    if len(numeric_columns) == 1:
        return numeric_columns[0]
    if len(named_numeric_columns) == 1 and len(named_any_columns) == 1:
        return named_numeric_columns[0]
    return table_info.selected_column


def _match_formula_columns(
    task_prompt: str,
    table_info: CsvTableInfo,
    formula_ast=None,
    formula_expression: str | None = None,
) -> str | None:
    formula_expression = formula_expression or extract_formula_expression(task_prompt)
    formula_ast = formula_ast or parse_formula_ast(formula_expression)
    available_columns = {column.name: column.kind for column in table_info.columns}
    referenced_columns = referenced_variables(formula_ast)
    matched_numeric_columns = [
        column_name
        for column_name in referenced_columns
        if available_columns.get(column_name) in {"integer", "float"}
    ]

    unknown_columns = [column_name for column_name in referenced_columns if column_name not in available_columns]
    if unknown_columns:
        raise ValueError(f"Formula references unknown CSV column '{unknown_columns[0]}'.")

    if unknown_columns:
        raise ValueError(f"Formula references unknown CSV column '{unknown_columns[0]}'.")

    if not matched_numeric_columns:
        raise ValueError("Formula must reference at least one numeric CSV column.")

    _validate_formula_columns(table_info, matched_numeric_columns)

    computed_values = []
    for row_index in range(table_info.row_count):
        row_env = {
            column_name: float(table_info.table_columns[column_name][row_index])
            for column_name in matched_numeric_columns
        }
        computed_values.append(evaluate_formula_ast(formula_ast, row_env))

    computed_column_name = infer_result_column_name(task_prompt)
    table_info.table_columns[computed_column_name] = [str(value) for value in computed_values]
    table_info.columns = list(table_info.columns) + [ColumnInfo(name=computed_column_name, kind="float")]
    table_info.selected_column = computed_column_name
    table_info.numeric_vector = computed_values
    table_info.formula_expression = formula_expression
    table_info.formula_ast_serialized = serialize_formula_node(formula_ast)
    table_info.formula_columns = matched_numeric_columns
    table_info.computed_column = computed_column_name
    return computed_column_name


def _looks_like_identifier_column(column_name: str, values: list[str]) -> bool:
    normalized_name = column_name.strip().lower()
    if normalized_name.endswith("_id") or normalized_name == "id":
        return True
    try:
        numeric = coerce_numeric_vector(values)
    except ValueError:
        return False
    unique_ratio = len(set(numeric)) / len(numeric)
    return unique_ratio > 0.9 and all(float(x).is_integer() and x >= 0 for x in numeric)


def _parse_table_intent(redacted_prompt: str, table_info: CsvTableInfo) -> dict[str, Any]:
    try:
        return parse_table_intent_with_llm(redacted_prompt, table_info.metadata())
    except Exception:
        return {"intent_type": "planner"}


def _validate_formula_columns(table_info: CsvTableInfo, column_names: list[str]) -> None:
    table_columns = table_info.table_columns
    column_kinds = {column.name: column.kind for column in table_info.columns}
    for column_name in column_names:
        if column_kinds.get(column_name) not in {"integer", "float"}:
            raise ValueError(
                f"Column '{column_name}' is referenced in the formula but is not a clean numeric column. "
                "Please remove missing or non-numeric values before upload."
            )
        for row_index, raw_value in enumerate(table_columns.get(column_name, []), start=2):
            if not str(raw_value).strip():
                raise ValueError(
                    f"CSV column '{column_name}' has a missing value at row {row_index}. "
                    "Please clean the CSV before upload."
                )
            try:
                float(raw_value)
            except ValueError as exc:
                raise ValueError(
                    f"CSV column '{column_name}' has a non-numeric value {raw_value!r} at row {row_index}. "
                    "Please clean the CSV before upload."
                ) from exc
