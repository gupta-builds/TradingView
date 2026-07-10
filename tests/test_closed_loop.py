"""The x-factor, end to end:

citation → proposed spec → human approve → Python hook → four gates →
promote → paper thesis → replay journal → lesson → next proposal.

One test walks the entire loop on synthetic stored prices; if any link
breaks (schema, gate order, human gate, journal contract), this fails.
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
from research_data.paper import (
    ActionLabel,
    PaperEngine,
    PaperMode,
    PaperStore,
    ReplayRun,
    Thesis,
)
from research_data.read_api import PriceReadAPI
from research_data.storage import batch_insert_ohlcv, init_db

from tests.synthetic import make_price_records, trading_days

AS_OF = date(2026, 6, 30)
SESSIONS = 1300  # enough history for momentum warm-up + 3 walk-forward windows
UNIVERSE = ["VOO", "AAPL", "MSFT", "AMZN", "GOOGL"]
NOW = datetime(2026, 7, 10, tzinfo=timezone.utc)


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


def test_full_closed_loop(conn) -> None:
    brain = BrainStore(conn)
    brain.init_schema()
    paper_store = PaperStore(conn)
    paper_store.init_schema()
    price_api = PriceReadAPI(conn)

    # 1. Citation enters the brain.
    citation = Citation(
        source_type="paper",
        title="Returns to Buying Winners and Selling Losers (Jegadeesh-Titman 1993)",
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=227214",
        retrieved_at=NOW,
        claims=["12-1 month cross-sectional momentum persists out of sample"],
    )
    brain.add_citation(citation)

    # 2. AI proposes a spec citing it.
    spec = StrategySpec(
        name="momentum_tilt_top2",
        description="Monthly equal-weight tilt into top-2 symbols by 12-1 momentum.",
        proposed_by="ai:analyst",
        citation_ids=[citation.citation_id],
        factor_dependencies=["momentum"],
        params={"top_k": 2},
        hook_ref="tests.hooks_momentum:momentum_tilt_hook",
    )
    brain.propose_spec(spec)
    assert brain.get_spec(spec.spec_id).status == SpecStatus.PROPOSED

    # 3. Human approves (the only way forward).
    brain.approve_spec(spec.spec_id, approved_by="Anant")

    # 4. Python hook implements the approved spec from stored data.
    hook = resolve_hook(spec.hook_ref)
    dates = trading_days(AS_OF, SESSIONS)
    strategy, benchmark = hook(
        spec.params, price_api, UNIVERSE, dates[0], AS_OF
    )
    assert len(strategy.gross_returns) > 900

    # 5. Four gates run in order and are recorded.
    outcome = GateHarness().run_and_record(
        brain, spec.spec_id, strategy, benchmark, as_of=AS_OF
    )
    assert [r.gate for r in outcome.results] == [
        "out_of_sample", "monte_carlo", "walk_forward", "deflated_sharpe",
    ]
    assert outcome.all_passed, [
        (r.gate, r.notes) for r in outcome.results if not r.passed
    ]

    # 6. Promotion is a recorded human decision citing the gate runs.
    decision = record_gate_outcome_decision(
        brain, spec.spec_id, decided_by="Anant",
        rationale="All four gates passed on the synthetic verification set.",
    )
    assert decision.to_state == PromotionState.DEMO_ELIGIBLE
    assert is_demo_eligible(brain, spec.spec_id) is True

    # 7. A pre-approved thesis enters the paper book inside its window.
    window = trading_days(AS_OF, 40)
    thesis = Thesis(
        spec_id=spec.spec_id,
        symbol="AAPL",
        action=ActionLabel.ACCUMULATE,
        thesis_text="Spec momentum_tilt_top2 is demo-eligible; AAPL ranks top "
        "of universe on 12-1 momentum. Small starter size in the test window.",
        invalidation_conditions=["Momentum rank drops below universe median."],
        size_fraction=0.10,
        entry_window_start=window[0],
        entry_window_end=window[10],
    )
    paper_store.propose_thesis(thesis)
    paper_store.approve_thesis(thesis.thesis_id, approved_by="Anant")

    # 8. Accelerated replay: timed entry + exit, journal as-if-time-passed.
    engine = PaperEngine(paper_store, price_api)
    written = engine.run_replay(
        ReplayRun(
            spec_id=spec.spec_id,
            start_date=window[0],
            end_date=AS_OF,
            description="closed-loop verification replay",
        )
    )
    exits = [e for e in written if e.entry_type == "exit"]
    assert len(exits) == 1
    assert exits[0].voo_return_same_period is not None

    # 9. The journal lesson links back into the brain…
    lesson = exits[0]
    brain.link_journal(
        JournalLink(
            spec_id=spec.spec_id,
            journal_entry_id=lesson.entry_id,
            relation="lesson",
        )
    )
    assert brain.list_journal_links(spec.spec_id)[0].journal_entry_id == lesson.entry_id

    # 10. …and feeds the next proposal as a citable source: loop closed.
    lesson_citation = Citation(
        source_type="journal_lesson",
        title="Replay lesson: momentum_tilt_top2 entry behaved as specified",
        retrieved_at=NOW,
        claims=[
            f"Replay realized {lesson.realized_return:+.4%} vs benchmark "
            f"{lesson.voo_return_same_period:+.4%} over the same period."
        ],
    )
    brain.add_citation(lesson_citation)
    next_spec = StrategySpec(
        name="momentum_tilt_top2",
        version=2,
        description="v2: add safety-rank filter before the momentum tilt.",
        proposed_by="ai:analyst",
        citation_ids=[citation.citation_id, lesson_citation.citation_id],
        factor_dependencies=["momentum", "safety"],
        params={"top_k": 2, "min_safety_rank": 2},
        hook_ref="tests.hooks_momentum:momentum_tilt_hook",
    )
    brain.propose_spec(next_spec)
    assert brain.get_spec(next_spec.spec_id).status == SpecStatus.PROPOSED
    # The v2 proposal is unproven until it passes its own gates.
    assert brain.get_spec(next_spec.spec_id).promotion_state == PromotionState.UNPROVEN
