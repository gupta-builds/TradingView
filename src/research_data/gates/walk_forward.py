"""Gate 3 — walk-forward consistency (Pardo 1992).

Rolling train/test windows advance through time; each test segment is
evaluated net of costs. Parameters are fixed to literature defaults — this
harness does NOT re-optimize per window (our universe is too small for
honest per-window optimization; the gate checks *consistency*, which is the
part of walk-forward that survives at this scale — recorded in the result).

Default pass rule: >= 60% of test windows have positive net return AND the
pooled out-of-window Sharpe is positive.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_data.gates.metrics import (
    DEFAULT_COST_BPS_PER_SIDE,
    GateResult,
    StrategyReturns,
    sharpe_annualized,
    summarize,
    total_return,
)


@dataclass(frozen=True)
class WalkForwardParams:
    train_sessions: int = 504  # ~2 years
    test_sessions: int = 126  # ~6 months
    step_sessions: int = 126
    min_fraction_positive: float = 0.60
    min_pooled_sharpe: float = 0.0
    cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE
    min_windows: int = 3


def run_walk_forward_gate(
    strategy: StrategyReturns,
    benchmark_returns: list[float],
    params: WalkForwardParams = WalkForwardParams(),
) -> GateResult:
    """Roll train/test windows through the net return series."""
    net = strategy.net_returns(params.cost_bps_per_side)
    inputs = {
        "train_sessions": params.train_sessions,
        "test_sessions": params.test_sessions,
        "step_sessions": params.step_sessions,
        "min_fraction_positive": params.min_fraction_positive,
        "min_pooled_sharpe": params.min_pooled_sharpe,
        "cost_bps_per_side": params.cost_bps_per_side,
        "periods": len(net),
        "parameter_note": "parameters fixed to literature defaults; not re-optimized per window",
    }

    windows: list[dict] = []
    pooled: list[float] = []
    start = 0
    while start + params.train_sessions + params.test_sessions <= len(net):
        test_start = start + params.train_sessions
        test_end = test_start + params.test_sessions
        segment = net[test_start:test_end]
        benchmark_segment = benchmark_returns[test_start:test_end]
        windows.append(
            {
                "test_start_index": test_start,
                "test_return": total_return(segment),
                "test_sharpe": sharpe_annualized(segment),
                "benchmark_return": total_return(benchmark_segment),
            }
        )
        pooled.extend(segment)
        start += params.step_sessions

    if len(windows) < params.min_windows:
        return GateResult(
            gate="walk_forward",
            passed=False,
            inputs=inputs,
            outputs={"windows": windows},
            notes=[
                f"Insufficient data: only {len(windows)} walk-forward windows "
                f"(need >= {params.min_windows}). Fails closed."
            ],
        )

    positive = sum(1 for w in windows if w["test_return"] > 0)
    fraction_positive = positive / len(windows)
    pooled_sharpe = sharpe_annualized(pooled)
    pooled_summary = summarize(pooled)

    passed = (
        fraction_positive >= params.min_fraction_positive
        and pooled_sharpe is not None
        and pooled_sharpe > params.min_pooled_sharpe
    )

    return GateResult(
        gate="walk_forward",
        passed=bool(passed),
        inputs=inputs,
        outputs={
            "n_windows": len(windows),
            "fraction_positive": fraction_positive,
            "pooled_sharpe": pooled_sharpe,
            "pooled_summary": pooled_summary.model_dump(),
            "windows": windows,
        },
        notes=(
            []
            if passed
            else [
                f"fraction_positive={fraction_positive:.2f} "
                f"(need >= {params.min_fraction_positive}), "
                f"pooled_sharpe={pooled_sharpe}."
            ]
        ),
    )
