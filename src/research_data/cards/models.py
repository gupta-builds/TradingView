"""Pydantic EvidenceCard and CriticReview — code SoT for AI hub card shape.

Vault YAML in ``Trading with Ai`` is a mirror example only. Schema version
bumps when fields change; DuckDB ``evidence_cards`` (build #2) is not here yet.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from research_data.models import QualityStatus
from research_data.paper.models import ActionLabel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class EvidencePoint(BaseModel):
    """One cited claim on a card; ``ref_key`` must exist in assembler input."""

    source: str
    point: str
    ref_key: str | None = None  # EvidenceRef.key or citation_id


class EvidenceCard(BaseModel):
    """Symbol-level evidence card produced by the analyst path."""

    card_id: str = Field(default_factory=_new_id)
    schema_version: int = 1
    symbol: str
    as_of: date
    action: ActionLabel
    confidence: float = Field(ge=0.0, le=1.0)
    time_horizon: str = "weeks_to_months"
    summary: str
    evidence: list[EvidencePoint] = Field(default_factory=list)
    opposing_evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation: list[str] = Field(default_factory=list)
    next_review_date: date | None = None
    data_quality_status: QualityStatus
    max_confidence: float = Field(ge=0.0, le=1.0)
    source_packet_symbol: str | None = None
    source_packet_as_of: date | None = None
    evidence_ref_keys: list[str] = Field(default_factory=list)
    spec_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("summary must be non-empty")
        return v


class CriticReview(BaseModel):
    """Separate from EvidenceCard — HOLD/DEMOTE pressure and confidence deltas."""

    review_id: str = Field(default_factory=_new_id)
    schema_version: int = 1
    card_id: str | None = None
    spec_id: str | None = None
    suggestion: str  # "hold" | "demote" | "ok" | "insufficient_data"
    confidence_delta: float = Field(le=0.0)  # monotone nonincreasing
    rationale: str
    risks_flagged: list[str] = Field(default_factory=list)
    gate_summary: dict[str, Any] = Field(default_factory=dict)
    rejected: bool = False
    reject_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("critic rationale must be non-empty")
        return v

    @field_validator("suggestion")
    @classmethod
    def validate_suggestion(cls, v: str) -> str:
        allowed = {"hold", "demote", "ok", "insufficient_data"}
        cleaned = v.strip().lower()
        if cleaned not in allowed:
            raise ValueError(f"suggestion must be one of {sorted(allowed)}, got {v!r}")
        return cleaned
