"""Safety score: 12-month realized volatility, inverse-ranked.

Fills the QMJ safety dimension (Asness-Frazzini-Pedersen 2014) and overlaps
the low-volatility / Betting-Against-Beta evidence (Frazzini-Pedersen 2014):

    vol = stdev(daily simple returns over trailing 252 sessions) * sqrt(252)

Lowest volatility in the universe gets the highest rank. A low safety rank is
a risk flag, not a disqualifier. Kill condition: < 253 sessions → no rank,
INSUFFICIENT_DATA.
"""

from __future__ import annotations

import math
import statistics

VOL_WINDOW_SESSIONS = 252
MIN_SESSIONS = VOL_WINDOW_SESSIONS + 1
ANNUALIZATION_FACTOR = math.sqrt(252)

#: Annualized realized vol above this level is flagged as a risk regardless of rank.
HIGH_VOL_FLAG_THRESHOLD = 0.40


def realized_volatility_annualized(closes: list[float]) -> float | None:
    """Annualized stdev of daily simple returns over the trailing 252 sessions.

    Returns None on insufficient history (< 253 bars) or non-positive prices.
    """
    if len(closes) < MIN_SESSIONS:
        return None
    window = closes[-MIN_SESSIONS:]
    returns: list[float] = []
    for prev, curr in zip(window, window[1:]):
        if prev <= 0:
            return None
        returns.append(curr / prev - 1.0)
    if len(returns) < 2:
        return None
    return statistics.stdev(returns) * ANNUALIZATION_FACTOR
