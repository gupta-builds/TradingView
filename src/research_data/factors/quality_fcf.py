"""Quality/FCF composite and cash-based valuation context.

Composite of four sub-signals (weights below), each rank-scored across the
universe and combined into a 0-100 value:

- FCF/EV (primary weight): free cash flow / enterprise value. Hardest
  valuation metric to manipulate; strongest documented large-cap factor.
- FCF margin: FCF / revenue.
- Operating-margin stability: stdev of operating margin across trailing
  periods (lower stdev = steadier = better).
- Debt-to-equity: lower is better within the universe.

Derivations (explicit, no fabrication):
    fcf            = operating_cash_flow - capex
    market_cap     = price_as_of * shares_outstanding
    enterprise_val = market_cap + total_debt - cash_and_equivalents
    fcf_ev         = fcf / enterprise_value
    fcf_margin     = fcf / revenue
    debt_to_equity = total_debt / total_equity

Kill conditions: ETFs and symbols without fundamentals get no composite —
status INSUFFICIENT_DATA. Missing sub-fields shrink the composite's inputs
and are reported, never imputed.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from research_data.factors.ranking import ascending_ranks, inverse_ranks

#: Sub-signal weights (must sum to 1.0). FCF/EV carries the primary weight.
WEIGHTS: dict[str, float] = {
    "fcf_ev": 0.40,
    "fcf_margin": 0.25,
    "op_margin_stability": 0.15,
    "debt_to_equity": 0.20,
}


@dataclass(frozen=True)
class FundamentalInputs:
    """Per-symbol fundamentals needed by the composite, with provenance.

    All monetary values in the statement's reporting currency (USD for the
    V1 universe). ``operating_margins`` holds trailing per-period operating
    margins (most recent last) for the stability check.
    """

    symbol: str
    as_of: date
    source: str
    revenue: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    total_equity: float | None = None
    shares_outstanding: float | None = None
    operating_margins: list[float] = field(default_factory=list)

    @property
    def fcf(self) -> float | None:
        if self.operating_cash_flow is None or self.capex is None:
            return None
        return self.operating_cash_flow - abs(self.capex)


@dataclass(frozen=True)
class QualityMetrics:
    """Derived per-symbol metrics feeding the cross-sectional composite."""

    symbol: str
    fcf_ev: float | None
    fcf_margin: float | None
    op_margin_stability: float | None  # stdev of operating margins (lower better)
    debt_to_equity: float | None
    market_cap: float | None
    enterprise_value: float | None
    fundamentals_as_of: date | None
    fundamentals_source: str | None


def derive_metrics(
    inputs: FundamentalInputs, price_as_of: float | None
) -> QualityMetrics:
    """Derive composite inputs from fundamentals + an as-of price.

    Every None stays None: a missing field is reported missing downstream,
    never replaced with an estimate.
    """
    market_cap: float | None = None
    if price_as_of is not None and inputs.shares_outstanding:
        market_cap = price_as_of * inputs.shares_outstanding

    enterprise_value: float | None = None
    if (
        market_cap is not None
        and inputs.total_debt is not None
        and inputs.cash_and_equivalents is not None
    ):
        enterprise_value = market_cap + inputs.total_debt - inputs.cash_and_equivalents

    fcf = inputs.fcf

    fcf_ev: float | None = None
    if fcf is not None and enterprise_value is not None and enterprise_value > 0:
        fcf_ev = fcf / enterprise_value

    fcf_margin: float | None = None
    if fcf is not None and inputs.revenue is not None and inputs.revenue > 0:
        fcf_margin = fcf / inputs.revenue

    stability: float | None = None
    if len(inputs.operating_margins) >= 4:
        stability = statistics.stdev(inputs.operating_margins)

    debt_to_equity: float | None = None
    if (
        inputs.total_debt is not None
        and inputs.total_equity is not None
        and inputs.total_equity > 0
    ):
        debt_to_equity = inputs.total_debt / inputs.total_equity

    return QualityMetrics(
        symbol=inputs.symbol,
        fcf_ev=fcf_ev,
        fcf_margin=fcf_margin,
        op_margin_stability=stability,
        debt_to_equity=debt_to_equity,
        market_cap=market_cap,
        enterprise_value=enterprise_value,
        fundamentals_as_of=inputs.as_of,
        fundamentals_source=inputs.source,
    )


def composite_scores(metrics: dict[str, QualityMetrics]) -> dict[str, float | None]:
    """Cross-sectional 0-100 composite per symbol via weighted rank-average.

    For each sub-signal, symbols are ranked across the universe (higher rank =
    better: high FCF/EV and FCF margin, low margin stdev, low leverage). Each
    rank is scaled to 0-100 and combined with WEIGHTS, renormalizing over the
    sub-signals the symbol actually has. A symbol with no sub-signals at all
    gets None.
    """
    fcf_ev_ranks = ascending_ranks({s: m.fcf_ev for s, m in metrics.items()})
    fcf_margin_ranks = ascending_ranks({s: m.fcf_margin for s, m in metrics.items()})
    stability_ranks = inverse_ranks(
        {s: m.op_margin_stability for s, m in metrics.items()}
    )
    leverage_ranks = inverse_ranks({s: m.debt_to_equity for s, m in metrics.items()})

    per_signal_ranks: dict[str, dict[str, int | None]] = {
        "fcf_ev": fcf_ev_ranks,
        "fcf_margin": fcf_margin_ranks,
        "op_margin_stability": stability_ranks,
        "debt_to_equity": leverage_ranks,
    }

    scores: dict[str, float | None] = {}
    for symbol in metrics:
        weighted_sum = 0.0
        weight_total = 0.0
        for signal, ranks in per_signal_ranks.items():
            rank = ranks[symbol]
            if rank is None:
                continue
            ranked_count = sum(1 for r in ranks.values() if r is not None)
            if ranked_count < 2:
                continue  # a rank within a single-symbol field carries no signal
            scaled = (rank - 1) / (ranked_count - 1) * 100.0
            weighted_sum += WEIGHTS[signal] * scaled
            weight_total += WEIGHTS[signal]
        scores[symbol] = round(weighted_sum / weight_total, 2) if weight_total else None
    return scores
