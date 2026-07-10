"""Deterministic cross-sectional ranking helpers shared by factor scorers."""

from __future__ import annotations


def ascending_ranks(values: dict[str, float | None]) -> dict[str, int | None]:
    """Rank symbols 1..K ascending by value (1 = lowest, K = highest).

    Symbols with ``None`` values are unranked (``None``); K is the count of
    rankable symbols, not the universe size. Ties break deterministically by
    symbol name so repeated runs produce identical ranks.
    """
    rankable = sorted(
        ((v, s) for s, v in values.items() if v is not None),
        key=lambda pair: (pair[0], pair[1]),
    )
    ranks: dict[str, int | None] = {s: None for s in values}
    for position, (_, symbol) in enumerate(rankable, start=1):
        ranks[symbol] = position
    return ranks


def inverse_ranks(values: dict[str, float | None]) -> dict[str, int | None]:
    """Rank symbols 1..K descending by value (K = lowest value).

    Used where *low* is good (e.g. realized volatility → safety): the symbol
    with the lowest value receives the highest rank.
    """
    asc = ascending_ranks(values)
    ranked_count = sum(1 for r in asc.values() if r is not None)
    return {
        s: (ranked_count - r + 1 if r is not None else None) for s, r in asc.items()
    }
