"""Tests for the four-gate harness and its statistics."""

from __future__ import annotations

import random
from datetime import date

import duckdb
import pytest

from research_data.brain import (
    BrainStore,
    StrategySpec,
    gate_sequence_passes,
    is_demo_eligible,
    latest_gate_batch,
    record_gate_outcome_decision,
)
from research_data.gates import (
    GateHarness,
    MonteCarloParams,
    OOSParams,
    StrategyReturns,
    WalkForwardParams,
    deflated_sharpe_probability,
    expected_max_sharpe,
    run_deflated_sharpe_gate,
    run_monte_carlo_gate,
    run_oos_gate,
    run_walk_forward_gate,
)
from research_data.gates.metrics import (
    max_drawdown,
    percentile,
    sharpe_annualized,
    total_return,
)

from tests.synthetic import trading_days

AS_OF = date(2026, 6, 30)
SESSIONS = 1200  # enough for 504-train/126-test walk-forward windows


def make_strategy(
    name: str, mean: float, std: float, seed: int = 1, sessions: int = SESSIONS
) -> StrategyReturns:
    rng = random.Random(f"{name}:{seed}")
    dates = trading_days(AS_OF, sessions)
    returns = [rng.gauss(mean, std) for _ in range(sessions)]
    # Monthly rebalance: 20% of the book turns over every 21st session.
    turnover = [0.2 if i % 21 == 0 else 0.0 for i in range(sessions)]
    return StrategyReturns(
        strategy_name=name, dates=dates, gross_returns=returns, turnover=turnover
    )


def benchmark_like(seed: int = 99, sessions: int = SESSIONS) -> list[float]:
    rng = random.Random(f"benchmark:{seed}")
    return [rng.gauss(0.0004, 0.008) for _ in range(sessions)]


EDGE = make_strategy("edge", mean=0.0011, std=0.008)
NOISE = make_strategy("noise", mean=0.0, std=0.010)
LOSER = make_strategy("loser", mean=-0.0012, std=0.010)
BENCHMARK = benchmark_like()


# -- metrics --------------------------------------------------------------------


def test_total_return_and_drawdown_known_values() -> None:
    assert total_return([0.10, -0.10]) == pytest.approx(-0.01)
    assert max_drawdown([0.10, -0.50, 0.20]) == pytest.approx(-0.50)
    assert max_drawdown([0.01, 0.02]) == 0.0


def test_sharpe_none_for_constant_series() -> None:
    assert sharpe_annualized([0.01] * 100) is None


def test_percentile_interpolates() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0) == 1.0
    assert percentile(values, 100) == 4.0
    assert percentile(values, 50) == pytest.approx(2.5)


def test_strategy_returns_validation() -> None:
    days = trading_days(AS_OF, 3)
    with pytest.raises(ValueError, match="equal length"):
        StrategyReturns(
            strategy_name="x", dates=days, gross_returns=[0.0], turnover=[0.0, 0.0, 0.0]
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        StrategyReturns(
            strategy_name="x",
            dates=[days[0], days[0], days[2]],
            gross_returns=[0.0, 0.0, 0.0],
            turnover=[0.0, 0.0, 0.0],
        )
    with pytest.raises(ValueError, match="turnover"):
        StrategyReturns(
            strategy_name="x", dates=days, gross_returns=[0.0] * 3, turnover=[0.0, -0.1, 0.0]
        )


def test_net_returns_subtract_costs_on_turnover_days() -> None:
    days = trading_days(AS_OF, 2)
    strategy = StrategyReturns(
        strategy_name="x", dates=days, gross_returns=[0.01, 0.01], turnover=[1.0, 0.0]
    )
    net = strategy.net_returns(cost_bps_per_side=10.0)
    assert net[0] == pytest.approx(0.01 - 0.001)
    assert net[1] == pytest.approx(0.01)
    assert strategy.trade_count == 1


# -- gate 1: out-of-sample ---------------------------------------------------------


def test_oos_gate_passes_real_edge_and_reports_benchmark() -> None:
    result = run_oos_gate(EDGE, BENCHMARK)
    assert result.passed is True
    assert result.outputs["oos_sharpe"] > 0
    assert "oos_benchmark" in result.outputs
    assert result.outputs["oos_strategy"]["trade_count"] > 0


def test_oos_gate_fails_loser() -> None:
    assert run_oos_gate(LOSER, BENCHMARK).passed is False


def test_oos_gate_fails_closed_on_short_series() -> None:
    short = make_strategy("short", mean=0.002, std=0.005, sessions=100)
    result = run_oos_gate(short, benchmark_like(sessions=100))
    assert result.passed is False
    assert "Insufficient data" in result.notes[0]


# -- gate 2: Monte Carlo -------------------------------------------------------------


def test_monte_carlo_is_deterministic_for_a_seed() -> None:
    a = run_monte_carlo_gate(EDGE, MonteCarloParams(n_simulations=200, seed=7))
    b = run_monte_carlo_gate(EDGE, MonteCarloParams(n_simulations=200, seed=7))
    assert a.outputs == b.outputs


def test_monte_carlo_passes_edge_fails_noise() -> None:
    assert run_monte_carlo_gate(EDGE).passed is True
    assert run_monte_carlo_gate(NOISE).passed is False


def test_monte_carlo_reports_tails() -> None:
    outputs = run_monte_carlo_gate(EDGE).outputs
    assert outputs["tail_annualized_return"] < outputs["median_annualized_return"]
    assert outputs["tail_max_drawdown"] <= 0
    assert 0.0 <= outputs["probability_negative_year"] <= 1.0


# -- gate 3: walk-forward --------------------------------------------------------------


def test_walk_forward_passes_edge_fails_loser() -> None:
    edge_result = run_walk_forward_gate(EDGE, BENCHMARK)
    assert edge_result.passed is True
    assert edge_result.outputs["n_windows"] >= 3
    assert run_walk_forward_gate(LOSER, BENCHMARK).passed is False


def test_walk_forward_fails_closed_without_enough_windows() -> None:
    short = make_strategy("shortwf", mean=0.002, std=0.005, sessions=700)
    result = run_walk_forward_gate(
        short, benchmark_like(sessions=700), WalkForwardParams()
    )
    assert result.passed is False
    assert "Insufficient data" in result.notes[0]


# -- gate 4: deflated Sharpe --------------------------------------------------------------


def test_expected_max_sharpe_grows_with_trials() -> None:
    assert expected_max_sharpe(1, 0.01) == 0.0
    few = expected_max_sharpe(5, 0.01)
    many = expected_max_sharpe(100, 0.01)
    assert 0 < few < many


def test_dsr_single_trial_reduces_to_psr() -> None:
    probability, details = deflated_sharpe_probability(
        EDGE.net_returns(), n_trials=1
    )
    assert probability is not None and probability > 0.95
    assert details["sr0_expected_max"] == 0.0


def test_dsr_deflates_with_many_varied_trials() -> None:
    net = EDGE.net_returns()
    baseline, _ = deflated_sharpe_probability(net, n_trials=1)
    trial_sharpes = [-0.1, 0.0, 0.05, 0.1, 0.15, -0.05]
    deflated, details = deflated_sharpe_probability(
        net, n_trials=500, trial_sharpes=trial_sharpes
    )
    assert deflated is not None and deflated < baseline
    assert details["sr0_expected_max"] > 0


def test_dsr_gate_fails_closed_on_degenerate_series() -> None:
    days = trading_days(AS_OF, 10)
    flat = StrategyReturns(
        strategy_name="flat",
        dates=days,
        gross_returns=[0.0] * 10,
        turnover=[0.0] * 10,
    )
    result = run_deflated_sharpe_gate(flat, n_trials=1)
    assert result.passed is False
    assert "Fails closed" in result.notes[0]


# -- harness ----------------------------------------------------------------------------


@pytest.fixture()
def store() -> BrainStore:
    conn = duckdb.connect(":memory:")
    s = BrainStore(conn)
    s.init_schema()
    return s


def approved_spec(store: BrainStore, name: str) -> StrategySpec:
    spec = StrategySpec(name=name, description="d", proposed_by="ai:analyst")
    store.propose_spec(spec)
    return store.approve_spec(spec.spec_id, approved_by="Anant")


def test_harness_short_circuits_on_first_failure() -> None:
    results = GateHarness().run(LOSER, BENCHMARK, n_trials=1)
    assert len(results) == 1
    assert results[0].gate == "out_of_sample"
    assert results[0].passed is False


def test_harness_runs_all_four_in_order_for_edge() -> None:
    results = GateHarness().run(EDGE, BENCHMARK, n_trials=1)
    assert [r.gate for r in results] == [
        "out_of_sample",
        "monte_carlo",
        "walk_forward",
        "deflated_sharpe",
    ]
    assert all(r.passed for r in results)


def test_harness_rejects_misaligned_benchmark() -> None:
    with pytest.raises(ValueError, match="align"):
        GateHarness().run(EDGE, BENCHMARK[:-5], n_trials=1)


def test_run_and_record_full_promotion_path(store: BrainStore) -> None:
    spec = approved_spec(store, "edge_strategy")
    outcome = GateHarness().run_and_record(
        store, spec.spec_id, EDGE, BENCHMARK, as_of=AS_OF
    )
    assert outcome.all_passed is True
    assert outcome.n_trials == 1
    assert len(outcome.test_run_ids) == 4

    batch = latest_gate_batch(store, spec.spec_id)
    assert gate_sequence_passes(batch) is True

    record_gate_outcome_decision(
        store, spec.spec_id, decided_by="Anant", rationale="all four gates passed"
    )
    assert is_demo_eligible(store, spec.spec_id) is True


def test_run_and_record_failure_is_persisted_not_silent(store: BrainStore) -> None:
    spec = approved_spec(store, "loser_strategy")
    outcome = GateHarness().run_and_record(
        store, spec.spec_id, LOSER, BENCHMARK, as_of=AS_OF
    )
    assert outcome.all_passed is False
    runs = store.list_test_runs(spec.spec_id)
    assert len(runs) == 1  # only the failed OOS gate ran — and it is on record
    assert runs[0].passed is False
    assert is_demo_eligible(store, spec.spec_id) is False


def test_trial_count_grows_across_specs(store: BrainStore) -> None:
    first = approved_spec(store, "first")
    GateHarness().run_and_record(store, first.spec_id, EDGE, BENCHMARK, as_of=AS_OF)
    second = approved_spec(store, "second")
    outcome = GateHarness().run_and_record(
        store, second.spec_id, NOISE, BENCHMARK, as_of=AS_OF
    )
    assert outcome.n_trials == 2  # the brain remembers the first trial
