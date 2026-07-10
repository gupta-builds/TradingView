"""Unit tests for individual factor formulas (kill-tests included)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from research_data.factors.etf_baseline import compare_to_benchmark
from research_data.factors.momentum import (
    MIN_SESSIONS,
    SKIP_SESSIONS,
    twelve_minus_one_return,
)
from research_data.factors.quality_fcf import (
    FundamentalInputs,
    composite_scores,
    derive_metrics,
)
from research_data.factors.ranking import ascending_ranks, inverse_ranks
from research_data.factors.safety import realized_volatility_annualized
from research_data.factors.ta_context import (
    bollinger_position,
    build_ta_context,
    drawdown_from_52w_high,
    rsi_14,
    simple_moving_average,
)


# -- momentum -----------------------------------------------------------------


def test_momentum_needs_full_window() -> None:
    assert twelve_minus_one_return([100.0] * (MIN_SESSIONS - 1)) is None


def test_momentum_skips_most_recent_month() -> None:
    # Flat at 100 for the 12-1 window, then a +50% melt-up in the skipped month:
    # the skip means the melt-up must NOT appear in the signal.
    closes = [100.0] * (MIN_SESSIONS - SKIP_SESSIONS) + [150.0] * SKIP_SESSIONS
    assert len(closes) == MIN_SESSIONS
    result = twelve_minus_one_return(closes)
    assert result == pytest.approx(0.0)


def test_momentum_known_value() -> None:
    # Price doubles linearly across the whole window.
    closes = [100.0 + i for i in range(MIN_SESSIONS)]
    expected = closes[-1 - SKIP_SESSIONS] / closes[0] - 1.0
    assert twelve_minus_one_return(closes) == pytest.approx(expected)


# -- ranking --------------------------------------------------------------------


def test_ascending_ranks_with_missing_values() -> None:
    ranks = ascending_ranks({"A": 0.10, "B": None, "C": -0.05, "D": 0.30})
    assert ranks == {"C": 1, "A": 2, "D": 3, "B": None}


def test_inverse_ranks_low_value_gets_top_rank() -> None:
    ranks = inverse_ranks({"LOWVOL": 0.10, "MIDVOL": 0.20, "HIGHVOL": 0.50})
    assert ranks == {"LOWVOL": 3, "MIDVOL": 2, "HIGHVOL": 1}


def test_rank_ties_break_deterministically_by_symbol() -> None:
    assert ascending_ranks({"B": 1.0, "A": 1.0}) == {"A": 1, "B": 2}


# -- safety -----------------------------------------------------------------------


def test_volatility_needs_full_window() -> None:
    assert realized_volatility_annualized([100.0] * 200) is None


def test_constant_prices_have_zero_volatility() -> None:
    vol = realized_volatility_annualized([100.0] * 300)
    assert vol == pytest.approx(0.0)


def test_alternating_returns_volatility() -> None:
    closes = [100.0]
    for i in range(299):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 0.99))
    vol = realized_volatility_annualized(closes)
    assert vol is not None
    # Daily swing of ±1% → annualized vol near 0.01 * sqrt(252) ≈ 0.159.
    assert 0.10 < vol < 0.20


# -- quality / valuation -------------------------------------------------------------


def make_inputs(symbol: str, **overrides) -> FundamentalInputs:
    defaults = dict(
        symbol=symbol,
        as_of=date(2026, 3, 31),
        source="fixture",
        revenue=100e9,
        operating_cash_flow=40e9,
        capex=10e9,
        total_debt=20e9,
        cash_and_equivalents=15e9,
        total_equity=80e9,
        shares_outstanding=1e9,
        operating_margins=[0.30, 0.31, 0.29, 0.30],
    )
    defaults.update(overrides)
    return FundamentalInputs(**defaults)


def test_derive_metrics_formulas() -> None:
    metrics = derive_metrics(make_inputs("AAPL"), price_as_of=200.0)
    # market_cap = 200 * 1e9 = 200e9 ; EV = 200e9 + 20e9 - 15e9 = 205e9
    assert metrics.market_cap == pytest.approx(200e9)
    assert metrics.enterprise_value == pytest.approx(205e9)
    # fcf = 40e9 - 10e9 = 30e9 → fcf_ev ≈ 0.14634 ; fcf_margin = 0.30
    assert metrics.fcf_ev == pytest.approx(30e9 / 205e9)
    assert metrics.fcf_margin == pytest.approx(0.30)
    assert metrics.debt_to_equity == pytest.approx(0.25)
    assert metrics.op_margin_stability is not None


def test_derive_metrics_never_fabricates() -> None:
    metrics = derive_metrics(
        make_inputs("MSFT", operating_cash_flow=None, operating_margins=[]),
        price_as_of=None,
    )
    assert metrics.market_cap is None
    assert metrics.enterprise_value is None
    assert metrics.fcf_ev is None
    assert metrics.fcf_margin is None
    assert metrics.op_margin_stability is None


def test_composite_orders_better_fundamentals_higher() -> None:
    strong = derive_metrics(make_inputs("STRONG"), price_as_of=100.0)
    weak = derive_metrics(
        make_inputs(
            "WEAK",
            operating_cash_flow=12e9,
            total_debt=60e9,
            operating_margins=[0.10, 0.25, 0.05, 0.30],
        ),
        price_as_of=100.0,
    )
    scores = composite_scores({"STRONG": strong, "WEAK": weak})
    assert scores["STRONG"] is not None and scores["WEAK"] is not None
    assert scores["STRONG"] > scores["WEAK"]
    assert 0.0 <= scores["WEAK"] <= scores["STRONG"] <= 100.0


def test_composite_returns_none_without_data() -> None:
    empty = derive_metrics(
        FundamentalInputs(symbol="ETF", as_of=date(2026, 3, 31), source="fixture"),
        price_as_of=None,
    )
    strong = derive_metrics(make_inputs("STRONG"), price_as_of=100.0)
    other = derive_metrics(make_inputs("OTHER", total_debt=30e9), price_as_of=90.0)
    scores = composite_scores({"ETF": empty, "STRONG": strong, "OTHER": other})
    assert scores["ETF"] is None


# -- ETF baseline ----------------------------------------------------------------


def _series(start: date, prices: list[float]) -> list[tuple[date, float]]:
    days = []
    current = start
    while len(days) < len(prices):
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return list(zip(days, prices))


def test_compare_to_benchmark_overlapping_windows() -> None:
    start = date(2025, 1, 6)
    symbol = _series(start, [100.0 * math.exp(0.001 * i) for i in range(300)])
    benchmark = _series(start, [50.0 * math.exp(0.0005 * i) for i in range(300)])
    comparisons = compare_to_benchmark(symbol, benchmark)
    assert [c.window_sessions for c in comparisons] == [63, 126, 252]
    for c in comparisons:
        assert c.symbol_return > c.benchmark_return > 0
        assert c.overlapping_sessions == c.window_sessions + 1


def test_compare_to_benchmark_refuses_thin_overlap() -> None:
    start = date(2026, 5, 1)
    symbol = _series(start, [100.0] * 30)
    benchmark = _series(start, [50.0] * 30)
    assert compare_to_benchmark(symbol, benchmark) == []


# -- TA context (descriptive only) --------------------------------------------------


def test_sma_and_rsi_bounds() -> None:
    closes = [100.0 + (i % 7) for i in range(260)]
    assert simple_moving_average(closes, 50) is not None
    rsi = rsi_14(closes)
    assert rsi is not None and 0.0 <= rsi <= 100.0


def test_rsi_all_gains_is_100() -> None:
    closes = [100.0 * (1.01**i) for i in range(30)]
    assert rsi_14(closes) == pytest.approx(100.0)


def test_bollinger_and_drawdown() -> None:
    closes = [100.0] * 19 + [110.0]
    pos = bollinger_position(closes)
    assert pos is not None and pos > 2.0
    dd = drawdown_from_52w_high([100.0, 120.0, 90.0])
    assert dd == pytest.approx(90.0 / 120.0 - 1.0)


def test_ta_context_is_descriptive_only() -> None:
    context = build_ta_context([100.0 + i * 0.1 for i in range(260)])
    dumped = context.model_dump_json().lower()
    # Guardrail: TA context must not carry action or execution words.
    for forbidden in ("buy", "sell", "accumulate", "reduce", "guaranteed"):
        assert forbidden not in dumped
    assert context.ma_cross == "golden"
    assert context.price_vs_sma_200 == "above"
