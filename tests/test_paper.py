"""Paper-test contract tests: thesis gate, timed entry, replay journal."""

from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb
import pytest

from research_data.paper import (
    ActionLabel,
    JournalEntry,
    PaperEngine,
    PaperFill,
    PaperMode,
    PaperStore,
    PaperStoreError,
    PositionEffect,
    ReplayRun,
    Thesis,
    ThesisStatus,
)
from research_data.read_api import PriceReadAPI
from research_data.storage import batch_insert_ohlcv, init_db

from tests.synthetic import make_price_records, trading_days

AS_OF = date(2026, 6, 30)
SESSIONS = 130
DATES = trading_days(AS_OF, SESSIONS)  # ~2026-01 → 2026-06


@pytest.fixture()
def env():
    conn = duckdb.connect(":memory:")
    init_db(conn)
    records = make_price_records(
        "AAPL", end=AS_OF, sessions=SESSIONS, base_price=200.0,
        daily_drift=0.001, daily_vol=0.01,
    )
    records += make_price_records(
        "VOO", end=AS_OF, sessions=SESSIONS, base_price=450.0,
        daily_drift=0.0004, daily_vol=0.007, asset_type="etf", exchange="NYSE",
    )
    batch_insert_ohlcv(conn, records)
    store = PaperStore(conn)
    store.init_schema()
    engine = PaperEngine(store, PriceReadAPI(conn))
    return store, engine


def make_thesis(**overrides) -> Thesis:
    defaults = dict(
        symbol="AAPL",
        action=ActionLabel.ACCUMULATE,
        thesis_text="Quality composite rank 2/14 with momentum rank 12/14; "
        "entry sized small pending next filing.",
        invalidation_conditions=["Operating margin deteriorates in next filing."],
        size_fraction=0.10,
        entry_window_start=DATES[10],
        entry_window_end=DATES[20],
        next_review_date=DATES[40],
    )
    defaults.update(overrides)
    return Thesis(**defaults)


# -- model validation -----------------------------------------------------------


def test_thesis_requires_text_and_valid_window() -> None:
    with pytest.raises(ValueError, match="thesis_text"):
        make_thesis(thesis_text="   ")
    with pytest.raises(ValueError, match="entry_window_end"):
        make_thesis(entry_window_start=DATES[20], entry_window_end=DATES[10])
    with pytest.raises(ValueError):
        make_thesis(size_fraction=0.0)
    with pytest.raises(ValueError):
        make_thesis(size_fraction=1.5)


def test_exit_journal_requires_benchmark_return() -> None:
    with pytest.raises(ValueError, match="voo_return_same_period"):
        JournalEntry(
            mode=PaperMode.LIVE,
            entry_type="exit",
            as_of=AS_OF,
            body="closed position",
            realized_return=0.05,
        )


# -- thesis lifecycle -------------------------------------------------------------


def test_thesis_approval_human_gate(env) -> None:
    store, _ = env
    thesis = make_thesis()
    store.propose_thesis(thesis)
    with pytest.raises(ValueError):
        store.approve_thesis(thesis.thesis_id, approved_by="agent")
    approved = store.approve_thesis(thesis.thesis_id, approved_by="Anant")
    assert approved.status == ThesisStatus.APPROVED
    with pytest.raises(PaperStoreError, match="PROPOSED"):
        store.approve_thesis(thesis.thesis_id, approved_by="Anant")


def test_open_fill_requires_approval_and_window(env) -> None:
    store, _ = env
    thesis = make_thesis()
    store.propose_thesis(thesis)

    fill = PaperFill(
        thesis_id=thesis.thesis_id,
        symbol="AAPL",
        position_effect=PositionEffect.OPEN,
        quantity=10.0,
        fill_date=DATES[12],
        fill_price=200.0,
        price_source="synthetic_fixture",
        price_payload_hash="h",
        mode=PaperMode.LIVE,
    )
    with pytest.raises(PaperStoreError, match="APPROVED"):
        store.record_fill(fill)

    store.approve_thesis(thesis.thesis_id, approved_by="Anant")
    outside = fill.model_copy(update={"fill_date": DATES[30], "fill_id": "f2"})
    with pytest.raises(PaperStoreError, match="entry window"):
        store.record_fill(outside)


# -- timed auto-entry ---------------------------------------------------------------


def test_timed_entry_fills_first_session_in_window(env) -> None:
    store, engine = env
    thesis = make_thesis()
    store.propose_thesis(thesis)
    store.approve_thesis(thesis.thesis_id, approved_by="Anant")

    fills = engine.execute_timed_entries(AS_OF, PaperMode.LIVE)
    assert len(fills) == 1
    fill = fills[0]
    assert fill.fill_date == DATES[10]  # first session of the window
    assert fill.position_effect == PositionEffect.OPEN
    assert fill.price_source == "synthetic_fixture"
    assert fill.quantity * fill.fill_price == pytest.approx(100_000 * 0.10)
    assert store.get_thesis(thesis.thesis_id).status == ThesisStatus.EXECUTED

    journal = store.list_journal_entries(thesis_id=thesis.thesis_id)
    assert len(journal) == 1
    assert journal[0].entry_type == "entry"
    assert journal[0].as_of == DATES[10]

    # Idempotent: a second sweep must not double-enter.
    assert engine.execute_timed_entries(AS_OF, PaperMode.LIVE) == []


def test_no_entry_before_window_opens(env) -> None:
    store, engine = env
    thesis = make_thesis(
        entry_window_start=AS_OF + timedelta(days=5),
        entry_window_end=AS_OF + timedelta(days=15),
        next_review_date=None,
    )
    store.propose_thesis(thesis)
    store.approve_thesis(thesis.thesis_id, approved_by="Anant")
    assert engine.execute_timed_entries(AS_OF, PaperMode.LIVE) == []
    assert store.get_thesis(thesis.thesis_id).status == ThesisStatus.APPROVED


def test_non_accumulate_theses_never_auto_enter(env) -> None:
    store, engine = env
    thesis = make_thesis(action=ActionLabel.WATCH)
    store.propose_thesis(thesis)
    store.approve_thesis(thesis.thesis_id, approved_by="Anant")
    assert engine.execute_timed_entries(AS_OF, PaperMode.LIVE) == []


def test_window_without_data_expires_honestly(env) -> None:
    store, engine = env
    # JPM has no stored prices at all.
    thesis = make_thesis(symbol="JPM")
    store.propose_thesis(thesis)
    store.approve_thesis(thesis.thesis_id, approved_by="Anant")
    assert engine.execute_timed_entries(AS_OF, PaperMode.LIVE) == []
    assert store.get_thesis(thesis.thesis_id).status == ThesisStatus.EXPIRED
    journal = store.list_journal_entries(thesis_id=thesis.thesis_id)
    assert len(journal) == 1
    assert "No entry was fabricated" in journal[0].body


# -- replay -------------------------------------------------------------------------


def test_replay_writes_journal_as_if_time_passed(env) -> None:
    store, engine = env
    thesis = make_thesis()
    store.propose_thesis(thesis)
    store.approve_thesis(thesis.thesis_id, approved_by="Anant")

    replay = ReplayRun(
        spec_id=None,
        start_date=DATES[0],
        end_date=AS_OF,
        description="verification replay over H1 2026",
    )
    written = engine.run_replay(replay)

    fills = store.list_fills(thesis.thesis_id)
    assert [f.position_effect for f in fills] == [PositionEffect.OPEN, PositionEffect.CLOSE]
    open_fill, close_fill = fills
    assert close_fill.fill_date == DATES[-1]

    exits = [e for e in written if e.entry_type == "exit"]
    assert len(exits) == 1
    exit_entry = exits[0]
    # Journal-as-if-time-passed: as_of is the simulated exit session.
    assert exit_entry.as_of == DATES[-1]
    assert exit_entry.realized_return == pytest.approx(
        close_fill.fill_price / open_fill.fill_price - 1.0
    )
    assert exit_entry.voo_return_same_period is not None

    assert store.get_replay_run(replay.replay_id).status == "completed"


def test_pending_reviews_jump_ahead_hook(env) -> None:
    store, engine = env
    thesis = make_thesis()
    store.propose_thesis(thesis)
    store.approve_thesis(thesis.thesis_id, approved_by="Anant")
    engine.execute_timed_entries(AS_OF, PaperMode.LIVE)

    due = store.pending_reviews(DATES[40])
    assert len(due) == 1
    assert due[0].thesis_id == thesis.thesis_id
    assert store.pending_reviews(DATES[39]) == []


# -- guardrails -----------------------------------------------------------------------


def test_paper_records_contain_no_execution_language(env) -> None:
    store, engine = env
    thesis = make_thesis()
    store.propose_thesis(thesis)
    store.approve_thesis(thesis.thesis_id, approved_by="Anant")
    engine.run_replay(
        ReplayRun(start_date=DATES[0], end_date=AS_OF, description="sweep")
    )
    for entry in store.list_journal_entries():
        text = json.dumps(entry.model_dump(mode="json")).lower()
        for forbidden in ('"buy"', '"sell"', "guaranteed", "risk-free"):
            assert forbidden not in text
    for fill in store.list_fills():
        assert fill.position_effect in (PositionEffect.OPEN, PositionEffect.CLOSE)


def test_action_vocabulary_is_closed() -> None:
    assert {a.value for a in ActionLabel} == {
        "WATCH", "HOLD", "ACCUMULATE", "REDUCE", "AVOID", "INSUFFICIENT_DATA",
    }
