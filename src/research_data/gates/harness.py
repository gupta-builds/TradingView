"""Four-gate harness: fixed order, short-circuit on failure, recorded runs.

Order is non-negotiable: out-of-sample → Monte Carlo → walk-forward →
deflated Sharpe. A failed gate stops the batch (later gates are not run and
therefore cannot pass); every executed gate is written to the brain as a
TestRunRecord so failures are auditable, never silent.

Demo-paper eligibility additionally requires a recorded human promotion
decision — see ``research_data.brain.loop``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from research_data.brain.models import GateName, TestRunRecord
from research_data.brain.store import BrainStore
from research_data.gates.deflated_sharpe import (
    DeflatedSharpeParams,
    run_deflated_sharpe_gate,
)
from research_data.gates.metrics import (
    TRADING_DAYS_PER_YEAR,
    GateResult,
    StrategyReturns,
)
from research_data.gates.monte_carlo import MonteCarloParams, run_monte_carlo_gate
from research_data.gates.oos import OOSParams, run_oos_gate
from research_data.gates.walk_forward import WalkForwardParams, run_walk_forward_gate


@dataclass(frozen=True)
class GateHarnessConfig:
    oos: OOSParams = field(default_factory=OOSParams)
    monte_carlo: MonteCarloParams = field(default_factory=MonteCarloParams)
    walk_forward: WalkForwardParams = field(default_factory=WalkForwardParams)
    deflated_sharpe: DeflatedSharpeParams = field(default_factory=DeflatedSharpeParams)


@dataclass(frozen=True)
class GateBatchOutcome:
    results: list[GateResult]
    test_run_ids: list[str]
    all_passed: bool
    n_trials: int


class GateHarness:
    """Runs the four gates against a strategy return series."""

    def __init__(self, config: GateHarnessConfig | None = None) -> None:
        self._config = config or GateHarnessConfig()

    def run(
        self,
        strategy: StrategyReturns,
        benchmark_returns: list[float],
        n_trials: int,
        trial_sharpes: list[float] | None = None,
    ) -> list[GateResult]:
        """Run gates in fixed order; stop at the first failure."""
        if len(benchmark_returns) != len(strategy.gross_returns):
            raise ValueError(
                "benchmark_returns must align 1:1 with the strategy series "
                f"({len(benchmark_returns)} vs {len(strategy.gross_returns)})"
            )
        results: list[GateResult] = []

        result = run_oos_gate(strategy, benchmark_returns, self._config.oos)
        results.append(result)
        if not result.passed:
            return results

        result = run_monte_carlo_gate(strategy, self._config.monte_carlo)
        results.append(result)
        if not result.passed:
            return results

        result = run_walk_forward_gate(
            strategy, benchmark_returns, self._config.walk_forward
        )
        results.append(result)
        if not result.passed:
            return results

        results.append(
            run_deflated_sharpe_gate(
                strategy, n_trials, trial_sharpes, self._config.deflated_sharpe
            )
        )
        return results

    def run_and_record(
        self,
        store: BrainStore,
        spec_id: str,
        strategy: StrategyReturns,
        benchmark_returns: list[float],
        as_of: date,
    ) -> GateBatchOutcome:
        """Run the gates and persist every executed gate as a TestRunRecord.

        The deflated-Sharpe trial count comes from the brain itself: every
        spec that ever reached testing counts as one selection-bias trial
        (including this one), and prior recorded OOS Sharpes provide the
        trial-Sharpe variance.
        """
        already_tested = bool(store.list_test_runs(spec_id))
        n_trials = store.count_tested_specs() + (0 if already_tested else 1)
        trial_sharpes = collect_trial_sharpes(store)

        results = self.run(strategy, benchmark_returns, n_trials, trial_sharpes)

        run_ids: list[str] = []
        for index, result in enumerate(results):
            record = TestRunRecord(
                spec_id=spec_id,
                gate_name=GateName(result.gate),
                sequence_index=index,
                inputs=result.inputs,
                outputs={**result.outputs, "notes": result.notes},
                passed=result.passed,
                as_of=as_of,
            )
            run_ids.append(store.record_test_run(record))

        all_passed = len(results) == 4 and all(r.passed for r in results)
        return GateBatchOutcome(
            results=results,
            test_run_ids=run_ids,
            all_passed=all_passed,
            n_trials=n_trials,
        )


def collect_trial_sharpes(store: BrainStore) -> list[float]:
    """Per-period OOS Sharpes from all recorded out-of-sample gate runs.

    These feed the deflation term: the more configurations were tried (and
    the more their Sharpes varied), the higher the bar for the current one.
    """
    sharpes: list[float] = []
    for run in store.list_runs_for_gate(GateName.OUT_OF_SAMPLE):
        value = run.outputs.get("oos_sharpe")
        if isinstance(value, (int, float)):
            sharpes.append(float(value) / math.sqrt(TRADING_DAYS_PER_YEAR))
    return sharpes
