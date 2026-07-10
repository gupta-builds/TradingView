"""Shared return-series types and performance metrics for the gate harness.

Pure Python (statistics.NormalDist covers the distribution math — no scipy).
Every metric here is a plain formula over supplied returns; nothing fetches
data or invents values.
"""

from __future__ import annotations

import math
from datetime import date

from pydantic import BaseModel, Field, model_validator

TRADING_DAYS_PER_YEAR = 252

#: Default one-way transaction cost in basis points (literature-conservative
#: for liquid US large caps / ETFs).
DEFAULT_COST_BPS_PER_SIDE = 5.0


class StrategyReturns(BaseModel):
    """Time-ordered daily strategy returns with turnover for cost accounting.

    ``gross_returns[i]`` is the strategy's return for ``dates[i]``;
    ``turnover[i]`` is the fraction of the portfolio traded that day
    (0.0 = no trade, 1.0 = full rotation). Produced by a spec's Python hook —
    dates must be strictly increasing (time order is a guardrail, not a hint).
    """

    strategy_name: str
    dates: list[date]
    gross_returns: list[float]
    turnover: list[float]

    @model_validator(mode="after")
    def validate_alignment(self) -> "StrategyReturns":
        if not (len(self.dates) == len(self.gross_returns) == len(self.turnover)):
            raise ValueError(
                "dates, gross_returns, and turnover must have equal length"
            )
        for previous, current in zip(self.dates, self.dates[1:]):
            if current <= previous:
                raise ValueError(
                    f"dates must be strictly increasing; {current} follows {previous}"
                )
        for t in self.turnover:
            if t < 0:
                raise ValueError(f"turnover cannot be negative, got {t}")
        return self

    def net_returns(self, cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE) -> list[float]:
        """Gross returns minus linear transaction costs on turnover."""
        cost_rate = cost_bps_per_side / 10_000.0
        return [
            r - t * cost_rate for r, t in zip(self.gross_returns, self.turnover)
        ]

    @property
    def trade_count(self) -> int:
        return sum(1 for t in self.turnover if t > 0)


class PerformanceSummary(BaseModel):
    """Standard honest-reporting block: return, risk, drawdown, activity."""

    periods: int
    total_return: float
    annualized_return: float | None
    sharpe_annualized: float | None
    max_drawdown: float
    trade_count: int | None = None


class GateResult(BaseModel):
    """Outcome of one gate: pass/fail plus every number that drove it."""

    gate: str
    passed: bool
    inputs: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


# -- scalar metrics -------------------------------------------------------------


def total_return(returns: list[float]) -> float:
    compounded = 1.0
    for r in returns:
        compounded *= 1.0 + r
    return compounded - 1.0


def annualized_return(returns: list[float]) -> float | None:
    if not returns:
        return None
    compounded = 1.0 + total_return(returns)
    if compounded <= 0:
        return -1.0  # total loss floor; geometric annualization undefined below 0
    years = len(returns) / TRADING_DAYS_PER_YEAR
    if years <= 0:
        return None
    return compounded ** (1.0 / years) - 1.0


def mean_std(returns: list[float]) -> tuple[float, float]:
    n = len(returns)
    if n < 2:
        return (returns[0] if returns else 0.0, 0.0)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return mean, math.sqrt(variance)


def sharpe_annualized(returns: list[float]) -> float | None:
    """Annualized Sharpe (rf = 0). None when the series has no usable variance."""
    mean, std = mean_std(returns)
    # Near-zero std: constant series can leave tiny float residue from sum()/n
    # (e.g. sum([0.01]*100) is not exactly 1.0 on some platforms).
    if std <= 1e-12:
        return None
    return mean / std * math.sqrt(TRADING_DAYS_PER_YEAR)


def sharpe_per_period(returns: list[float]) -> float | None:
    mean, std = mean_std(returns)
    if std <= 1e-12:
        return None
    return mean / std


def max_drawdown(returns: list[float]) -> float:
    """Most negative peak-to-trough equity decline (0.0 = never below peak)."""
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def skewness(returns: list[float]) -> float:
    """Population skewness g1 = m3 / m2^1.5 (0.0 for degenerate series)."""
    n = len(returns)
    if n < 3:
        return 0.0
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    if m2 == 0:
        return 0.0
    m3 = sum((r - mean) ** 3 for r in returns) / n
    return m3 / m2**1.5


def kurtosis(returns: list[float]) -> float:
    """Population kurtosis g2 = m4 / m2^2 (normal ≈ 3.0; 3.0 for degenerate)."""
    n = len(returns)
    if n < 4:
        return 3.0
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    if m2 == 0:
        return 3.0
    m4 = sum((r - mean) ** 4 for r in returns) / n
    return m4 / m2**2


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in [0, 100]) of a value list."""
    if not values:
        raise ValueError("percentile of empty list")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (pct / 100.0) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(returns: list[float], trade_count: int | None = None) -> PerformanceSummary:
    return PerformanceSummary(
        periods=len(returns),
        total_return=total_return(returns),
        annualized_return=annualized_return(returns),
        sharpe_annualized=sharpe_annualized(returns),
        max_drawdown=max_drawdown(returns),
        trade_count=trade_count,
    )
