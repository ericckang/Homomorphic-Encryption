from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_side.crypto import decrypt_vector, encrypt_scalar_operand, encrypt_vector, make_context
from agent_side.formula_parser import evaluate_formula_ast
from agent_side.planner import plan_he_task
from agent_side.preflight import preflight_input_vector, preflight_plan, preflight_task_prompt
from agent_side.reporting import print_report
from agent_side.result_store import save_agent_result
from agent_side.transport import post_compute
from he_common.demo_state import reset_demo_state, update_agent, update_result
from he_common.operations import (
    apply_plaintext_pipeline,
    build_server_display_formula,
    data_profile,
    estimate_depth,
    normalize_decrypted_result,
    sanitize_plan,
)


def run_agent_task(
    redacted_prompt: str,
    data: list[float],
    *,
    input_metadata: dict[str, Any] | None = None,
    reset_state: bool = True,
    encrypt_formula_constants: bool = False,
) -> dict[str, Any]:
    if reset_state:
        reset_demo_state()
    selected_column = input_metadata.get("selected_column") if input_metadata else None
    update_agent(
        "collecting_input",
        "Task received from user input.",
        {"vector_length": len(data), "selected_column": selected_column},
    )

    preflight_input_vector(data)
    profile = data_profile(data, input_metadata)
    preflight_task_prompt(redacted_prompt)

    update_agent(
        "planning",
        "Asking planner for an HE operation schema without raw data.",
        {
            "vector_length": len(data),
            "numeric_kind": profile.get("numeric_kind"),
            "input_kind": profile.get("input_kind"),
            "selected_column": profile.get("selected_column"),
        },
    )

    formula_plan = _build_formula_plan_if_needed(redacted_prompt, input_metadata)
    if formula_plan is None:
        raw_plan = plan_he_task(redacted_prompt, profile)
        plan = sanitize_plan(raw_plan, profile)
        data = _resolve_plan_input_vector(data, plan, input_metadata)
        profile = data_profile(data, _with_selected_column(input_metadata, plan.get("target_column")))
        if encrypt_formula_constants:
            plan = _encrypt_plan_constants(plan)
        depth = estimate_depth(plan["operations"])
        preflight = preflight_plan(plan, len(data))
    else:
        plan = formula_plan
        if encrypt_formula_constants:
            plan = _encrypt_formula_plan_constants(plan)
        data = _resolve_formula_primary_vector(plan, input_metadata)
        profile = data_profile(data, _with_selected_column(input_metadata, plan.get("target_column")))
        depth = plan["depth"]
        preflight_input_vector(data)
        preflight = type("FormulaPreflight", (), {"warnings": [], "estimated_payload_bytes": 0})()

    update_agent(
        "planned",
        f"Planned schema '{plan['schema_name']}' with {len(plan['operations'])} operation(s).",
        {
            "schema_name": plan["schema_name"],
            "scheme": plan["scheme"],
            "depth": depth,
            "estimated_payload_kb": round(preflight.estimated_payload_bytes / 1024, 2),
            "warnings": preflight.warnings,
            "encrypt_formula_constants": encrypt_formula_constants,
            "selected_column": plan.get("target_column"),
        },
    )

    context, poly_mod_degree = make_context(plan["scheme"], len(data), depth)

    update_agent("encrypting", "Encrypting local data.", {"scheme": plan["scheme"]})
    t0 = time.perf_counter()
    encrypted_vector = encrypt_vector(context, plan["scheme"], data)
    encrypted_operands = _build_encrypted_operands(context, plan, len(data))
    encrypted_inputs = _build_encrypted_inputs(context, plan, input_metadata)
    encryption_time = time.perf_counter() - t0

    update_agent("sending", "Sending ciphertext and operation schema to compute service.")
    server_response, _ = post_compute(context, encrypted_vector, plan, encrypted_operands, encrypted_inputs)

    result_path = Path(server_response["result_path"])
    update_agent("decrypting", "Decrypting returned ciphertext locally.")
    t0 = time.perf_counter()
    decrypted = normalize_decrypted_result(
        plan,
        decrypt_vector(context, plan["scheme"], result_path.read_bytes()),
    )
    decryption_time = time.perf_counter() - t0

    expected = _expected_output(data, plan, input_metadata)
    update_agent("reporting", "Preparing final result summary for the dashboard.")
    result_summary = print_report(
        plan,
        data,
        decrypted,
        expected,
        server_response,
        {"encryption": encryption_time, "decryption": decryption_time},
        poly_mod_degree,
        encrypt_formula_constants,
        input_metadata=input_metadata,
    )
    saved_result_path = save_agent_result(result_summary)
    result_summary["saved_result_path"] = saved_result_path
    update_result(result_summary)
    update_agent(
        "done",
        "Agent run completed successfully.",
        {"schema_name": plan["schema_name"], "saved_result_path": saved_result_path},
    )

    return {
        "plan": plan,
        "decrypted": decrypted,
        "expected": expected,
        "server_response": server_response,
        "timings": {"encryption": encryption_time, "decryption": decryption_time},
        "poly_mod_degree": poly_mod_degree,
        "result_summary": result_summary,
    }


def _encrypt_plan_constants(plan: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(plan)
    transformed_ops: list[dict[str, Any]] = []
    operand_index = 0
    for operation in plan["operations"]:
        op = operation["op"]
        if op in {"add_scalar", "sub_scalar", "mul_scalar"}:
            transformed_op = dict(operation)
            transformed_op["op"] = op.replace("_scalar", "_encrypted_scalar")
            transformed_op["operand_key"] = f"enc_const_{operand_index}"
            transformed_ops.append(transformed_op)
            operand_index += 1
            continue

        if op == "polynomial":
            transformed_op = dict(operation)
            transformed_terms: list[dict[str, Any]] = []
            for term in operation.get("terms", []):
                transformed_term = dict(term)
                transformed_term["operand_key"] = f"enc_const_{operand_index}"
                transformed_terms.append(transformed_term)
                operand_index += 1
            transformed_op["terms"] = transformed_terms
            transformed_op["constant_operand_key"] = f"enc_const_{operand_index}"
            operand_index += 1
            transformed_ops.append(transformed_op)
            continue

        transformed_ops.append(dict(operation))
    transformed["operations"] = transformed_ops
    transformed["notes"] = (
        f"{plan['notes']} Constants in eligible scalar operations and polynomial terms were encrypted before server evaluation."
    ).strip()
    transformed["server_display_formula"] = build_server_display_formula(transformed)
    return transformed


def _resolve_plan_input_vector(
    data: list[float],
    plan: dict[str, Any],
    input_metadata: dict[str, Any] | None,
) -> list[float]:
    if not input_metadata or input_metadata.get("input_kind") != "table":
        return data
    target_column = plan.get("target_column")
    table_columns = input_metadata.get("table_columns") or {}
    raw_values = table_columns.get(target_column)
    if not isinstance(raw_values, list) or not raw_values:
        raise ValueError(f"Selected CSV column '{target_column}' could not be loaded from the uploaded file.")
    return [float(value) for value in raw_values]


def _with_selected_column(input_metadata: dict[str, Any] | None, selected_column: str | None) -> dict[str, Any] | None:
    if not input_metadata:
        return None
    merged = dict(input_metadata)
    if selected_column:
        merged["selected_column"] = selected_column
    return merged


def _build_encrypted_operands(context, plan: dict[str, Any], vector_size: int) -> dict[str, Any]:
    operands: dict[str, Any] = {}

    formula_constants = plan.get("encrypted_formula_constants") or {}
    for operand_key, constant_value in formula_constants.items():
        operands[operand_key] = encrypt_scalar_operand(context, plan["scheme"], constant_value, vector_size)

    for operation in plan["operations"]:
        operand_key = operation.get("operand_key")
        if operand_key:
            operands[operand_key] = encrypt_scalar_operand(context, plan["scheme"], operation["value"], vector_size)

        if operation.get("op") == "polynomial":
            for term in operation.get("terms", []):
                term_operand_key = term.get("operand_key")
                if term_operand_key:
                    operands[term_operand_key] = encrypt_scalar_operand(
                        context,
                        plan["scheme"],
                        term["coefficient"],
                        vector_size,
                    )
            constant_operand_key = operation.get("constant_operand_key")
            if constant_operand_key:
                operands[constant_operand_key] = encrypt_scalar_operand(
                    context,
                    plan["scheme"],
                    operation.get("constant", 0),
                    vector_size,
                )
    return operands


def _build_formula_plan_if_needed(redacted_prompt: str, input_metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not input_metadata or input_metadata.get("input_kind") != "table":
        return None
    formula_ast = input_metadata.get("formula_ast")
    formula_columns = input_metadata.get("formula_columns")
    if not isinstance(formula_ast, dict) or not isinstance(formula_columns, list) or not formula_columns:
        return None

    return {
        "schema_name": str(input_metadata.get("computed_column") or "computed_formula"),
        "scheme": "CKKS",
        "computation_type": "general_ckks",
        "operations": [],
        "result_shape": "vector",
        "result_label": str(input_metadata.get("computed_column") or "computed_formula"),
        "plaintext_formula": str(input_metadata.get("formula_expression") or redacted_prompt),
        "notes": "Rule-based encrypted formula evaluation over CSV numeric columns.",
        "target_column": str(input_metadata.get("computed_column") or "computed_formula"),
        "server_display_formula": str(input_metadata.get("formula_expression") or redacted_prompt),
        "formula_ast": formula_ast,
        "formula_columns": list(formula_columns),
        "depth": _formula_depth(formula_ast),
        "formula_path": "rule_based_formula",
    }


def _formula_depth(node: dict[str, Any]) -> int:
    node_type = node.get("type")
    if node_type in {"constant", "encrypted_constant", "variable"}:
        return 0
    if node_type == "neg":
        return _formula_depth(node["operand"])
    if node_type in {"add", "sub"}:
        return max(_formula_depth(node["left"]), _formula_depth(node["right"]))
    if node_type == "mul":
        return 1 + max(_formula_depth(node["left"]), _formula_depth(node["right"]))
    if node_type == "pow":
        right_node = node["right"]
        if right_node.get("type") != "constant":
            raise ValueError("Encrypted formula exponents must remain plaintext constants.")
        exponent = int(right_node["value"])
        return max(_formula_depth(node["left"]), (exponent - 1).bit_length())
    raise ValueError(f"Unsupported formula node type: {node_type}")


def _resolve_formula_primary_vector(plan: dict[str, Any], input_metadata: dict[str, Any] | None) -> list[float]:
    if not input_metadata:
        raise ValueError("Formula plan requires table input metadata.")
    first_column = plan["formula_columns"][0]
    raw_values = (input_metadata.get("table_columns") or {}).get(first_column)
    if not isinstance(raw_values, list) or not raw_values:
        raise ValueError(f"Formula input column '{first_column}' could not be loaded from the uploaded file.")
    return [float(value) for value in raw_values]


def _build_encrypted_inputs(context, plan: dict[str, Any], input_metadata: dict[str, Any] | None) -> dict[str, Any]:
    formula_columns = plan.get("formula_columns") or []
    if not formula_columns:
        return {}
    if not input_metadata:
        raise ValueError("Formula plan requires table input metadata.")
    table_columns = input_metadata.get("table_columns") or {}
    encrypted_inputs: dict[str, Any] = {}
    for column_name in formula_columns:
        raw_values = table_columns.get(column_name)
        if not isinstance(raw_values, list) or not raw_values:
            raise ValueError(f"Formula input column '{column_name}' could not be loaded from the uploaded file.")
        encrypted_inputs[column_name] = encrypt_vector(
            context,
            plan["scheme"],
            [float(value) for value in raw_values],
        )
    return encrypted_inputs


def _expected_output(data: list[float], plan: dict[str, Any], input_metadata: dict[str, Any] | None) -> list[float]:
    formula_ast = plan.get("formula_ast")
    formula_columns = plan.get("formula_columns") or []
    if not isinstance(formula_ast, dict) or not formula_columns:
        return apply_plaintext_pipeline(data, plan["operations"])
    if not input_metadata:
        raise ValueError("Formula plan requires table input metadata.")
    table_columns = input_metadata.get("table_columns") or {}
    row_count = len(next(iter(table_columns.values()), []))
    expected = []
    for row_index in range(row_count):
        row_env = {
            column_name: float(table_columns[column_name][row_index])
            for column_name in formula_columns
        }
        expected.append(evaluate_formula_ast(_deserialize_formula_ast(formula_ast), row_env))
    return expected


def _encrypt_formula_plan_constants(plan: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(plan)
    constant_index = 0
    encrypted_constants: dict[str, float] = {}

    def transform(node: dict[str, Any]) -> dict[str, Any]:
        nonlocal constant_index
        node_type = node.get("type")
        if node_type == "constant":
            operand_key = f"enc_formula_const_{constant_index}"
            constant_index += 1
            encrypted_constants[operand_key] = float(node["value"])
            return {"type": "encrypted_constant", "operand_key": operand_key, "value": float(node["value"])}
        if node_type == "neg":
            return {"type": "neg", "operand": transform(node["operand"])}
        if node_type == "pow":
            return {
                "type": "pow",
                "left": transform(node["left"]),
                "right": dict(node["right"]),
            }
        if node_type in {"add", "sub", "mul"}:
            return {
                "type": node_type,
                "left": transform(node["left"]),
                "right": transform(node["right"]),
            }
        return dict(node)

    transformed_formula_ast = transform(plan["formula_ast"])
    transformed["formula_ast"] = transformed_formula_ast
    transformed["encrypted_formula_constants"] = encrypted_constants
    transformed["notes"] = (
        f"{plan['notes']} Formula constants were encrypted before server evaluation."
    ).strip()
    transformed["server_display_formula"] = _formula_ast_display(transformed_formula_ast)
    return transformed


def _formula_ast_display(node: dict[str, Any]) -> str:
    node_type = node.get("type")
    if node_type == "constant":
        value = node.get("value")
        return str(int(value)) if float(value).is_integer() else str(value)
    if node_type == "encrypted_constant":
        return "⟦c⟧"
    if node_type == "variable":
        return str(node.get("name", "x"))
    if node_type == "neg":
        return f"(-{_formula_ast_display(node['operand'])})"
    if node_type == "add":
        return f"({_formula_ast_display(node['left'])} + {_formula_ast_display(node['right'])})"
    if node_type == "sub":
        return f"({_formula_ast_display(node['left'])} - {_formula_ast_display(node['right'])})"
    if node_type == "mul":
        return f"({_formula_ast_display(node['left'])} * {_formula_ast_display(node['right'])})"
    if node_type == "pow":
        return f"({_formula_ast_display(node['left'])}^{_formula_ast_display(node['right'])})"
    return str(node_type)


def _deserialize_formula_ast(node: dict[str, Any]):
    import ast

    node_type = node.get("type")
    if node_type == "constant":
        return ast.Constant(value=float(node["value"]))
    if node_type == "encrypted_constant":
        return ast.Constant(value=float(node["value"]))
    if node_type == "variable":
        return ast.Name(id=str(node["name"]), ctx=ast.Load())
    if node_type == "neg":
        return ast.UnaryOp(op=ast.USub(), operand=_deserialize_formula_ast(node["operand"]))
    op_map = {"add": ast.Add(), "sub": ast.Sub(), "mul": ast.Mult(), "pow": ast.Pow()}
    if node_type in op_map:
        return ast.BinOp(
            left=_deserialize_formula_ast(node["left"]),
            op=op_map[node_type],
            right=_deserialize_formula_ast(node["right"]),
        )
    raise ValueError(f"Unsupported formula node type: {node_type}")
