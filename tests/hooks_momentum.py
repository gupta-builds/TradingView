"""Python implementation hook for the closed-loop integration test.

This is what a spec's ``hook_ref`` resolves to: a deterministic function
that turns stored prices into a StrategyReturns series for the gate
harness. Monthly-rebalanced equal-weight tilt into the top-K symbols by
12-1 month momentum. Every number derives from the price frame passed in —
nothing is invented.
"""

from __future__ import annotations

from datetime import date

from research_data.factors.momentum import MIN_SESSIONS, twelve_minus_one_return
from research_data.gates.metrics import StrategyReturns
from research_data.read_api import PriceReadAPI

REBALANCE_EVERY_SESSIONS = 21


def momentum_tilt_hook(
    params: dict,
    price_api: PriceReadAPI,
    universe: list[str],
    start: date,
    end: date,
    benchmark_symbol: str = "VOO",
) -> tuple[StrategyReturns, list[float]]:
    """Build (strategy returns, aligned benchmark returns) from stored prices.

    Assumes the test universe shares one session calendar (synthetic data
    guarantees it); raises if that does not hold rather than aligning by
    guesswork.
    """
    top_k = int(params.get("top_k", 2))
    symbols = [s for s in universe if s != benchmark_symbol]
    records = price_api.get_price_frame(
        symbols=symbols + [benchmark_symbol], start=start, end=end
    )

    closes: dict[str, list[float]] = {s: [] for s in symbols + [benchmark_symbol]}
    dates: dict[str, list[date]] = {s: [] for s in symbols + [benchmark_symbol]}
    for record in records:
        closes[record.symbol].append(record.adjusted_close or record.close)
        dates[record.symbol].append(record.trading_date)

    calendar = dates[benchmark_symbol]
    for symbol in symbols:
        if dates[symbol] != calendar:
            raise ValueError(f"{symbol} calendar differs from benchmark calendar")

    n = len(calendar)
    if n <= MIN_SESSIONS:
        raise ValueError(f"need more than {MIN_SESSIONS} sessions, got {n}")

    strategy_dates: list[date] = []
    gross: list[float] = []
    turnover: list[float] = []
    benchmark_returns: list[float] = []
    holdings: list[str] = []

    for i in range(MIN_SESSIONS, n):
        if (i - MIN_SESSIONS) % REBALANCE_EVERY_SESSIONS == 0:
            momentum = {
                s: twelve_minus_one_return(closes[s][: i + 1]) for s in symbols
            }
            ranked = sorted(
                (s for s in symbols if momentum[s] is not None),
                key=lambda s: (momentum[s], s),
                reverse=True,
            )
            new_holdings = ranked[:top_k]
            changed = set(new_holdings) != set(holdings)
            holdings = new_holdings
            day_turnover = 1.0 if changed else 0.0
        else:
            day_turnover = 0.0

        day_return = (
            sum(closes[s][i] / closes[s][i - 1] - 1.0 for s in holdings) / len(holdings)
            if holdings
            else 0.0
        )
        strategy_dates.append(calendar[i])
        gross.append(day_return)
        turnover.append(day_turnover)
        benchmark_returns.append(
            closes[benchmark_symbol][i] / closes[benchmark_symbol][i - 1] - 1.0
        )

    return (
        StrategyReturns(
            strategy_name="momentum_tilt",
            dates=strategy_dates,
            gross_returns=gross,
            turnover=turnover,
        ),
        benchmark_returns,
    )
