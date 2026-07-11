"""Typed paper-trading records. No execution language, full provenance."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class ActionLabel(str, Enum):
    """The only action vocabulary allowed anywhere in this system."""

    WATCH = "WATCH"
    HOLD = "HOLD"
    ACCUMULATE = "ACCUMULATE"
    REDUCE = "REDUCE"
    AVOID = "AVOID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ThesisStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTED = "executed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PaperMode(str, Enum):
    REPLAY = "replay"  # accelerated historical verification
    LIVE = "live"  # real-calendar paper book


class PositionEffect(str, Enum):
    """Paper fills open or close exposure — no directional trade words."""

    OPEN = "open"
    CLOSE = "close"


class Thesis(BaseModel):
    """A pre-approval contract: why, what, when, and how much.

    Timed auto-entry is only legal inside [entry_window_start,
    entry_window_end] and only after a human approves. ``invalidation_conditions``
    state, up front, what would prove the thesis wrong.
    """

    thesis_id: str = Field(default_factory=_new_id)
    spec_id: str | None = None  # strategy spec this thesis came from, if any
    source_card_id: str | None = None  # EvidenceCard that informed this thesis
    symbol: str
    action: ActionLabel
    thesis_text: str
    invalidation_conditions: list[str] = Field(default_factory=list)
    size_fraction: float = Field(gt=0.0, le=1.0)
    entry_window_start: date
    entry_window_end: date
    entry_rule: dict[str, Any] = Field(
        default_factory=lambda: {"type": "first_session_close"}
    )
    status: ThesisStatus = ThesisStatus.PROPOSED
    proposed_by: str = "human"
    approved_by: str | None = None
    approved_at: datetime | None = None
    next_review_date: date | None = None
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("thesis_text")
    @classmethod
    def validate_thesis_text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("thesis_text must be non-empty — no entry without a thesis")
        return v

    @model_validator(mode="after")
    def validate_window(self) -> "Thesis":
        if self.entry_window_end < self.entry_window_start:
            raise ValueError(
                f"entry_window_end ({self.entry_window_end}) is before "
                f"entry_window_start ({self.entry_window_start})"
            )
        return self


class PaperFill(BaseModel):
    """One paper execution, priced from a stored OHLCV row (provenance kept)."""

    fill_id: str = Field(default_factory=_new_id)
    thesis_id: str
    symbol: str
    position_effect: PositionEffect
    quantity: float = Field(gt=0.0)
    fill_date: date
    fill_price: float = Field(gt=0.0)
    price_source: str  # provider of the daily_ohlcv row used
    price_payload_hash: str  # raw_payload_hash of that row
    mode: PaperMode
    created_at: datetime = Field(default_factory=_utcnow)


class JournalEntry(BaseModel):
    """Journal record; in REPLAY mode ``as_of`` is the simulated date.

    Exits must carry ``voo_return_same_period`` — without the benchmark
    comparison it is impossible to say whether the strategy earned anything
    beyond market exposure.
    """

    entry_id: str = Field(default_factory=_new_id)
    mode: PaperMode
    entry_type: str  # "thesis" | "entry" | "exit" | "review" | "lesson"
    as_of: date
    body: str
    spec_id: str | None = None
    thesis_id: str | None = None
    symbol: str | None = None
    realized_return: float | None = None
    voo_return_same_period: float | None = None
    next_review_date: date | None = None
    created_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def validate_exit_requires_benchmark(self) -> "JournalEntry":
        if self.entry_type == "exit" and self.voo_return_same_period is None:
            raise ValueError(
                "exit journal entries require voo_return_same_period "
                "(benchmark-relative honesty is mandatory)"
            )
        return self


class ReplayRun(BaseModel):
    """One accelerated historical replay over a date range."""

    replay_id: str = Field(default_factory=_new_id)
    spec_id: str | None = None
    start_date: date
    end_date: date
    status: str = "created"  # "created" | "completed"
    description: str = ""
    created_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def validate_range(self) -> "ReplayRun":
        if self.end_date <= self.start_date:
            raise ValueError("replay end_date must be after start_date")
        return self
