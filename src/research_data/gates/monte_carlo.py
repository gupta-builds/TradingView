"""Gate 2 — Monte Carlo bootstrap stress.

Resamples the strategy's net daily returns with replacement (seeded, fully
reproducible) and checks the left tail: if the 5th percentile of resampled
annualized returns is below the floor (default 0.0), the "edge" doesn't
survive path luck and the gate fails. Drawdown tail is reported alongside.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from research_data.gates.metrics import (
    DEFAULT_COST_BPS_PER_SIDE,
    GateResult,
    StrategyReturns,
    annualized_return,
    max_drawdown,
    percentile,
)


@dataclass(frozen=True)
class MonteCarloParams:
    n_simulations: int = 1000
    tail_percentile: float = 5.0
    min_tail_annualized_return: float = 0.0
    seed: int = 42
    cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE
    min_periods: int = 120


def run_monte_carlo_gate(
    strategy: StrategyReturns,
    params: MonteCarloParams = MonteCarloParams(),
) -> GateResult:
    """Bootstrap the net return series; the tail must clear the floor."""
    net = strategy.net_returns(params.cost_bps_per_side)
    inputs = {
        "n_simulations": params.n_simulations,
        "tail_percentile": params.tail_percentile,
        "min_tail_annualized_return": params.min_tail_annualized_return,
        "seed": params.seed,
        "cost_bps_per_side": params.cost_bps_per_side,
        "periods": len(net),
    }

    if len(net) < params.min_periods:
        return GateResult(
            gate="monte_carlo",
            passed=False,
            inputs=inputs,
            outputs={},
            notes=[
                f"Insufficient data: {len(net)} sessions "
                f"(need >= {params.min_periods}). Fails closed."
            ],
        )

    rng = random.Random(params.seed)
    n = len(net)
    sim_annualized: list[float] = []
    sim_drawdowns: list[float] = []
    for _ in range(params.n_simulations):
        path = [net[rng.randrange(n)] for _ in range(n)]
        ann = annualized_return(path)
        sim_annualized.append(ann if ann is not None else -1.0)
        sim_drawdowns.append(max_drawdown(path))

    tail_return = percentile(sim_annualized, params.tail_percentile)
    tail_drawdown = percentile(sim_drawdowns, params.tail_percentile)
    loss_probability = sum(1 for a in sim_annualized if a < 0) / len(sim_annualized)

    passed = tail_return > params.min_tail_annualized_return

    return GateResult(
        gate="monte_carlo",
        passed=passed,
        inputs=inputs,
        outputs={
            "tail_annualized_return": tail_return,
            "median_annualized_return": percentile(sim_annualized, 50.0),
            "tail_max_drawdown": tail_drawdown,
            "probability_negative_year": loss_probability,
        },
        notes=(
            []
            if passed
            else [
                f"{params.tail_percentile:.0f}th percentile annualized return "
                f"{tail_return:.4f} does not clear the floor "
                f"{params.min_tail_annualized_return:.4f}."
            ]
        ),
    )
