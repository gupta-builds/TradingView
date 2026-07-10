"""Tests for closed-loop rules: gate ordering, eligibility, hook resolution."""

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest

from research_data.brain import (
    GATE_ORDER,
    BrainLoopError,
    BrainStore,
    GateName,
    PromotionState,
    StrategySpec,
    TestRunRecord,
    gate_sequence_passes,
    is_demo_eligible,
    record_gate_outcome_decision,
    resolve_hook,
)
from research_data.brain.models import DecisionKind

AS_OF = date(2026, 7, 10)


@pytest.fixture()
def store() -> BrainStore:
    conn = duckdb.connect(":memory:")
    s = BrainStore(conn)
    s.init_schema()
    return s


def approved_spec(store: BrainStore, name: str = "momentum_tilt") -> StrategySpec:
    spec = StrategySpec(
        name=name,
        description="test spec",
        proposed_by="ai:analyst",
        params={},
    )
    store.propose_spec(spec)
    return store.approve_spec(spec.spec_id, approved_by="Anant")


def make_batch(spec_id: str, passed_flags: list[bool]) -> list[TestRunRecord]:
    return [
        TestRunRecord(
            spec_id=spec_id,
            gate_name=gate,
            sequence_index=i,
            passed=passed_flags[i],
            as_of=AS_OF,
        )
        for i, gate in enumerate(GATE_ORDER[: len(passed_flags)])
    ]


def test_gate_order_is_fixed() -> None:
    assert [g.value for g in GATE_ORDER] == [
        "out_of_sample",
        "monte_carlo",
        "walk_forward",
        "deflated_sharpe",
    ]


def test_full_passing_batch_passes(store: BrainStore) -> None:
    spec = approved_spec(store)
    batch = make_batch(spec.spec_id, [True, True, True, True])
    assert gate_sequence_passes(batch) is True


def test_partial_or_failed_batches_do_not_pass(store: BrainStore) -> None:
    spec = approved_spec(store)
    assert gate_sequence_passes(make_batch(spec.spec_id, [True, True, True])) is False
    assert gate_sequence_passes(make_batch(spec.spec_id, [True, True, False, True])) is False
    assert gate_sequence_passes([]) is False


def test_out_of_order_batch_does_not_pass(store: BrainStore) -> None:
    spec = approved_spec(store)
    batch = make_batch(spec.spec_id, [True, True, True, True])
    # Swap gate names so the sequence indexes no longer match the fixed order.
    batch[0].gate_name, batch[1].gate_name = batch[1].gate_name, batch[0].gate_name
    assert gate_sequence_passes(batch) is False


def test_promotion_via_recorded_decision(store: BrainStore) -> None:
    spec = approved_spec(store)
    for run in make_batch(spec.spec_id, [True, True, True, True]):
        store.record_test_run(run)

    assert is_demo_eligible(store, spec.spec_id) is False  # no decision yet

    decision = record_gate_outcome_decision(
        store, spec.spec_id, decided_by="Anant", rationale="all gates passed"
    )
    assert decision.decision == DecisionKind.PROMOTE
    assert decision.to_state == PromotionState.DEMO_ELIGIBLE
    assert is_demo_eligible(store, spec.spec_id) is True


def test_failed_batch_cannot_promote(store: BrainStore) -> None:
    spec = approved_spec(store)
    for run in make_batch(spec.spec_id, [True, False]):
        store.record_test_run(run)
    decision = record_gate_outcome_decision(
        store, spec.spec_id, decided_by="Anant", rationale="monte carlo failed"
    )
    assert decision.decision == DecisionKind.HOLD
    assert decision.to_state == PromotionState.UNPROVEN
    assert is_demo_eligible(store, spec.spec_id) is False


def test_later_failed_batch_demotes(store: BrainStore) -> None:
    spec = approved_spec(store)
    for run in make_batch(spec.spec_id, [True, True, True, True]):
        store.record_test_run(run)
    record_gate_outcome_decision(store, spec.spec_id, decided_by="Anant", rationale="passed")
    assert is_demo_eligible(store, spec.spec_id) is True

    # A new (re-test) batch starts at sequence_index 0 and fails at walk-forward.
    for run in make_batch(spec.spec_id, [True, True, False]):
        store.record_test_run(run)
    decision = record_gate_outcome_decision(
        store, spec.spec_id, decided_by="Anant", rationale="walk-forward regression"
    )
    assert decision.decision == DecisionKind.DEMOTE
    assert decision.to_state == PromotionState.DEMOTED
    assert is_demo_eligible(store, spec.spec_id) is False


def test_decision_requires_gate_runs(store: BrainStore) -> None:
    spec = approved_spec(store)
    with pytest.raises(BrainLoopError, match="No gate runs"):
        record_gate_outcome_decision(store, spec.spec_id, decided_by="Anant", rationale="x")


def test_resolve_hook_roundtrip() -> None:
    hook = resolve_hook("research_data.env:load_dotenv")
    assert callable(hook)


@pytest.mark.parametrize("bad_ref", ["no_colon", ":func", "module:", "nope.nope:fn"])
def test_resolve_hook_rejects_bad_refs(bad_ref: str) -> None:
    with pytest.raises(BrainLoopError):
        resolve_hook(bad_ref)
