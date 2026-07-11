"""Project TestRunRecord batches to the fixed critic whitelist (B1).

Maps live gate output keys → critic-facing names. Extract/rename only —
no recomputation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from research_data.brain.models import GATE_ORDER, GateName, TestRunRecord

#: Critic-facing keys (locked questionnaire B1).
GATE_WHITELIST_KEYS: tuple[str, ...] = (
    "oos_net_sharpe",
    "mc_p5_return",
    "wf_pct_positive",
    "deflated_sharpe_probability",
)


class GateSummaryProjection(BaseModel):
    """Fixed four-key summary for critic / allowlist — never raw inputs/outputs."""

    spec_id: str
    all_passed: bool
    oos_net_sharpe: float | None = None
    mc_p5_return: float | None = None
    wf_pct_positive: float | None = None
    deflated_sharpe_probability: float | None = None
    gate_passed: dict[str, bool] = Field(default_factory=dict)


def project_gate_batch(spec_id: str, runs: list[TestRunRecord]) -> GateSummaryProjection:
    """Project the latest ordered gate batch to the whitelist.

    Missing gates leave their float fields None; ``all_passed`` is False unless
    every gate in ``GATE_ORDER`` is present and passed.
    """
    by_gate = {r.gate_name: r for r in runs}
    gate_passed = {
        g.value: (by_gate[g].passed if g in by_gate else False) for g in GATE_ORDER
    }

    oos = by_gate.get(GateName.OUT_OF_SAMPLE)
    mc = by_gate.get(GateName.MONTE_CARLO)
    wf = by_gate.get(GateName.WALK_FORWARD)
    dsr = by_gate.get(GateName.DEFLATED_SHARPE)

    oos_sharpe = None
    if oos is not None:
        raw = oos.outputs.get("oos_sharpe")
        oos_sharpe = float(raw) if raw is not None else None

    mc_p5 = None
    if mc is not None:
        raw = mc.outputs.get("tail_annualized_return")
        mc_p5 = float(raw) if raw is not None else None

    wf_pct = None
    if wf is not None:
        raw = wf.outputs.get("fraction_positive")
        wf_pct = float(raw) if raw is not None else None

    dsr_p = None
    if dsr is not None:
        raw = dsr.outputs.get("deflated_sharpe_probability")
        dsr_p = float(raw) if raw is not None else None

    all_passed = len(by_gate) == len(GATE_ORDER) and all(
        by_gate[g].passed for g in GATE_ORDER
    )

    return GateSummaryProjection(
        spec_id=spec_id,
        all_passed=all_passed,
        oos_net_sharpe=oos_sharpe,
        mc_p5_return=mc_p5,
        wf_pct_positive=wf_pct,
        deflated_sharpe_probability=dsr_p,
        gate_passed=gate_passed,
    )
