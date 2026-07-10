"""Gate 1 — out-of-sample screening.

Time-ordered split (no shuffling — lookahead is a guardrail violation).
The strategy's net-of-cost out-of-sample segment must stand on its own AND
must not collapse relative to in-sample (Pardo-style degradation check).
The same-window benchmark (VOO buy-and-hold) is always reported.

Default pass rule:
    oos_net_sharpe > 0
    AND (in-sample sharpe <= 0 OR oos_sharpe >= 0.5 * in-sample sharpe)
"""

from __future__ import annotations

from dataclasses import dataclass

from research_data.gates.metrics import (
    DEFAULT_COST_BPS_PER_SIDE,
    GateResult,
    StrategyReturns,
    sharpe_annualized,
    summarize,
)


@dataclass(frozen=True)
class OOSParams:
    train_fraction: float = 0.70
    min_oos_sharpe: float = 0.0
    max_degradation: float = 0.50  # OOS must keep ≥ 50% of in-sample Sharpe
    cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE
    min_oos_periods: int = 60  # fewer OOS sessions than this cannot pass


def run_oos_gate(
    strategy: StrategyReturns,
    benchmark_returns: list[float],
    params: OOSParams = OOSParams(),
) -> GateResult:
    """Evaluate the out-of-sample gate. Insufficient data fails closed."""
    net = strategy.net_returns(params.cost_bps_per_side)
    split = int(len(net) * params.train_fraction)
    train, test = net[:split], net[split:]
    inputs = {
        "train_fraction": params.train_fraction,
        "min_oos_sharpe": params.min_oos_sharpe,
        "max_degradation": params.max_degradation,
        "cost_bps_per_side": params.cost_bps_per_side,
        "total_periods": len(net),
        "oos_periods": len(test),
    }

    if len(test) < params.min_oos_periods or len(train) < params.min_oos_periods:
        return GateResult(
            gate="out_of_sample",
            passed=False,
            inputs=inputs,
            outputs={},
            notes=[
                f"Insufficient data: train={len(train)}, oos={len(test)} sessions "
                f"(need >= {params.min_oos_periods} each). Fails closed."
            ],
        )

    is_sharpe = sharpe_annualized(train)
    oos_sharpe = sharpe_annualized(test)
    oos_trades = sum(1 for t in strategy.turnover[split:] if t > 0)
    strategy_summary = summarize(test, trade_count=oos_trades)
    benchmark_summary = summarize(benchmark_returns[split:])

    passed = (
        oos_sharpe is not None
        and oos_sharpe > params.min_oos_sharpe
        and (
            is_sharpe is None
            or is_sharpe <= 0
            or oos_sharpe >= params.max_degradation * is_sharpe
        )
    )

    notes = []
    if oos_sharpe is None:
        notes.append("OOS returns have no variance; Sharpe undefined — fails.")
    if passed and strategy_summary.total_return < benchmark_summary.total_return:
        notes.append(
            "OOS return trails the benchmark buy-and-hold over the same window —"
            " reported for the promotion decision."
        )

    return GateResult(
        gate="out_of_sample",
        passed=bool(passed),
        inputs=inputs,
        outputs={
            "in_sample_sharpe": is_sharpe,
            "oos_sharpe": oos_sharpe,
            "oos_strategy": strategy_summary.model_dump(),
            "oos_benchmark": benchmark_summary.model_dump(),
        },
        notes=notes,
    )
