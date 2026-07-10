"""Score packet models — the typed output of the factor engine.

Every score carries its formula inputs, window, and status so a downstream
reader (human or AI) can verify the number instead of trusting it. Scores
never carry action labels; action vocabulary (WATCH | HOLD | ACCUMULATE |
REDUCE | AVOID | INSUFFICIENT_DATA) belongs to the downstream evidence layer
and paper theses, not to raw factor math.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field

from research_data.models import QualityStatus


class ScoreStatus(str, Enum):
    """Whether a score could be computed from real data."""

    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"


class MomentumScore(BaseModel):
    """12-1 month total-return rank within the universe (Jegadeesh-Titman).

    Formula: P[t-21] / P[t-252] - 1 on trading days, ranked ascending —
    rank == universe_size is the strongest 12-1 return, rank 1 the weakest.
    """

    status: ScoreStatus
    rank: int | None = None
    universe_size: int
    ranked_count: int = 0  # symbols that actually had enough history to rank
    twelve_minus_one_return: float | None = None
    window_start: date | None = None
    window_end: date | None = None
    price_field: str = "adjusted_close"
    context: str = ""


class SafetyScore(BaseModel):
    """Inverse rank of 12-month realized volatility (low vol → high rank).

    Formula: stdev of daily simple returns over the trailing 252 sessions,
    annualized by sqrt(252). Lowest volatility gets rank == universe_size.
    """

    status: ScoreStatus
    rank: int | None = None
    universe_size: int
    ranked_count: int = 0
    realized_vol_annualized: float | None = None
    window_start: date | None = None
    window_end: date | None = None
    context: str = ""


class QualityFCFComponents(BaseModel):
    """Raw inputs behind the quality composite, all as-of a statement period."""

    fcf_ev: float | None = None
    fcf_margin: float | None = None
    op_margin_stability: float | None = None  # stdev of operating margin (lower = steadier)
    debt_to_equity: float | None = None
    enterprise_value: float | None = None
    market_cap: float | None = None
    fundamentals_as_of: date | None = None
    fundamentals_source: str | None = None


class QualityFCFScore(BaseModel):
    """Composite 0-100 of FCF/EV, FCF margin, margin stability, and leverage.

    Weighted rank-average across the universe (weights in factors/quality_fcf.py).
    ETFs and symbols without fundamentals report INSUFFICIENT_DATA — never a
    synthesized value.
    """

    status: ScoreStatus
    value: float | None = Field(default=None, ge=0.0, le=100.0)
    universe_size: int
    ranked_count: int = 0
    components: QualityFCFComponents = Field(default_factory=QualityFCFComponents)
    context: str = ""


class ValuationContext(BaseModel):
    """Cash-based valuation context. FCF/EV is primary; P/E is never the driver."""

    status: ScoreStatus
    fcf_ev: float | None = None
    p_fcf: float | None = None
    sector_note: str = ""
    caveats: list[str] = Field(default_factory=list)


class BaselineWindowComparison(BaseModel):
    """Symbol vs benchmark total return over one overlapping-session window."""

    window_sessions: int
    symbol_return: float
    benchmark_return: float
    overlapping_sessions: int


class EtfBaselineComparison(BaseModel):
    """Comparison against the ETF baseline (default VOO) on overlapping sessions."""

    status: ScoreStatus
    benchmark_symbol: str
    windows: list[BaselineWindowComparison] = Field(default_factory=list)
    context: str = ""


class TAContext(BaseModel):
    """Descriptive technical context ONLY — never drives an action by itself.

    (MA/RSI/Bollinger have no robust standalone out-of-sample evidence; they
    describe price state for the reader. See the strategy-edge research note.)
    """

    sma_50: float | None = None
    sma_200: float | None = None
    price_vs_sma_50: str | None = None  # "above" | "below"
    price_vs_sma_200: str | None = None
    ma_cross: str | None = None  # "golden" | "death" | None
    rsi_14: float | None = None
    bollinger_position: float | None = None  # std devs from the 20-day mean
    drawdown_from_52w_high: float | None = None
    note: str = "Descriptive context only; not an action driver."


class PacketDataQuality(BaseModel):
    """Quality status and the confidence ceiling it imposes downstream."""

    status: QualityStatus
    max_confidence: float = Field(ge=0.0, le=1.0)
    price_rows_used: int = 0
    notes: list[str] = Field(default_factory=list)


class PacketProvenance(BaseModel):
    """Where every number in the packet came from."""

    price_source: str | None = None
    price_field: str = "adjusted_close"
    first_price_date: date | None = None
    last_price_date: date | None = None
    fundamentals_source: str | None = None
    generated_at: datetime


class ScorePacket(BaseModel):
    """Structured factor output for one symbol, as of one date.

    Downstream AI receives this packet; it does not recompute or invent
    numbers. Confidence anywhere downstream is capped by
    ``data_quality.max_confidence``.
    """

    symbol: str
    as_of: date
    universe: list[str]
    momentum_score: MomentumScore
    safety_score: SafetyScore
    quality_fcf_score: QualityFCFScore
    valuation: ValuationContext
    etf_baseline: EtfBaselineComparison
    ta_context: TAContext
    risk_flags: list[str] = Field(default_factory=list)
    data_quality: PacketDataQuality
    provenance: PacketProvenance
