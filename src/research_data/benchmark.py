"""Benchmark reporter for data-sanity metrics (not a strategy engine).

Computes return, volatility, drawdown, and excess return versus a configured
ETF baseline. Refuses computation for insufficient or stale data. Never emits
execution language (BUY/SELL/HOLD).

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from research_data.models import OHLCVRecord, QualityStatus


# Forbidden execution-language tokens (whole-word match in outputs)
_EXECUTION_TOKENS = frozenset({"BUY", "SELL", "HOLD", "BUY NOW", "SELL NOW"})

_MIN_SESSIONS = 50


class BenchmarkError(Exception):
    """Raised when benchmark metrics cannot be computed."""

    def __init__(self, symbol: str, reason: str, quality_status: QualityStatus | None = None):
        self.symbol = symbol
        self.reason = reason
        self.quality_status = quality_status
        status_part = f" (quality_status={quality_status.value})" if quality_status else ""
        super().__init__(f"Benchmark refused for {symbol}{status_part}: {reason}")


@dataclass(frozen=True)
class BenchmarkReport:
    """Computed benchmark metrics for a single symbol."""

    symbol: str
    total_return: float
    annualized_return: float
    annualized_volatility: float
    maximum_drawdown: float
    latest_data_date: date
    missing_session_count: int
    benchmark_excess_return: float | None
    quality_label: str
    sessions_used: int
    benchmark_symbol: str
    overlapping_sessions: int

    def to_dict(self) -> dict[str, object]:
        """Serialize metrics for CLI / property tests (no execution language)."""
        return {
            "symbol": self.symbol,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "annualized_volatility": self.annualized_volatility,
            "maximum_drawdown": self.maximum_drawdown,
            "latest_data_date": self.latest_data_date.isoformat(),
            "missing_session_count": self.missing_session_count,
            "benchmark_excess_return": self.benchmark_excess_return,
            "quality_status": self.quality_label,
            "sessions_used": self.sessions_used,
            "benchmark_symbol": self.benchmark_symbol,
            "overlapping_sessions": self.overlapping_sessions,
        }

    def format_text(self) -> str:
        """Human-readable report text without execution language."""
        excess = (
            f"{self.benchmark_excess_return:.6f}"
            if self.benchmark_excess_return is not None
            else "n/a (insufficient overlap)"
        )
        return (
            f"symbol={self.symbol}\n"
            f"total_return={self.total_return:.6f}\n"
            f"annualized_return={self.annualized_return:.6f}\n"
            f"annualized_volatility={self.annualized_volatility:.6f}\n"
            f"maximum_drawdown={self.maximum_drawdown:.6f}\n"
            f"latest_data_date={self.latest_data_date.isoformat()}\n"
            f"missing_session_count={self.missing_session_count}\n"
            f"benchmark_excess_return={excess}\n"
            f"quality_status={self.quality_label}\n"
        )


def map_quality_label(status: QualityStatus) -> str:
    """Map QualityStatus to benchmark output labels (Req 11.5)."""
    if status == QualityStatus.USABLE:
        return "usable"
    if status == QualityStatus.STALE:
        return "stale"
    if status in (QualityStatus.INSUFFICIENT_DATA, QualityStatus.MISSING):
        return "insufficient_data"
    # PARTIAL, CONTRADICTORY
    return "needs_review"


def compute_benchmark(
    symbol: str,
    records: list[OHLCVRecord],
    quality_status: QualityStatus,
    missing_session_count: int,
    benchmark_symbol: str,
    benchmark_records: list[OHLCVRecord] | None = None,
) -> BenchmarkReport:
    """Compute benchmark metrics for a symbol against an ETF baseline.

    Args:
        symbol: Symbol under evaluation.
        records: Time-ordered OHLCV records for the symbol.
        quality_status: Latest quality status for the symbol.
        missing_session_count: Count of missing expected sessions.
        benchmark_symbol: Baseline ETF symbol (default VOO).
        benchmark_records: OHLCV records for the baseline (optional for excess).

    Returns:
        BenchmarkReport with all computable metrics.

    Raises:
        BenchmarkError: When quality status or session count forbids computation.
    """
    _assert_no_execution_language_in_inputs(symbol, benchmark_symbol)

    # Refuse MISSING, INSUFFICIENT_DATA, STALE (Req 11.3)
    if quality_status in (
        QualityStatus.MISSING,
        QualityStatus.INSUFFICIENT_DATA,
        QualityStatus.STALE,
    ):
        raise BenchmarkError(
            symbol,
            "metrics computation refused due to quality status",
            quality_status,
        )

    sorted_records = sorted(records, key=lambda r: r.trading_date)
    if len(sorted_records) < _MIN_SESSIONS:
        raise BenchmarkError(
            symbol,
            f"fewer than {_MIN_SESSIONS} valid sessions "
            f"({len(sorted_records)} available)",
            quality_status,
        )

    closes = [_close_price(r) for r in sorted_records]
    total_return = closes[-1] / closes[0] - 1.0
    n = len(closes)
    years = n / 252.0
    annualized_return = (closes[-1] / closes[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    annualized_volatility = _annualized_volatility(closes)
    maximum_drawdown = _maximum_drawdown(closes)
    latest_data_date = sorted_records[-1].trading_date

    excess: float | None = None
    overlapping = 0
    if benchmark_records:
        excess, overlapping = _benchmark_excess_return(
            sorted_records, benchmark_records
        )
        if overlapping < _MIN_SESSIONS:
            # Refuse excess return but still return other metrics with None excess
            excess = None

    report = BenchmarkReport(
        symbol=symbol,
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        maximum_drawdown=maximum_drawdown,
        latest_data_date=latest_data_date,
        missing_session_count=missing_session_count,
        benchmark_excess_return=excess,
        quality_label=map_quality_label(quality_status),
        sessions_used=n,
        benchmark_symbol=benchmark_symbol,
        overlapping_sessions=overlapping,
    )
    _assert_no_execution_language(report.format_text())
    return report


def _close_price(record: OHLCVRecord) -> float:
    """Prefer adjusted_close when present."""
    if record.adjusted_close is not None:
        return record.adjusted_close
    return record.close


def _daily_returns(closes: list[float]) -> list[float]:
    returns: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] == 0:
            continue
        returns.append(closes[i] / closes[i - 1] - 1.0)
    return returns


def _annualized_volatility(closes: list[float]) -> float:
    rets = _daily_returns(closes)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    variance = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(variance) * math.sqrt(252.0)


def _maximum_drawdown(closes: list[float]) -> float:
    peak = closes[0]
    max_dd = 0.0
    for price in closes:
        if price > peak:
            peak = price
        drawdown = price / peak - 1.0
        if drawdown < max_dd:
            max_dd = drawdown
    return max_dd


def _benchmark_excess_return(
    symbol_records: list[OHLCVRecord],
    benchmark_records: list[OHLCVRecord],
) -> tuple[float | None, int]:
    """Compute excess total return on overlapping sessions only."""
    sym_by_date = {r.trading_date: _close_price(r) for r in symbol_records}
    bm_by_date = {r.trading_date: _close_price(r) for r in benchmark_records}
    overlap_dates = sorted(set(sym_by_date) & set(bm_by_date))
    overlapping = len(overlap_dates)
    if overlapping < _MIN_SESSIONS:
        return None, overlapping

    first, last = overlap_dates[0], overlap_dates[-1]
    sym_ret = sym_by_date[last] / sym_by_date[first] - 1.0
    bm_ret = bm_by_date[last] / bm_by_date[first] - 1.0
    return sym_ret - bm_ret, overlapping


def _assert_no_execution_language(text: str) -> None:
    """Guardrail: refuse to emit execution language in benchmark output."""
    upper = text.upper()
    for token in ("BUY NOW", "SELL NOW"):
        if token in upper:
            raise BenchmarkError("?", f"execution language detected: {token}")
    # Whole-word checks for BUY / SELL / HOLD
    import re

    for token in ("BUY", "SELL", "HOLD"):
        if re.search(rf"\b{token}\b", upper):
            raise BenchmarkError("?", f"execution language detected: {token}")


def _assert_no_execution_language_in_inputs(symbol: str, benchmark_symbol: str) -> None:
    """Symbols themselves are tickers; no-op placeholder for clarity."""
    _ = (symbol, benchmark_symbol)
