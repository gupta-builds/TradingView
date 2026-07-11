"""Production quality+momentum strategy pack — offline proof.

Covers: series alignment, no lookahead, ETF/missing-fundamentals eligibility
(INSUFFICIENT_DATA, never fabricated), two-sided turnover accounting, a
synthetic regime where the full four-gate batch passes, and fail-closed
behavior on free-tier-depth (thin) history.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from research_data.brain import BrainStore, StrategySpec
from research_data.brain.loop import gate_sequence_passes, latest_gate_batch
from research_data.gates import GateHarness
from research_data.read_api import PriceReadAPI
from research_data.storage import batch_insert_ohlcv, init_db
from research_data.strategies.quality_momentum import (
    StrategyDataError,
    quality_momentum_tilt_hook,
    run_quality_momentum_study,
)

from tests.synthetic import (
    make_fundamentals_snapshots,
    make_price_records,
    trading_days,
)

AS_OF = date(2026, 6, 30)
SESSIONS = 1300  # momentum warm-up + >= 4 default walk-forward windows
UNIVERSE = ["VOO", "QQQ", "AAPL", "MSFT", "AMZN", "GOOGL", "META"]
PARAMS = {"top_k": 2}

# symbol: (base, drift, vol, asset_type, exchange)
PRICE_PROFILES = {
    "VOO": (400.0, 0.0004, 0.007, "etf", "NYSE"),
    "QQQ": (350.0, 0.0005, 0.008, "etf", "NASDAQ"),
    "AAPL": (150.0, 0.0012, 0.008, "equity", "NASDAQ"),
    "MSFT": (300.0, 0.0009, 0.007, "equity", "NASDAQ"),
    "AMZN": (180.0, 0.0003, 0.010, "equity", "NASDAQ"),
    "GOOGL": (140.0, 0.0002, 0.009, "equity", "NASDAQ"),
    "META": (500.0, 0.0005, 0.009, "equity", "NASDAQ"),
}


def _fundamentals(end: date) -> dict:
    """Quality cross-section: AAPL/MSFT strong, AMZN weak, GOOGL middling,
    META has statements but no computable sub-signal, QQQ/VOO none (ETFs)."""
    return {
        "AAPL": make_fundamentals_snapshots(
            "AAPL", end=end, fcf_margin=0.25, total_debt=10e9, total_equity=90e9
        ),
        "MSFT": make_fundamentals_snapshots(
            "MSFT", end=end, fcf_margin=0.22, total_debt=15e9, total_equity=100e9
        ),
        "AMZN": make_fundamentals_snapshots(
            "AMZN", end=end, fcf_margin=0.06, total_debt=60e9, total_equity=50e9,
            operating_margin=0.08,
        ),
        "GOOGL": make_fundamentals_snapshots(
            "GOOGL", end=end, fcf_margin=0.18, total_debt=12e9, total_equity=95e9
        ),
        "META": make_fundamentals_snapshots(
            "META", end=end,
            omit_cash_flows=True, omit_balance_sheet=True, omit_operating_income=True,
        ),
    }


def _build_db(symbols: list[str], sessions: int) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    init_db(conn)
    records = []
    for symbol in symbols:
        base, drift, vol, asset_type, exchange = PRICE_PROFILES[symbol]
        records += make_price_records(
            symbol, end=AS_OF, sessions=sessions, base_price=base,
            daily_drift=drift, daily_vol=vol, asset_type=asset_type,
            exchange=exchange,
        )
    batch_insert_ohlcv(conn, records)
    return conn


@pytest.fixture(scope="module")
def price_api():
    return PriceReadAPI(_build_db(UNIVERSE, SESSIONS))


@pytest.fixture(scope="module")
def study(price_api):
    dates = trading_days(AS_OF, SESSIONS)
    return run_quality_momentum_study(
        PARAMS, price_api, UNIVERSE, dates[0], AS_OF,
        fundamentals_snapshots=_fundamentals(AS_OF),
    )


def test_series_aligned_and_time_ordered(study) -> None:
    strategy = study.strategy
    assert len(strategy.gross_returns) == len(study.benchmark_returns)
    assert len(strategy.gross_returns) > 900
    # StrategyReturns already validates strictly increasing dates; anchor the
    # start explicitly: first return is the session after the first rebalance.
    calendar = trading_days(AS_OF, SESSIONS)
    assert strategy.dates[0] == calendar[253]
    assert strategy.dates[-1] == AS_OF


def test_no_lookahead_prefix_invariance(price_api) -> None:
    """Truncating the future must not change past decisions or returns."""
    calendar = trading_days(AS_OF, SESSIONS)
    early_end = calendar[900]
    full = run_quality_momentum_study(
        PARAMS, price_api, UNIVERSE, calendar[0], AS_OF,
        fundamentals_snapshots=_fundamentals(AS_OF),
    )
    truncated = run_quality_momentum_study(
        PARAMS, price_api, UNIVERSE, calendar[0], early_end,
        fundamentals_snapshots=_fundamentals(AS_OF),
    )
    n = len(truncated.strategy.gross_returns)
    assert full.strategy.gross_returns[:n] == truncated.strategy.gross_returns
    assert full.strategy.turnover[:n] == truncated.strategy.turnover
    full_holdings = [r.holdings for r in full.rebalances[: len(truncated.rebalances)]]
    assert full_holdings == [r.holdings for r in truncated.rebalances]


def test_etf_quality_is_insufficient_never_selected(study) -> None:
    for record in study.rebalances:
        assert "QQQ" not in record.holdings
        assert "QQQ" not in record.quality_score
        assert "INSUFFICIENT_DATA" in record.skipped["QQQ"]


def test_equity_without_computable_subsignal_skipped(study) -> None:
    """META has statements but no derivable sub-signal → skipped, not imputed."""
    for record in study.rebalances:
        assert "META" not in record.holdings
        assert "INSUFFICIENT_DATA" in record.skipped["META"]


def test_scores_carry_inputs_and_as_of(study) -> None:
    assert study.params["formulas"]  # formulas travel with every study
    scored = [r for r in study.rebalances if r.holdings]
    assert scored
    for record in scored:
        for symbol in record.holdings:
            assert symbol in record.momentum_12_1
            assert symbol in record.quality_score
            assert symbol in record.composite
            assert record.fundamentals_as_of[symbol] <= record.as_of


def test_entry_from_cash_charges_one_side(study) -> None:
    first_traded = next(i for i, t in enumerate(study.strategy.turnover) if t > 0)
    assert study.strategy.turnover[first_traded] == pytest.approx(1.0)
    assert all(t >= 0.0 for t in study.strategy.turnover)


def test_full_gate_batch_passes_on_favorable_regime(study) -> None:
    """Capability proof: on long favorable synthetic data the production pack
    clears all four gates at unchanged literature defaults."""
    conn = duckdb.connect(":memory:")
    brain = BrainStore(conn)
    brain.init_schema()
    spec = StrategySpec(
        name="quality_momentum_tilt_test",
        description="gate capability check",
        proposed_by="ai:analyst",
        params=PARAMS,
        hook_ref="research_data.strategies.quality_momentum:quality_momentum_tilt_hook",
    )
    brain.propose_spec(spec)
    brain.approve_spec(spec.spec_id, approved_by="anant")
    outcome = GateHarness().run_and_record(
        brain, spec.spec_id, study.strategy, study.benchmark_returns, as_of=AS_OF
    )
    assert [r.gate for r in outcome.results] == [
        "out_of_sample", "monte_carlo", "walk_forward", "deflated_sharpe",
    ]
    assert outcome.all_passed, [
        (r.gate, r.notes) for r in outcome.results if not r.passed
    ]


def test_thin_history_fails_closed_and_is_recorded() -> None:
    """~400 sessions (free-tier depth): the hook still builds an honest series
    but the gate batch fails closed and the failure is recorded — never
    silently passed, never padded with invented history."""
    symbols = ["VOO", "AAPL", "MSFT", "AMZN"]
    price_api = PriceReadAPI(_build_db(symbols, 400))
    dates = trading_days(AS_OF, 400)
    strategy, benchmark = quality_momentum_tilt_hook(
        PARAMS, price_api, symbols, dates[0], AS_OF,
        fundamentals_snapshots=_fundamentals(AS_OF),
    )
    # first rebalance decision at session 252; returns emitted from 253 on
    assert len(strategy.gross_returns) == 400 - 253

    conn = duckdb.connect(":memory:")
    brain = BrainStore(conn)
    brain.init_schema()
    spec = StrategySpec(
        name="quality_momentum_tilt_thin",
        description="thin-history fail-closed check",
        proposed_by="ai:analyst",
        params=PARAMS,
        hook_ref="research_data.strategies.quality_momentum:quality_momentum_tilt_hook",
    )
    brain.propose_spec(spec)
    brain.approve_spec(spec.spec_id, approved_by="anant")
    outcome = GateHarness().run_and_record(
        brain, spec.spec_id, strategy, benchmark, as_of=AS_OF
    )
    assert not outcome.all_passed
    assert len(outcome.results) < 4  # stopped at the first failed gate
    assert not outcome.results[-1].passed
    batch = latest_gate_batch(brain, spec.spec_id)
    assert batch  # the failure is on the record
    assert gate_sequence_passes(batch) is False


def test_benchmark_history_below_momentum_window_raises() -> None:
    symbols = ["VOO", "AAPL", "MSFT", "AMZN"]
    price_api = PriceReadAPI(_build_db(symbols, 200))
    dates = trading_days(AS_OF, 200)
    with pytest.raises(StrategyDataError, match="[Ff]ails closed"):
        quality_momentum_tilt_hook(
            PARAMS, price_api, symbols, dates[0], AS_OF,
            fundamentals_snapshots=_fundamentals(AS_OF),
        )


def test_cross_section_of_one_holds_cash() -> None:
    """With fundamentals for a single name there is no cross-section: the
    book stays in cash at exactly 0.0 — no rank is invented for one symbol."""
    symbols = ["VOO", "AAPL", "MSFT", "AMZN"]
    price_api = PriceReadAPI(_build_db(symbols, 400))
    dates = trading_days(AS_OF, 400)
    study = run_quality_momentum_study(
        PARAMS, price_api, symbols, dates[0], AS_OF,
        fundamentals_snapshots={"AAPL": _fundamentals(AS_OF)["AAPL"]},
    )
    assert all(r.holdings == [] for r in study.rebalances)
    assert all(g == 0.0 for g in study.strategy.gross_returns)
    assert all("_cross_section" in r.skipped for r in study.rebalances)
