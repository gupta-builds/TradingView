"""Four-gate promotion harness (order fixed, all literature defaults).

1. out-of-sample screening   (Pardo degradation heuristic)
2. Monte Carlo bootstrap     (seeded, reproducible tail check)
3. walk-forward consistency  (rolling windows, no per-window re-optimization)
4. deflated Sharpe ratio     (Bailey & López de Prado; trial count from brain)

Nothing is demo-paper eligible without all four passing in order, a recorded
TestRunRecord per gate, and a human promotion decision.
"""

from research_data.gates.deflated_sharpe import (
    DeflatedSharpeParams,
    deflated_sharpe_probability,
    expected_max_sharpe,
    run_deflated_sharpe_gate,
)
from research_data.gates.harness import (
    GateBatchOutcome,
    GateHarness,
    GateHarnessConfig,
    collect_trial_sharpes,
)
from research_data.gates.metrics import (
    DEFAULT_COST_BPS_PER_SIDE,
    GateResult,
    PerformanceSummary,
    StrategyReturns,
    summarize,
)
from research_data.gates.monte_carlo import MonteCarloParams, run_monte_carlo_gate
from research_data.gates.oos import OOSParams, run_oos_gate
from research_data.gates.walk_forward import WalkForwardParams, run_walk_forward_gate

__all__ = [
    "DEFAULT_COST_BPS_PER_SIDE",
    "DeflatedSharpeParams",
    "GateBatchOutcome",
    "GateHarness",
    "GateHarnessConfig",
    "GateResult",
    "MonteCarloParams",
    "OOSParams",
    "PerformanceSummary",
    "StrategyReturns",
    "WalkForwardParams",
    "collect_trial_sharpes",
    "deflated_sharpe_probability",
    "expected_max_sharpe",
    "run_deflated_sharpe_gate",
    "run_monte_carlo_gate",
    "run_oos_gate",
    "run_walk_forward_gate",
    "summarize",
]
