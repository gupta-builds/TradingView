"""ETF baseline comparison — every symbol is judged against VOO first.

Total return over overlapping usable sessions for standard windows
(~3, 6, 12 months of trading days). Refuses to compare when overlap is
insufficient; never interpolates missing sessions.
"""

from __future__ import annotations

from datetime import date

from research_data.factors.packets import BaselineWindowComparison

#: Trading-session windows: ~3 months, ~6 months, ~12 months.
DEFAULT_WINDOWS = (63, 126, 252)


def compare_to_benchmark(
    symbol_series: list[tuple[date, float]],
    benchmark_series: list[tuple[date, float]],
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
) -> list[BaselineWindowComparison]:
    """Compare symbol vs benchmark total return on overlapping sessions.

    Both series are time-ordered (date, close). Only sessions present in BOTH
    series count; a window is produced only when the overlap covers at least
    ``window + 1`` shared sessions. No fill-forward, no fabrication.
    """
    benchmark_by_date = dict(benchmark_series)
    shared = [
        (d, price, benchmark_by_date[d])
        for d, price in symbol_series
        if d in benchmark_by_date
    ]

    comparisons: list[BaselineWindowComparison] = []
    for window in windows:
        if len(shared) < window + 1:
            continue
        window_slice = shared[-(window + 1) :]
        _, sym_start, bench_start = window_slice[0]
        _, sym_end, bench_end = window_slice[-1]
        if sym_start <= 0 or bench_start <= 0:
            continue
        comparisons.append(
            BaselineWindowComparison(
                window_sessions=window,
                symbol_return=sym_end / sym_start - 1.0,
                benchmark_return=bench_end / bench_start - 1.0,
                overlapping_sessions=len(window_slice),
            )
        )
    return comparisons
