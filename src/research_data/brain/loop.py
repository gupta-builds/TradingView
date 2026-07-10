"""Closed-loop rules: gate-order enforcement, eligibility, hook resolution.

The loop this module guards:

    citation → proposed spec → human approve → Python hook → four gates
    → promote/demote → journal link → next proposal

Nothing here computes gate statistics (that lives in ``research_data.gates``);
this module only enforces *when* results count and *how* they change state.
"""

from __future__ import annotations

import importlib
from typing import Callable

from research_data.brain.models import (
    GATE_ORDER,
    DecisionKind,
    PromotionDecision,
    PromotionState,
    SpecStatus,
    TestRunRecord,
)
from research_data.brain.store import BrainStore


class BrainLoopError(Exception):
    """Raised when the closed loop's rules are violated."""


def gate_sequence_passes(runs: list[TestRunRecord]) -> bool:
    """True iff ``runs`` form one complete, ordered, all-passing gate batch.

    Rules (all must hold):
    - exactly one run per gate in ``GATE_ORDER``;
    - sequence indexes match the fixed order (OOS=0 … deflated Sharpe=3);
    - every run passed.

    A short batch (e.g. stopped after a failed gate) never passes.
    """
    if len(runs) != len(GATE_ORDER):
        return False
    ordered = sorted(runs, key=lambda r: r.sequence_index)
    for index, (run, expected_gate) in enumerate(zip(ordered, GATE_ORDER)):
        if run.sequence_index != index or run.gate_name != expected_gate:
            return False
        if not run.passed:
            return False
    return True


def latest_gate_batch(store: BrainStore, spec_id: str) -> list[TestRunRecord]:
    """Return the most recent gate batch for a spec.

    A batch starts at a run with ``sequence_index == 0``; the latest batch is
    everything from the last such run onward (runs are stored in time order).
    """
    runs = store.list_test_runs(spec_id)
    if not runs:
        return []
    start = 0
    for i, run in enumerate(runs):
        if run.sequence_index == 0:
            start = i
    return runs[start:]


def is_demo_eligible(store: BrainStore, spec_id: str) -> bool:
    """Demo-paper eligibility: approved spec + latest full gate batch passed
    + promotion state DEMO_ELIGIBLE (i.e. a recorded human decision).

    All three must hold; test results alone never flip eligibility without a
    recorded decision, and a decision cannot stand without passing gates.
    """
    spec = store.get_spec(spec_id)
    if spec.status != SpecStatus.APPROVED:
        return False
    if spec.promotion_state != PromotionState.DEMO_ELIGIBLE:
        return False
    return gate_sequence_passes(latest_gate_batch(store, spec_id))


def record_gate_outcome_decision(
    store: BrainStore,
    spec_id: str,
    decided_by: str,
    rationale: str,
    journal_entry_ids: list[str] | None = None,
) -> PromotionDecision:
    """Record the promote/demote decision implied by the latest gate batch.

    - full batch, all gates passed  → promote to DEMO_ELIGIBLE
    - anything else (failed/partial) → demote to DEMOTED (from DEMO_ELIGIBLE)
      or hold at UNPROVEN/DEMOTED (state cannot silently improve)

    The decision cites the batch's test-run ids as evidence. ``decided_by``
    must be a human identity — the loop keeps the human in charge.
    """
    spec = store.get_spec(spec_id)
    if spec.status != SpecStatus.APPROVED:
        raise BrainLoopError(
            f"Promotion decisions apply to APPROVED specs only; "
            f"{spec_id} is {spec.status.value}"
        )
    batch = latest_gate_batch(store, spec_id)
    if not batch:
        raise BrainLoopError(f"No gate runs recorded for spec {spec_id}")

    passed = gate_sequence_passes(batch)
    from_state = spec.promotion_state
    if passed:
        decision_kind = DecisionKind.PROMOTE
        to_state = PromotionState.DEMO_ELIGIBLE
        if from_state == PromotionState.DEMO_ELIGIBLE:
            decision_kind = DecisionKind.HOLD
    else:
        if from_state == PromotionState.DEMO_ELIGIBLE:
            decision_kind = DecisionKind.DEMOTE
            to_state = PromotionState.DEMOTED
        else:
            decision_kind = DecisionKind.HOLD
            to_state = from_state

    decision = PromotionDecision(
        spec_id=spec_id,
        decision=decision_kind,
        from_state=from_state,
        to_state=to_state,
        rationale=rationale,
        evidence_test_run_ids=[r.test_run_id for r in batch],
        evidence_citation_ids=spec.citation_ids,
        journal_entry_ids=journal_entry_ids or [],
        decided_by=decided_by,
    )
    store.record_decision(decision)
    return decision


def resolve_hook(hook_ref: str) -> Callable:
    """Resolve a spec's ``"module:function"`` hook reference to a callable.

    The hook is the Python implementation of an approved spec: a deterministic
    function that produces the strategy return series the gates evaluate.
    """
    module_name, sep, attr = hook_ref.partition(":")
    if not sep or not module_name or not attr:
        raise BrainLoopError(
            f"hook_ref must look like 'package.module:function', got {hook_ref!r}"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise BrainLoopError(f"Cannot import hook module {module_name!r}: {e}") from e
    hook = getattr(module, attr, None)
    if not callable(hook):
        raise BrainLoopError(f"Hook {hook_ref!r} does not resolve to a callable")
    return hook
