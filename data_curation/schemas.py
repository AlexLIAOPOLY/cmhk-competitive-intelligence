from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceTask(BaseModel):
    id: str
    company: str
    metric: str
    current_value: str = ""
    raw_text: str = ""
    sources: list[str] = Field(default_factory=list)
    row_ref: str = ""
    source_score: float = 0.0
    source_tier: str = "unknown"
    evidence_hash: str = ""


class CandidateFact(BaseModel):
    id: str
    company: str
    metric: str
    value: str = ""
    basis: str = ""
    note: str = ""
    status: Literal["ok", "unavailable"] = "unavailable"
    entity_supported: bool = False
    metric_supported: bool = False
    value_supported: bool = False
    confidence: float = 0.0
    source_score: float = 0.0
    source_tier: str = "unknown"
    row_ref: str = ""
    sources: list[str] = Field(default_factory=list)
    evidence_hash: str = ""
    quality_score: float = 0.0
    decision: Literal["pending", "accepted", "rejected", "review"] = "pending"
    reasons: list[str] = Field(default_factory=list)


class GapRecord(BaseModel):
    company: str
    metric: str
    row_ref: str = ""
    reason: str
    candidate_ids: list[str] = Field(default_factory=list)


class RecrawlTask(BaseModel):
    row_ref: str
    row_number: int
    reason: str
    priority: int = 50
    attempts: int = 0
    companies: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)


class RunSummary(BaseModel):
    run_id: str
    started_at: str
    completed_at: str = ""
    tasks: int = 0
    accepted: int = 0
    rejected: int = 0
    review: int = 0
    gaps: int = 0
    recrawl_rows: list[int] = Field(default_factory=list)
    recrawl_performed: bool = False
    online_ai: bool = False
    node_events: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
