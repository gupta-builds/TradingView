"""Typed records for the brain closed loop.

Every model here is an auditable fact: who proposed what, based on which
citations, which gates ran with which inputs/outputs, and why a spec was
promoted or demoted. Nothing in this module fetches data or calls an LLM.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SpecStatus(str, Enum):
    """Lifecycle of a strategy spec. Only a human moves PROPOSED → APPROVED."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETIRED = "retired"


class PromotionState(str, Enum):
    """Where a spec stands against the four-gate promotion wall."""

    UNPROVEN = "unproven"
    DEMO_ELIGIBLE = "demo_eligible"
    DEMOTED = "demoted"


class GateName(str, Enum):
    """The four promotion gates. Order is fixed and non-negotiable."""

    OUT_OF_SAMPLE = "out_of_sample"
    MONTE_CARLO = "monte_carlo"
    WALK_FORWARD = "walk_forward"
    DEFLATED_SHARPE = "deflated_sharpe"


#: Fixed gate order: OOS → Monte Carlo → walk-forward → deflated Sharpe.
GATE_ORDER: tuple[GateName, ...] = (
    GateName.OUT_OF_SAMPLE,
    GateName.MONTE_CARLO,
    GateName.WALK_FORWARD,
    GateName.DEFLATED_SHARPE,
)


class DecisionKind(str, Enum):
    """Kinds of promotion decisions recorded in the loop."""

    PROMOTE = "promote"
    DEMOTE = "demote"
    HOLD = "hold"


# Identities that must never appear as a human approver. The human gate is a
# product guarantee, not a formality; this is a tripwire, not authentication.
_NON_HUMAN_IDENTITIES = frozenset(
    {"ai", "agent", "assistant", "bot", "claude", "cursor", "fable", "llm", "model", "system"}
)


def validate_human_identity(value: str, field_name: str) -> str:
    """Require a plausible human identity string for gated actions."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be a non-empty human identity")
    if cleaned.lower() in _NON_HUMAN_IDENTITIES:
        raise ValueError(
            f"{field_name} must be a human identity, got {cleaned!r}: "
            "AI agents may propose specs but must not approve or decide promotion"
        )
    return cleaned


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    """A research source the brain can cite: paper, article, dataset, or a
    lesson recorded in the paper journal."""

    citation_id: str = Field(default_factory=_new_id)
    source_type: str  # e.g. "paper", "article", "dataset", "journal_lesson"
    title: str
    url: str | None = None
    authors: str | None = None
    retrieved_at: datetime
    claims: list[str] = Field(default_factory=list)
    license_note: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("citation title must be non-empty")
        return v


class StrategySpec(BaseModel):
    """A strategy specification moving through the closed loop.

    ``hook_ref`` names the Python implementation hook as ``"module:function"``.
    Python implements only approved specs; the hook must be deterministic and
    must derive every number from stored data.
    """

    spec_id: str = Field(default_factory=_new_id)
    name: str
    version: int = 1
    status: SpecStatus = SpecStatus.PROPOSED
    promotion_state: PromotionState = PromotionState.UNPROVEN
    description: str
    proposed_by: str  # "human" or an AI proposer label, e.g. "ai:analyst"
    citation_ids: list[str] = Field(default_factory=list)
    factor_dependencies: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    hook_ref: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    approved_by: str | None = None
    approved_at: datetime | None = None
    status_reason: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("spec name must be non-empty")
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"version must be >= 1, got {v}")
        return v


class TestRunRecord(BaseModel):
    """One gate execution against one spec: inputs, outputs, pass/fail, as-of."""

    # Prevent pytest from collecting this Pydantic model as a test class.
    __test__ = False

    test_run_id: str = Field(default_factory=_new_id)
    spec_id: str
    gate_name: GateName
    sequence_index: int  # 0-based position in GATE_ORDER for this run batch
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    passed: bool
    as_of: date
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("sequence_index")
    @classmethod
    def validate_sequence_index(cls, v: int) -> int:
        if not 0 <= v < len(GATE_ORDER):
            raise ValueError(
                f"sequence_index must be in [0, {len(GATE_ORDER) - 1}], got {v}"
            )
        return v


class PromotionDecision(BaseModel):
    """A promote/demote/hold decision with the evidence that justified it."""

    decision_id: str = Field(default_factory=_new_id)
    spec_id: str
    decision: DecisionKind
    from_state: PromotionState
    to_state: PromotionState
    rationale: str
    evidence_test_run_ids: list[str] = Field(default_factory=list)
    evidence_citation_ids: list[str] = Field(default_factory=list)
    journal_entry_ids: list[str] = Field(default_factory=list)
    decided_by: str
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a promotion decision requires a non-empty rationale")
        return v

    @field_validator("decided_by")
    @classmethod
    def validate_decided_by(cls, v: str) -> str:
        return validate_human_identity(v, "decided_by")


class JournalLink(BaseModel):
    """Link between a strategy spec and a paper-journal entry."""

    link_id: str = Field(default_factory=_new_id)
    spec_id: str
    journal_entry_id: str
    relation: str  # e.g. "lesson", "entry", "exit", "review"
    created_at: datetime = Field(default_factory=_utcnow)
