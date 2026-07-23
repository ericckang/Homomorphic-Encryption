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
