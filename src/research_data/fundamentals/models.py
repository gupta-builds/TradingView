"""Typed fundamentals records with full provenance."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class FundamentalsSnapshot(BaseModel):
    """One statement period for one symbol from one source.

    All monetary fields are in ``currency`` (USD for the V1 universe) and may
    be None when the source did not report them — missing means missing.
    ``capex`` is stored as a positive magnitude (cash spent on PP&E).
    """

    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    source: str  # "fmp" | "sec_edgar" | "fixture"
    period_type: Literal["annual", "quarter"]
    fiscal_period_end: date
    retrieved_at: datetime
    raw_payload_hash: str
    currency: str = "USD"

    revenue: float | None = None
    operating_income: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    total_equity: float | None = None
    shares_outstanding: float | None = None

    @field_validator("raw_payload_hash")
    @classmethod
    def validate_hash(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("raw_payload_hash must be non-empty (provenance required)")
        return v

    @property
    def operating_margin(self) -> float | None:
        if self.operating_income is None or self.revenue is None or self.revenue <= 0:
            return None
        return self.operating_income / self.revenue


class FundamentalsFetchResult(BaseModel):
    """Result of a fundamentals fetch: snapshots + raw payloads for audit.

    ``request_urls`` must already be secret-free (API keys stripped before
    storage — see the clients).
    """

    symbol: str
    source: str
    retrieved_at: datetime
    request_urls: list[str] = Field(default_factory=list)
    raw_payloads: dict[str, str] = Field(default_factory=dict)  # label → raw JSON
    snapshots: list[FundamentalsSnapshot] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
