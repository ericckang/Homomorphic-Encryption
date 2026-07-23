from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    kind: str


@dataclass
class CsvTableInfo:
    columns: list[ColumnInfo]
    row_count: int
    selected_column: str
    numeric_vector: list[float]
    table_columns: dict[str, list[str]]
    formula_expression: str | None = None
    formula_ast_serialized: dict[str, Any] | None = None
    formula_columns: list[str] | None = None
    computed_column: str | None = None

    def metadata(self) -> dict[str, Any]:
        metadata = {
            "input_kind": "table",
            "row_count": self.row_count,
            "columns": [{"name": column.name, "kind": column.kind} for column in self.columns],
            "selected_column": self.selected_column,
            "table_columns": self.table_columns,
        }
        if self.formula_expression is not None:
            metadata["formula_expression"] = self.formula_expression
        if self.formula_ast_serialized is not None:
            metadata["formula_ast"] = self.formula_ast_serialized
        if self.formula_columns is not None:
            metadata["formula_columns"] = self.formula_columns
        if self.computed_column is not None:
            metadata["computed_column"] = self.computed_column
        return metadata


@dataclass(frozen=True)
class ResolvedInput:
    task_prompt: str
    redacted_prompt: str
    data: list[float]
    input_metadata: dict[str, Any]
