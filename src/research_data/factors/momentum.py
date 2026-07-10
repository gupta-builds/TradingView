"""Cross-sectional 12-1 month momentum (Jegadeesh-Titman 1993).

Formula (trading-day approximation of "month -12 to month -2"):

    r_12_1 = P[t-21] / P[t-252] - 1

where P is the daily close series (adjusted when available), t the last
session at or before the as-of date, 21 skipped sessions ≈ the most recent
month (short-term reversal), 252 sessions ≈ 12 months.

Kill condition: fewer than 253 sessions of usable history → no rank, status
INSUFFICIENT_DATA. The score ranks; it never produces an action by itself.
Parameters are literature defaults — not optimized on our data.
"""

from __future__ import annotations

from datetime import date

LOOKBACK_SESSIONS = 252
SKIP_SESSIONS = 21
MIN_SESSIONS = LOOKBACK_SESSIONS + 1


def twelve_minus_one_return(closes: list[float]) -> float | None:
    """12-1 month total return from a time-ordered daily close series.

    Returns None when history is insufficient (< MIN_SESSIONS bars) — the
    caller must surface INSUFFICIENT_DATA, never a substitute value.
    """
    if len(closes) < MIN_SESSIONS:
        return None
    end_price = closes[-1 - SKIP_SESSIONS]
    start_price = closes[-MIN_SESSIONS]
    if start_price <= 0:
        return None
    return end_price / start_price - 1.0


def momentum_window(dates: list[date]) -> tuple[date, date] | None:
    """The (start, end) trading dates the 12-1 return was computed over."""
    if len(dates) < MIN_SESSIONS:
        return None
    return dates[-MIN_SESSIONS], dates[-1 - SKIP_SESSIONS]
