"""Closed loop on the PRODUCTION strategy pack (not a test-only hook).

Same shape as tests/test_closed_loop.py, but the spec's hook_ref resolves to
``research_data.strategies.quality_momentum:quality_momentum_tilt_hook`` from
the installed package, fundamentals gate quality eligibility, and the human
approver is the desk's identity string.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest

from research_data.brain import (
    BrainStore,
    Citation,
    JournalLink,
    PromotionState,
    SpecStatus,
    StrategySpec,
    is_demo_eligible,
    record_gate_outcome_decision,
    resolve_hook,
)
from research_data.gates import GateHarness
from research_data.paper import ActionLabel, PaperEngine, PaperStore, ReplayRun, Thesis
from research_data.read_api import PriceReadAPI
from research_data.storage import batch_insert_ohlcv, init_db

from tests.synthetic import (
    make_fundamentals_snapshots,
    make_price_records,
    trading_days,
)

AS_OF = date(2026, 6, 30)
SESSIONS = 1300
UNIVERSE = ["VOO", "AAPL", "MSFT", "AMZN", "GOOGL"]
NOW = datetime(2026, 7, 10, tzinfo=timezone.utc)
HOOK_REF = "research_data.strategies.quality_momentum:quality_momentum_tilt_hook"


@pytest.fixture(scope="module")
def conn():
    conn = duckdb.connect(":memory:")
    init_db(conn)
    profiles = {
        "VOO": (400.0, 0.0004, 0.007, "etf", "NYSE"),
        "AAPL": (150.0, 0.0012, 0.008, "equity", "NASDAQ"),
        "MSFT": (300.0, 0.0009, 0.007, "equity", "NASDAQ"),
        "AMZN": (180.0, 0.0003, 0.010, "equity", "NASDAQ"),
        "GOOGL": (140.0, 0.0002, 0.009, "equity", "NASDAQ"),
    }
    records = []
    for symbol, (base, drift, vol, asset_type, exchange) in profiles.items():
        records += make_price_records(
            symbol, end=AS_OF, sessions=SESSIONS, base_price=base,
            daily_drift=drift, daily_vol=vol, asset_type=asset_type, exchange=exchange,
        )
    batch_insert_ohlcv(conn, records)
    return conn


FUNDAMENTALS = {
    "AAPL": make_fundamentals_snapshots(
        "AAPL", end=AS_OF, fcf_margin=0.25, total_debt=10e9, total_equity=90e9
    ),
    "MSFT": make_fundamentals_snapshots(
        "MSFT", end=AS_OF, fcf_margin=0.22, total_debt=15e9, total_equity=100e9
    ),
    "AMZN": make_fundamentals_snapshots(
        "AMZN", end=AS_OF, fcf_margin=0.06, total_debt=60e9, total_equity=50e9,
        operating_margin=0.08,
    ),
    "GOOGL": make_fundamentals_snapshots(
        "GOOGL", end=AS_OF, fcf_margin=0.18, total_debt=12e9, total_equity=95e9
    ),
}


def test_closed_loop_with_production_hook(conn) -> None:
    brain = BrainStore(conn)
    brain.init_schema()
    paper_store = PaperStore(conn)
    paper_store.init_schema()
    price_api = PriceReadAPI(conn)

    # 1. Citations: momentum (JT 1993) + quality (Novy-Marx 2013).
    momentum_citation = Citation(
        source_type="paper",
        title="Returns to Buying Winners and Selling Losers (Jegadeesh-Titman 1993)",
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=227214",
        retrieved_at=NOW,
        claims=["12-1 month cross-sectional momentum persists out of sample"],
    )
    quality_citation = Citation(
        source_type="paper",
        title="The Other Side of Value: The Gross Profitability Premium (Novy-Marx 2013)",
        url="https://doi.org/10.1016/j.jfineco.2013.01.003",
        retrieved_at=NOW,
        claims=["Profitable, cash-generative firms earn a cross-sectional premium"],
    )
    brain.add_citation(momentum_citation)
    brain.add_citation(quality_citation)

    # 2. Spec cites both and points at the PRODUCTION hook.
    spec = StrategySpec(
        name="quality_momentum_tilt_top2",
        description="Monthly equal-weight tilt into top-2 names by 50/50 "
        "composite of 12-1 momentum percentile and quality_fcf score.",
        proposed_by="ai:analyst",
        citation_ids=[momentum_citation.citation_id, quality_citation.citation_id],
        factor_dependencies=["momentum", "quality_fcf"],
        params={"top_k": 2},
        hook_ref=HOOK_REF,
    )
    brain.propose_spec(spec)
    assert brain.get_spec(spec.spec_id).status == SpecStatus.PROPOSED

    # 3. Human approval (identity string per settled law).
    brain.approve_spec(spec.spec_id, approved_by="anant")

    # 4. The production hook resolves from the installed package.
    hook = resolve_hook(spec.hook_ref)
    dates = trading_days(AS_OF, SESSIONS)
    strategy, benchmark = hook(
        spec.params, price_api, UNIVERSE, dates[0], AS_OF,
        fundamentals_snapshots=FUNDAMENTALS,
    )
    assert strategy.strategy_name == "quality_momentum_tilt"
    assert len(strategy.gross_returns) > 900

    # 5. Four gates in order, recorded.
    outcome = GateHarness().run_and_record(
        brain, spec.spec_id, strategy, benchmark, as_of=AS_OF
    )
    assert [r.gate for r in outcome.results] == [
        "out_of_sample", "monte_carlo", "walk_forward", "deflated_sharpe",
    ]
    assert outcome.all_passed, [
        (r.gate, r.notes) for r in outcome.results if not r.passed
    ]

    # 6. Recorded human promotion decision.
    decision = record_gate_outcome_decision(
        brain, spec.spec_id, decided_by="anant",
        rationale="All four gates passed on the synthetic verification set.",
    )
    assert decision.to_state == PromotionState.DEMO_ELIGIBLE
    assert is_demo_eligible(brain, spec.spec_id) is True

    # 7-8. Pre-approved thesis + replay journal with the same-period VOO figure.
    window = trading_days(AS_OF, 40)
    thesis = Thesis(
        spec_id=spec.spec_id,
        symbol="AAPL",
        action=ActionLabel.ACCUMULATE,
        thesis_text="quality_momentum_tilt_top2 is demo-eligible; AAPL leads the "
        "composite. Small starter size inside the approved test window.",
        invalidation_conditions=["Composite rank drops below universe median."],
        size_fraction=0.10,
        entry_window_start=window[0],
        entry_window_end=window[10],
    )
    paper_store.propose_thesis(thesis)
    paper_store.approve_thesis(thesis.thesis_id, approved_by="anant")

    engine = PaperEngine(paper_store, price_api)
    written = engine.run_replay(
        ReplayRun(
            spec_id=spec.spec_id,
            start_date=window[0],
            end_date=AS_OF,
            description="production-hook closed-loop verification replay",
        )
    )
    exits = [e for e in written if e.entry_type == "exit"]
    assert len(exits) == 1
    assert exits[0].voo_return_same_period is not None

    # 9. Journal lesson links back into the brain — loop closed.
    brain.link_journal(
        JournalLink(
            spec_id=spec.spec_id,
            journal_entry_id=exits[0].entry_id,
            relation="lesson",
        )
    )
    assert (
        brain.list_journal_links(spec.spec_id)[0].journal_entry_id
        == exits[0].entry_id
    )
