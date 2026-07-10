"""Descriptive technical context — NEVER an action driver.

SMA 50/200, RSI-14 (Wilder smoothing), Bollinger position (std devs from the
20-day mean), and drawdown from the 52-week high. These describe price state
for a reader; none of them has robust standalone out-of-sample evidence, so
they are reported as values, not directives (factor-zoo filter).
"""

from __future__ import annotations

import statistics

from research_data.factors.packets import TAContext

RSI_PERIOD = 14
BOLLINGER_PERIOD = 20
SMA_SHORT = 50
SMA_LONG = 200
HIGH_52W_SESSIONS = 252


def simple_moving_average(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def rsi_14(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """Relative Strength Index with Wilder's smoothing. Reported, not acted on."""
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, curr in zip(closes, closes[1:]):
        change = curr - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def bollinger_position(closes: list[float], period: int = BOLLINGER_PERIOD) -> float | None:
    """How many standard deviations the last close sits from the period mean."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    stdev = statistics.stdev(window)
    if stdev == 0:
        return 0.0
    return (closes[-1] - mean) / stdev


def drawdown_from_52w_high(closes: list[float]) -> float | None:
    """Percentage decline of the last close from the trailing 52-week high."""
    if not closes:
        return None
    window = closes[-HIGH_52W_SESSIONS:]
    high = max(window)
    if high <= 0:
        return None
    return closes[-1] / high - 1.0


def build_ta_context(closes: list[float]) -> TAContext:
    """Compute all descriptive fields; anything uncomputable stays None."""
    sma_50 = simple_moving_average(closes, SMA_SHORT)
    sma_200 = simple_moving_average(closes, SMA_LONG)
    last = closes[-1] if closes else None

    price_vs_50 = None
    price_vs_200 = None
    ma_cross = None
    if last is not None and sma_50 is not None:
        price_vs_50 = "above" if last >= sma_50 else "below"
    if last is not None and sma_200 is not None:
        price_vs_200 = "above" if last >= sma_200 else "below"
    if sma_50 is not None and sma_200 is not None:
        ma_cross = "golden" if sma_50 >= sma_200 else "death"

    return TAContext(
        sma_50=sma_50,
        sma_200=sma_200,
        price_vs_sma_50=price_vs_50,
        price_vs_sma_200=price_vs_200,
        ma_cross=ma_cross,
        rsi_14=rsi_14(closes),
        bollinger_position=bollinger_position(closes),
        drawdown_from_52w_high=drawdown_from_52w_high(closes),
    )
