from __future__ import annotations

from pydantic import BaseModel, Field


class ComputeRequest(BaseModel):
    computation_type: str
    scheme: str
    context_path: str
    payload_path: str
    result_path: str
    params: dict = Field(default_factory=dict)


class ComputeResponse(BaseModel):
    status: str
    computation_type: str
    scheme: str
    result_path: str
    results: list[dict]
    evaluation_time_sec: float
    audit: dict
