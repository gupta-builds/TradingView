"""Integration tests for FactorEngine on synthetic DuckDB data."""

from __future__ import annotations

import json
from datetime import date

import duckdb
import pytest

from research_data.factors import FactorEngine, FundamentalInputs, ScoreStatus
from research_data.models import QualityStatus
from research_data.read_api import PriceReadAPI
from research_data.storage import batch_insert_ohlcv, init_db

from tests.synthetic import make_price_records

AS_OF = date(2026, 6, 30)
FULL = 320  # sessions — enough for the 253-session windows
SHORT = 120  # sessions — PARTIAL quality, no momentum/safety rank


@pytest.fixture(scope="module")
def engine_and_packets():
    conn = duckdb.connect(":memory:")
    init_db(conn)
    records = []
    # VOO: benchmark, moderate drift/vol.
    records += make_price_records(
        "VOO", end=AS_OF, sessions=FULL, base_price=400.0,
        daily_drift=0.0004, daily_vol=0.008, asset_type="etf", exchange="NYSE",
    )
    # HIGHMO: strong uptrend → top momentum rank.
    records += make_price_records(
        "AAPL", end=AS_OF, sessions=FULL, base_price=150.0,
        daily_drift=0.0020, daily_vol=0.012,
    )
    # LOWVOL: quiet series → top safety rank.
    records += make_price_records(
        "MSFT", end=AS_OF, sessions=FULL, base_price=300.0,
        daily_drift=0.0002, daily_vol=0.004,
    )
    # WILD: high volatility, negative drift → bottom safety rank + risk flag.
    # seed=4 keeps this walk's 12-1 return below AAPL's (vol 0.035 can out-drift
    # it on other seeds).
    records += make_price_records(
        "TSLA", end=AS_OF, sessions=FULL, base_price=200.0,
        daily_drift=-0.0010, daily_vol=0.035, seed=4,
    )
    # SHORTHIST: not enough sessions for the factor windows.
    records += make_price_records(
        "META", end=AS_OF, sessions=SHORT, base_price=500.0,
        daily_drift=0.0005, daily_vol=0.015,
    )
    batch_insert_ohlcv(conn, records)

    fundamentals = {
        "AAPL": FundamentalInputs(
            symbol="AAPL", as_of=date(2026, 3, 31), source="fixture",
            revenue=400e9, operating_cash_flow=110e9, capex=11e9,
            total_debt=100e9, cash_and_equivalents=60e9, total_equity=70e9,
            shares_outstanding=15e9,
            operating_margins=[0.30, 0.31, 0.30, 0.29],
        ),
        "MSFT": FundamentalInputs(
            symbol="MSFT", as_of=date(2026, 3, 31), source="fixture",
            revenue=250e9, operating_cash_flow=120e9, capex=30e9,
            total_debt=45e9, cash_and_equivalents=80e9, total_equity=240e9,
            shares_outstanding=7.4e9,
            operating_margins=[0.44, 0.45, 0.44, 0.46],
        ),
        # TSLA: deliberately no fundamentals → INSUFFICIENT_DATA path for an equity.
    }

    engine = FactorEngine(PriceReadAPI(conn), benchmark_symbol="VOO")
    universe = ["VOO", "AAPL", "MSFT", "TSLA", "META"]
    packets = engine.compute_packets(universe, AS_OF, fundamentals=fundamentals)
    return engine, {p.symbol: p for p in packets}


def test_every_symbol_gets_a_packet(engine_and_packets) -> None:
    _, packets = engine_and_packets
    assert set(packets) == {"VOO", "AAPL", "MSFT", "TSLA", "META"}


def test_momentum_ranks_reflect_drift(engine_and_packets) -> None:
    _, packets = engine_and_packets
    ranked = {s: p.momentum_score.rank for s, p in packets.items()}
    # 4 rankable (META lacks history); AAPL's strong drift must rank top.
    assert ranked["AAPL"] == 4
    assert packets["AAPL"].momentum_score.twelve_minus_one_return > 0
    assert ranked["META"] is None
    assert packets["META"].momentum_score.status == ScoreStatus.INSUFFICIENT_DATA


def test_safety_ranks_reflect_volatility(engine_and_packets) -> None:
    _, packets = engine_and_packets
    assert packets["MSFT"].safety_score.rank == 4  # lowest vol of 4 rankable
    assert packets["TSLA"].safety_score.rank == 1  # wildest
    assert packets["TSLA"].safety_score.realized_vol_annualized > 0.4


def test_wild_symbol_carries_risk_flags(engine_and_packets) -> None:
    _, packets = engine_and_packets
    flags = " ".join(packets["TSLA"].risk_flags)
    assert "volatility" in flags


def test_quality_scores_only_with_fundamentals(engine_and_packets) -> None:
    _, packets = engine_and_packets
    assert packets["AAPL"].quality_fcf_score.status == ScoreStatus.OK
    assert packets["MSFT"].quality_fcf_score.status == ScoreStatus.OK
    assert 0 <= packets["AAPL"].quality_fcf_score.value <= 100
    # Equity without fundamentals: insufficient, flagged, never fabricated.
    tsla_quality = packets["TSLA"].quality_fcf_score
    assert tsla_quality.status == ScoreStatus.INSUFFICIENT_DATA
    assert tsla_quality.value is None
    # ETF: explicitly not applicable.
    voo_quality = packets["VOO"].quality_fcf_score
    assert voo_quality.status == ScoreStatus.INSUFFICIENT_DATA
    assert "ETF" in voo_quality.context


def test_valuation_derived_from_same_components(engine_and_packets) -> None:
    _, packets = engine_and_packets
    valuation = packets["MSFT"].valuation
    assert valuation.status == ScoreStatus.OK
    assert valuation.fcf_ev == packets["MSFT"].quality_fcf_score.components.fcf_ev
    assert valuation.p_fcf is not None and valuation.p_fcf > 0


def test_etf_baseline_windows_present(engine_and_packets) -> None:
    _, packets = engine_and_packets
    baseline = packets["AAPL"].etf_baseline
    assert baseline.benchmark_symbol == "VOO"
    assert [w.window_sessions for w in baseline.windows] == [63, 126, 252]
    assert packets["VOO"].etf_baseline.context == "This symbol is the benchmark."


def test_data_quality_caps_confidence(engine_and_packets) -> None:
    _, packets = engine_and_packets
    assert packets["AAPL"].data_quality.status == QualityStatus.USABLE
    assert packets["AAPL"].data_quality.max_confidence == 1.0
    meta_quality = packets["META"].data_quality
    assert meta_quality.status == QualityStatus.PARTIAL
    assert meta_quality.max_confidence == 0.7
    assert any("capped" in f for f in packets["META"].risk_flags)


def test_missing_symbol_reports_missing_not_fabricated() -> None:
    conn = duckdb.connect(":memory:")
    init_db(conn)
    batch_insert_ohlcv(
        conn,
        make_price_records("VOO", end=AS_OF, sessions=FULL, base_price=400.0,
                           asset_type="etf", exchange="NYSE"),
    )
    engine = FactorEngine(PriceReadAPI(conn), benchmark_symbol="VOO")
    packets = {p.symbol: p for p in engine.compute_packets(["VOO", "JPM"], AS_OF)}
    jpm = packets["JPM"]
    assert jpm.data_quality.status == QualityStatus.MISSING
    assert jpm.data_quality.max_confidence == 0.0
    assert jpm.momentum_score.status == ScoreStatus.INSUFFICIENT_DATA
    assert jpm.provenance.price_source is None


def test_packets_contain_no_execution_language(engine_and_packets) -> None:
    _, packets = engine_and_packets
    for packet in packets.values():
        dumped = json.dumps(packet.model_dump(mode="json")).lower()
        for forbidden in ('"buy"', '"sell"', "guaranteed", "risk-free", "risk free"):
            assert forbidden not in dumped, f"{packet.symbol}: {forbidden}"


def test_ta_context_never_produces_actions(engine_and_packets) -> None:
    _, packets = engine_and_packets
    for packet in packets.values():
        assert "not an action driver" in packet.ta_context.note.lower()
