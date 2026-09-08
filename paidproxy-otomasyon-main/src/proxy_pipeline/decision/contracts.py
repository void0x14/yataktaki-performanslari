from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from proxy_pipeline.domain.models import Action


class TargetPlan(BaseModel):
    cidr: str
    ports: list[int] = Field(default_factory=list)
    protocols: list[str] = Field(default_factory=list)
    asn: int | None = None
    prefix: str | None = None
    sample_approach: str | None = None

    @field_validator("ports")
    @classmethod
    def ports_in_range(cls, value: list[int]) -> list[int]:
        for port in value:
            if not 1 <= int(port) <= 65535:
                raise ValueError("port out of range")
        return value


class DecisionItemPlan(BaseModel):
    candidate_id: str
    action: Action
    targets: list[TargetPlan] = Field(default_factory=list)
    order_index: int = 0
    resource_allocation: dict[str, Any] = Field(default_factory=dict)
    stop_expression: dict[str, Any] = Field(default_factory=dict)
    reassessment_expression: dict[str, Any] | None = None
    status: str = "pending"


class DecisionOutput(BaseModel):
    """Executable result schema. Does not constrain Stage-1 reasoning."""

    action: Action
    targets: list[TargetPlan] = Field(default_factory=list)
    resource_plan: dict[str, Any]
    stop_condition: dict[str, Any]
    items: list[DecisionItemPlan] = Field(default_factory=list)
    reassessment: dict[str, Any] | None = None
    expected_value: str | None = None
    confidence: str | None = None
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    requested_tools: list[str] = Field(default_factory=list)
    decision_id: str | None = None
    raw_response_ref: str | None = None
    provider: str | None = None
    model: str | None = None

    @field_validator("items")
    @classmethod
    def batch_requires_items(cls, value: list[DecisionItemPlan], info):
        return value
