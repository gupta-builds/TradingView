"""Brain module — the closed research loop (the x-factor of this desk).

citation → proposed spec → human approve → Python hook → four gates →
promote/demote → journal link → next proposal.

AI may propose strategy specs; only a human may approve them; only the
four-gate harness may make a spec demo-paper eligible. Every transition is
persisted with evidence references so the loop is auditable a year from now.

Public surface: models + BrainStore + loop rules. Keep it thin.
"""

from research_data.brain.models import (
    GATE_ORDER,
    Citation,
    GateName,
    JournalLink,
    PromotionDecision,
    PromotionState,
    SpecStatus,
    StrategySpec,
    TestRunRecord,
)
from research_data.brain.store import BrainStore
from research_data.brain.loop import (
    BrainLoopError,
    gate_sequence_passes,
    latest_gate_batch,
    is_demo_eligible,
    record_gate_outcome_decision,
    resolve_hook,
)

__all__ = [
    "GATE_ORDER",
    "BrainLoopError",
    "BrainStore",
    "Citation",
    "GateName",
    "JournalLink",
    "PromotionDecision",
    "PromotionState",
    "SpecStatus",
    "StrategySpec",
    "TestRunRecord",
    "gate_sequence_passes",
    "latest_gate_batch",
    "is_demo_eligible",
    "record_gate_outcome_decision",
    "resolve_hook",
]
