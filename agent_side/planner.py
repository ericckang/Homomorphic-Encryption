from __future__ import annotations

import json
import os
import sys
from typing import Any

from openai import AzureOpenAI


sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

AZURE_OPENAI_ENDPOINT = os.environ.get(
    "AZURE_OPENAI_ENDPOINT",
    "https://aoai-ucla-prjs.openai.azure.com/",
)
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")


def get_azure_client() -> AzureOpenAI:
    subscription_key = os.environ.get("AZURE_OPENAI_KEY", "")
    if not subscription_key:
        raise RuntimeError("AZURE_OPENAI_KEY environment variable is not set.")

    return AzureOpenAI(
        api_version=AZURE_OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=subscription_key,
    )


def parse_table_intent_with_llm(redacted_task_prompt: str, data_profile: dict[str, Any]) -> dict[str, Any]:
    """
    Ask the model to normalize a CSV/table request into either a formula intent or a reduction intent.
    The result is validated later by deterministic code.
    """
    system_prompt = """
You are a semantic parser for a homomorphic-encryption agent.
Return ONLY valid JSON. Do not include Markdown.

You never receive raw data values. You only receive the user task text and table metadata.

Return exactly one of these shapes:

For arithmetic formulas over one or more CSV numeric columns:
{
  "intent_type": "formula",
  "formula_expression": "salary * 3 + age",
  "result_label": "risk_score"
}

For single-column aggregate/reduction tasks:
{
  "intent_type": "reduction",
  "reduction": "sum" or "mean",
  "target_column": "salary",
  "result_label": "salary_mean"
}

For anything else that should be handled by the generic planner:
{
  "intent_type": "planner"
}

Rules:
- Use intent_type=formula only for arithmetic expressions over CSV columns and numeric constants.
- Supported formula operators are +, -, *, and ^ only.
- Do not use division, comparisons, booleans, function calls, or conditionals in formula_expression.
- If any variable-like token in the user request is not an exact CSV header name from metadata, do NOT guess or rewrite it; return {"intent_type": "formula", "formula_expression": "<original expression>"} so validation can reject it.
- Never silently replace an unknown column with another known column.
- If the user clearly asks for sum or mean of one column, use intent_type=reduction.
- If uncertain, return {"intent_type": "planner"}.
- If you output formula_expression, reference CSV columns by exact header names from metadata.
""".strip()

    user_prompt = {
        "task_prompt_without_raw_data": redacted_task_prompt,
        "data_profile": data_profile,
    }
    response = get_azure_client().chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt)},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def plan_he_task(redacted_task_prompt: str, data_profile: dict[str, Any]) -> dict[str, Any]:
    """
    Ask the model to map a natural-language request onto the HE operation DSL.
    Raw data is intentionally excluded; only non-sensitive shape/type metadata is sent.
    """
    system_prompt = """
You are a planner for a homomorphic-encryption agent.
Return ONLY valid JSON. Do not include Markdown.

Important privacy rule:
- You never receive raw user data. Plan from the task text and metadata only.

Your output schema:
{
  "schema_name": "short_snake_case_name",
  "target_column": "column_name_if_input_is_table_or_null",
  "scheme": "BFV" or "CKKS",
  "computation_type": "general_bfv" or "general_ckks",
  "operations": [
    {"op": "add_scalar", "value": number},
    {"op": "sub_scalar", "value": number},
    {"op": "mul_scalar", "value": number},
    {"op": "square"},
    {"op": "sum_reduce"},
    {"op": "mean_reduce"},
    {"op": "dot_product_public", "weights": [number, number]},
    {
      "op": "polynomial",
      "terms": [{"power": positive_integer, "coefficient": number}],
      "constant": number
    }
  ],
  "result_label": "short human-readable label",
  "plaintext_formula": "formula applied element-wise to x",
  "notes": "short explanation, including any HE limitation"
}

Rules:
- If the input metadata describes a table/CSV, you must choose exactly one numeric target_column from the provided columns.
- Never choose a string/non-numeric column.
- If the input metadata is a single vector instead of a table, set target_column to null or omit it.
- Choose BFV only for exact integer arithmetic using add/subtract/multiply by scalar.
- Choose CKKS for floating point values, weighted/risk scores, averages, or polynomial scoring.
- This HE skill supports both vector->vector pipelines and a single final vector->scalar reduction.
- Allowed reductions are sum_reduce, mean_reduce, and dot_product_public, and they must be the final operation.
- Use sum_reduce for requests to sum or aggregate all encrypted values into one result.
- Use mean_reduce for mean/average requests only with CKKS.
- Use dot_product_public when the user provides public weights for a weighted score across the input vector.
- No sorting, branching, exact comparison, min/max, median discovery, division by encrypted values,
  or arbitrary conditionals.
- For comparison requests, return a difference score such as x - threshold, not a boolean.
- Use polynomial only when the user asks for a risk score, nonlinear score, square,
  or powers. Polynomial powers must be positive integers.
- Keep multiplicative depth practical; prefer shallow powers unless the task clearly asks deeper.
- computation_type must match the scheme: BFV -> general_bfv, CKKS -> general_ckks.
""".strip()

    user_prompt = {
        "task_prompt_without_raw_data": redacted_task_prompt,
        "data_profile": data_profile,
    }
    response = get_azure_client().chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt)},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)
