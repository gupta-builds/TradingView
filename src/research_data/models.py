"""Pydantic models, enumerations, and validation rules for the research data system."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class QualityStatus(str, Enum):
    """Classification of data quality for a symbol or record."""

    USABLE = "usable"
    PARTIAL = "partial"
    STALE = "stale"
    MISSING = "missing"
    CONTRADICTORY = "contradictory"
    INSUFFICIENT_DATA = "insufficient_data"


class PriceAdjustment(str, Enum):
    """Type of price adjustment applied to OHLCV data."""

    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"
    SPLIT_DIVIDEND_ADJUSTED = "split_dividend_adjusted"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InsufficientDataError(Exception):
    """Raised when a symbol has fewer rows than required for the requested operation."""

    def __init__(self, symbol: str, rows_available: int, rows_requested: int) -> None:
        self.symbol = symbol
        self.rows_available = rows_available
        self.rows_requested = rows_requested
        super().__init__(
            f"Insufficient data for {symbol}: "
            f"{rows_available} rows available, {rows_requested} requested"
        )


# ---------------------------------------------------------------------------
# Symbol validation pattern
# ---------------------------------------------------------------------------

_SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,10}$")


# ---------------------------------------------------------------------------
# Core OHLCV Record
# ---------------------------------------------------------------------------


class OHLCVRecord(BaseModel):
    """Canonical normalized daily price record with full provenance fields.

    Validation rules enforce:
    - Positive prices (open, high, low, close > 0)
    - high >= open, high >= close, high >= low
    - low <= open, low <= close
    - Non-negative volume (>= 0)
    - Positive adjusted_close when present (> 0)
    - No future dates for trading_date and data_as_of
    - Uppercase ASCII symbol, max 10 characters
    - Non-empty raw_payload_hash
    """

    symbol: str
    asset_type: Literal["equity", "etf"]
    exchange: str | None = None
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float | None = None
    volume: int
    split_factor: float | None = None
    dividend_cash: float | None = None
    price_adjustment: PriceAdjustment
    currency: str = "USD"
    source: str
    source_record_id: str | None = None
    retrieved_at: datetime
    data_as_of: date
    raw_payload_hash: str
    quality_status: QualityStatus = QualityStatus.USABLE

    # --- Field-level validators ---

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        """Symbol must be uppercase ASCII letters only, max 10 chars."""
        if not _SYMBOL_PATTERN.match(v):
            raise ValueError(
                "Symbol must be 1-10 uppercase ASCII letters only, got: " + repr(v)
            )
        return v

    @field_validator("open", "high", "low", "close")
    @classmethod
    def validate_positive_prices(cls, v: float) -> float:
        """Open, high, low, close must be strictly greater than zero."""
        if v <= 0:
            raise ValueError(f"Price must be positive (> 0), got: {v}")
        return v

    @field_validator("volume")
    @classmethod
    def validate_non_negative_volume(cls, v: int) -> int:
        """Volume must be non-negative (>= 0)."""
        if v < 0:
            raise ValueError(f"Volume must be non-negative (>= 0), got: {v}")
        return v

    @field_validator("adjusted_close")
    @classmethod
    def validate_adjusted_close(cls, v: float | None) -> float | None:
        """Adjusted close, if present, must be strictly greater than zero."""
        if v is not None and v <= 0:
            raise ValueError(
                f"Adjusted close must be positive (> 0) when present, got: {v}"
            )
        return v

    @field_validator("raw_payload_hash")
    @classmethod
    def validate_raw_payload_hash(cls, v: str) -> str:
        """Raw payload hash must be a non-empty string."""
        if not v or not v.strip():
            raise ValueError("raw_payload_hash must be a non-empty string")
        return v

    # --- Model-level validators ---

    @model_validator(mode="after")
    def validate_high_low_relationships(self) -> "OHLCVRecord":
        """Validate OHLC price relationships: high >= open/close/low, low <= open/close."""
        # high must be >= open, close, and low
        if self.high < self.open:
            raise ValueError(
                f"high ({self.high}) must be >= open ({self.open})"
            )
        if self.high < self.close:
            raise ValueError(
                f"high ({self.high}) must be >= close ({self.close})"
            )
        if self.high < self.low:
            raise ValueError(
                f"high ({self.high}) must be >= low ({self.low})"
            )
        # low must be <= open and close
        if self.low > self.open:
            raise ValueError(
                f"low ({self.low}) must be <= open ({self.open})"
            )
        if self.low > self.close:
            raise ValueError(
                f"low ({self.low}) must be <= close ({self.close})"
            )
        return self

    @model_validator(mode="after")
    def validate_no_future_dates(self) -> "OHLCVRecord":
        """trading_date and data_as_of cannot be in the future (UTC)."""
        today = datetime.now(timezone.utc).date()
        if self.trading_date > today:
            raise ValueError(
                f"trading_date ({self.trading_date}) cannot be in the future (today is {today})"
            )
        if self.data_as_of > today:
            raise ValueError(
                f"data_as_of ({self.data_as_of}) cannot be in the future (today is {today})"
            )
        return self


# ---------------------------------------------------------------------------
# Provider Models
# ---------------------------------------------------------------------------


class ProviderCapabilities(BaseModel):
    """Describes the capabilities and constraints of a data provider."""

    source_name: str
    asset_classes: list[str]
    supports_daily_ohlcv: bool
    supports_adjusted_prices: bool
    supports_corporate_actions: bool
    min_history_years_free: float | None = None
    rate_limit_per_minute: int | None = None
    requires_api_key: bool
    license_note: str
    experimental: bool = False


class ProviderFetchResult(BaseModel):
    """Result of a provider fetch operation including raw payload and parsed records."""

    symbol: str
    provider: str
    request_url: str
    request_params: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime
    raw_payload: str
    content_hash: str
    records: list[OHLCVRecord] = Field(default_factory=list)
    provider_warnings: list[str] = Field(default_factory=list)
    rate_limit_state: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Data Quality Report
# ---------------------------------------------------------------------------


class DataQualityReport(BaseModel):
    """Per-symbol quality report generated after an ingestion run."""

    report_id: str
    run_id: str
    symbol: str
    source_name: str
    generated_at: datetime
    requested_start_date: date
    requested_end_date: date
    first_available_date: date | None = None
    last_available_date: date | None = None
    expected_sessions: int
    valid_sessions: int
    missing_sessions: list[date] = Field(default_factory=list)
    rejected_records: int
    quality_status: QualityStatus
    confidence_cap: float = Field(ge=0.0, le=1.0)
    issues_json: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Evidence Packet Models
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    """Reference to a specific row in a data table for provenance tracking."""

    table: str
    key: str
    source: str
    retrieved_at: datetime
    data_as_of: date


class DataEvidencePacket(BaseModel):
    """Structured evidence packet with full provenance for downstream AI consumption.

    Serializable as JSON via Pydantic for consumption by any downstream AI framework.
    """

    symbol: str
    as_of: date
    source: str
    data_window: tuple[date, date]
    latest_price_date: date | None = None
    price_adjustment: PriceAdjustment
    rows_available: int
    missing_sessions: list[date] = Field(default_factory=list)
    quality_status: QualityStatus
    confidence_cap: float = Field(ge=0.0, le=1.0)
    benchmark_symbol: str
    benchmark_available: bool
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
