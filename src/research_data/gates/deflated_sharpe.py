"""Gate 4 — deflated Sharpe ratio (Bailey & López de Prado 2014, SSRN 2460551).

The best backtest among N tried configurations has an inflated Sharpe. The
DSR asks: given how many trials were run (from brain test-run records) and
the non-normality of the returns, what is the probability that the true
Sharpe exceeds the expected maximum Sharpe of N skill-less trials?

    DSR = Phi( ((SR_hat - SR0) * sqrt(T - 1)) /
               sqrt(1 - g3*SR_hat + ((g4 - 1)/4) * SR_hat^2) )

with SR_hat the per-period Sharpe, T the number of returns, g3 skewness,
g4 (non-excess) kurtosis, and SR0 the expected max trial Sharpe:

    SR0 = sqrt(V[SR_trials]) * ((1-γ) * Z^-1(1 - 1/N) + γ * Z^-1(1 - 1/(N·e)))

γ = Euler-Mascheroni. With one trial (or no trial-Sharpe variance) SR0 = 0
and the DSR reduces to the probabilistic Sharpe ratio against 0.

Default pass rule: DSR >= 0.95.
"""

from __future__ import annotations

import math
import statistics as stats_mod
from dataclasses import dataclass

from research_data.gates.metrics import (
    DEFAULT_COST_BPS_PER_SIDE,
    GateResult,
    StrategyReturns,
    kurtosis,
    mean_std,
    skewness,
)

EULER_MASCHERONI = 0.5772156649015329
_NORMAL = stats_mod.NormalDist()


def expected_max_sharpe(n_trials: int, variance_trial_sharpes: float) -> float:
    """E[max SR] across n skill-less trials with the given SR variance."""
    if n_trials <= 1 or variance_trial_sharpes <= 0:
        return 0.0
    z1 = _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(variance_trial_sharpes) * (
        (1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2
    )


def deflated_sharpe_probability(
    returns: list[float],
    n_trials: int,
    trial_sharpes: list[float] | None = None,
) -> tuple[float | None, dict]:
    """DSR probability and its intermediate values (for the audit trail).

    ``trial_sharpes`` are per-period Sharpes of other tried configurations
    (from brain test runs); their variance drives the deflation term. Without
    at least two, SR0 falls back to 0 (pure PSR — no selection-bias credit is
    *added*, none is forgiven).
    """
    t = len(returns)
    if t < 3:
        return None, {"reason": f"only {t} returns; need >= 3"}
    mean, std = mean_std(returns)
    if std == 0:
        return None, {"reason": "returns have no variance; Sharpe undefined"}
    sr_hat = mean / std
    g3 = skewness(returns)
    g4 = kurtosis(returns)

    variance_trials = 0.0
    if trial_sharpes is not None and len(trial_sharpes) >= 2:
        variance_trials = stats_mod.pvariance(trial_sharpes)
    sr0 = expected_max_sharpe(n_trials, variance_trials)

    denominator_sq = 1.0 - g3 * sr_hat + ((g4 - 1.0) / 4.0) * sr_hat**2
    if denominator_sq <= 0:
        return None, {
            "reason": "non-normality adjustment is degenerate for this series",
            "sr_hat": sr_hat,
            "skewness": g3,
            "kurtosis": g4,
        }
    z = (sr_hat - sr0) * math.sqrt(t - 1) / math.sqrt(denominator_sq)
    probability = _NORMAL.cdf(z)
    return probability, {
        "sr_hat_per_period": sr_hat,
        "sr0_expected_max": sr0,
        "n_trials": n_trials,
        "variance_trial_sharpes": variance_trials,
        "skewness": g3,
        "kurtosis": g4,
        "t_periods": t,
        "z_statistic": z,
    }


@dataclass(frozen=True)
class DeflatedSharpeParams:
    min_probability: float = 0.95
    cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE


def run_deflated_sharpe_gate(
    strategy: StrategyReturns,
    n_trials: int,
    trial_sharpes: list[float] | None = None,
    params: DeflatedSharpeParams = DeflatedSharpeParams(),
) -> GateResult:
    """The DSR probability must clear ``min_probability`` (default 0.95)."""
    net = strategy.net_returns(params.cost_bps_per_side)
    probability, details = deflated_sharpe_probability(net, n_trials, trial_sharpes)
    inputs = {
        "min_probability": params.min_probability,
        "cost_bps_per_side": params.cost_bps_per_side,
        "n_trials": n_trials,
        "n_trial_sharpes_provided": len(trial_sharpes or []),
    }
    if probability is None:
        return GateResult(
            gate="deflated_sharpe",
            passed=False,
            inputs=inputs,
            outputs=details,
            notes=[f"DSR undefined: {details.get('reason', 'unknown')}. Fails closed."],
        )
    passed = probability >= params.min_probability
    return GateResult(
        gate="deflated_sharpe",
        passed=passed,
        inputs=inputs,
        outputs={"deflated_sharpe_probability": probability, **details},
        notes=(
            []
            if passed
            else [
                f"DSR probability {probability:.4f} < required {params.min_probability}."
            ]
        ),
    )
