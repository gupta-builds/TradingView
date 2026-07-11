"""Tests for the brain persistence layer (citations, specs, runs, decisions)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest

from research_data.brain import (
    BrainStore,
    Citation,
    GateName,
    JournalLink,
    PromotionDecision,
    PromotionState,
    SpecStatus,
    StrategySpec,
    TestRunRecord,
)
from research_data.brain.models import DecisionKind
from research_data.brain.store import BrainStoreError


NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store() -> BrainStore:
    conn = duckdb.connect(":memory:")
    s = BrainStore(conn)
    s.init_schema()
    return s


def make_citation(**overrides) -> Citation:
    defaults = dict(
        source_type="paper",
        title="Returns to Buying Winners and Selling Losers",
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=227214",
        authors="Jegadeesh, Titman",
        retrieved_at=NOW,
        claims=["12-1 month momentum persists 3-12 months out of sample"],
    )
    defaults.update(overrides)
    return Citation(**defaults)


def make_spec(citation_ids: list[str] | None = None, **overrides) -> StrategySpec:
    defaults = dict(
        name="momentum_tilt",
        version=1,
        description="Rank universe by 12-1 month return; tilt watchlist priority.",
        proposed_by="ai:analyst",
        citation_ids=citation_ids or [],
        factor_dependencies=["momentum"],
        params={"lookback_days": 252, "skip_days": 21},
        hook_ref="research_data.strategies.quality_momentum:quality_momentum_tilt_hook",
    )
    defaults.update(overrides)
    return StrategySpec(**defaults)


def test_citation_roundtrip(store: BrainStore) -> None:
    citation = make_citation()
    store.add_citation(citation)
    loaded = store.get_citation(citation.citation_id)
    assert loaded.title == citation.title
    assert loaded.claims == citation.claims
    assert loaded.retrieved_at == NOW


def test_propose_spec_requires_existing_citations(store: BrainStore) -> None:
    spec = make_spec(citation_ids=["missing-citation"])
    with pytest.raises(BrainStoreError, match="Unknown citation_id"):
        store.propose_spec(spec)


def test_propose_and_get_spec_roundtrip(store: BrainStore) -> None:
    cid = store.add_citation(make_citation())
    spec = make_spec(citation_ids=[cid])
    store.propose_spec(spec)
    loaded = store.get_spec(spec.spec_id)
    assert loaded.status == SpecStatus.PROPOSED
    assert loaded.promotion_state == PromotionState.UNPROVEN
    assert loaded.params == {"lookback_days": 252, "skip_days": 21}
    assert loaded.citation_ids == [cid]


def test_new_spec_cannot_enter_pre_approved(store: BrainStore) -> None:
    spec = make_spec(status=SpecStatus.APPROVED)
    with pytest.raises(BrainStoreError, match="PROPOSED"):
        store.propose_spec(spec)


def test_approve_spec_human_gate(store: BrainStore) -> None:
    spec = make_spec()
    store.propose_spec(spec)
    approved = store.approve_spec(spec.spec_id, approved_by="Anant", approved_at=NOW)
    assert approved.status == SpecStatus.APPROVED
    assert approved.approved_by == "Anant"
    assert approved.approved_at == NOW


@pytest.mark.parametrize("identity", ["", "  ", "ai", "Claude", "AGENT", "cursor"])
def test_non_human_identities_cannot_approve(store: BrainStore, identity: str) -> None:
    spec = make_spec()
    store.propose_spec(spec)
    with pytest.raises(ValueError):
        store.approve_spec(spec.spec_id, approved_by=identity)
    assert store.get_spec(spec.spec_id).status == SpecStatus.PROPOSED


def test_reject_and_retire_transitions(store: BrainStore) -> None:
    spec = make_spec()
    store.propose_spec(spec)
    rejected = store.reject_spec(spec.spec_id, reason="duplicate of v1", decided_by="Anant")
    assert rejected.status == SpecStatus.REJECTED
    # Rejected specs cannot be approved afterwards.
    with pytest.raises(BrainStoreError):
        store.approve_spec(spec.spec_id, approved_by="Anant")

    other = make_spec(name="momentum_tilt_v2", version=2)
    store.propose_spec(other)
    store.approve_spec(other.spec_id, approved_by="Anant")
    retired = store.retire_spec(other.spec_id, reason="superseded", decided_by="Anant")
    assert retired.status == SpecStatus.RETIRED


def test_duplicate_name_version_rejected(store: BrainStore) -> None:
    store.propose_spec(make_spec())
    with pytest.raises(Exception):
        store.propose_spec(make_spec())


def test_test_runs_only_against_approved_specs(store: BrainStore) -> None:
    spec = make_spec()
    store.propose_spec(spec)
    run = TestRunRecord(
        spec_id=spec.spec_id,
        gate_name=GateName.OUT_OF_SAMPLE,
        sequence_index=0,
        passed=True,
        as_of=date(2026, 7, 10),
    )
    with pytest.raises(BrainStoreError, match="APPROVED"):
        store.record_test_run(run)


def test_test_run_roundtrip_and_trial_count(store: BrainStore) -> None:
    spec = make_spec()
    store.propose_spec(spec)
    store.approve_spec(spec.spec_id, approved_by="Anant")
    run = TestRunRecord(
        spec_id=spec.spec_id,
        gate_name=GateName.OUT_OF_SAMPLE,
        sequence_index=0,
        inputs={"train_fraction": 0.7},
        outputs={"oos_sharpe": 0.42},
        passed=True,
        as_of=date(2026, 7, 10),
    )
    store.record_test_run(run)
    runs = store.list_test_runs(spec.spec_id)
    assert len(runs) == 1
    assert runs[0].gate_name == GateName.OUT_OF_SAMPLE
    assert runs[0].outputs == {"oos_sharpe": 0.42}
    assert store.count_tested_specs() == 1


def test_decision_updates_promotion_state(store: BrainStore) -> None:
    spec = make_spec()
    store.propose_spec(spec)
    store.approve_spec(spec.spec_id, approved_by="Anant")
    run_id = store.record_test_run(
        TestRunRecord(
            spec_id=spec.spec_id,
            gate_name=GateName.OUT_OF_SAMPLE,
            sequence_index=0,
            passed=True,
            as_of=date(2026, 7, 10),
        )
    )
    decision = PromotionDecision(
        spec_id=spec.spec_id,
        decision=DecisionKind.PROMOTE,
        from_state=PromotionState.UNPROVEN,
        to_state=PromotionState.DEMO_ELIGIBLE,
        rationale="all four gates passed on fixture data",
        evidence_test_run_ids=[run_id],
        decided_by="Anant",
    )
    store.record_decision(decision)
    assert store.get_spec(spec.spec_id).promotion_state == PromotionState.DEMO_ELIGIBLE
    decisions = store.list_decisions(spec.spec_id)
    assert len(decisions) == 1
    assert decisions[0].evidence_test_run_ids == [run_id]


def test_decision_requires_matching_from_state_and_real_evidence(store: BrainStore) -> None:
    spec = make_spec()
    store.propose_spec(spec)
    store.approve_spec(spec.spec_id, approved_by="Anant")

    mismatched = PromotionDecision(
        spec_id=spec.spec_id,
        decision=DecisionKind.DEMOTE,
        from_state=PromotionState.DEMO_ELIGIBLE,
        to_state=PromotionState.DEMOTED,
        rationale="state mismatch",
        decided_by="Anant",
    )
    with pytest.raises(BrainStoreError, match="from_state"):
        store.record_decision(mismatched)

    phantom_evidence = PromotionDecision(
        spec_id=spec.spec_id,
        decision=DecisionKind.PROMOTE,
        from_state=PromotionState.UNPROVEN,
        to_state=PromotionState.DEMO_ELIGIBLE,
        rationale="cites a run that does not exist",
        evidence_test_run_ids=["no-such-run"],
        decided_by="Anant",
    )
    with pytest.raises(BrainStoreError, match="test_run_id"):
        store.record_decision(phantom_evidence)


def test_decisions_require_human_identity() -> None:
    with pytest.raises(ValueError):
        PromotionDecision(
            spec_id="s",
            decision=DecisionKind.PROMOTE,
            from_state=PromotionState.UNPROVEN,
            to_state=PromotionState.DEMO_ELIGIBLE,
            rationale="gates passed",
            decided_by="ai",
        )


def test_journal_link_roundtrip(store: BrainStore) -> None:
    spec = make_spec()
    store.propose_spec(spec)
    link = JournalLink(spec_id=spec.spec_id, journal_entry_id="journal-1", relation="lesson")
    store.link_journal(link)
    links = store.list_journal_links(spec.spec_id)
    assert len(links) == 1
    assert links[0].journal_entry_id == "journal-1"
