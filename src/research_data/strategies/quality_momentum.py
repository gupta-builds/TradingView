"""Quality + momentum composite tilt — the first production strategy pack.

Literature basis (parameters are documented defaults, not fit to our data):

- Momentum 12-1: Jegadeesh & Titman (1993), "Returns to Buying Winners and
  Selling Losers" — 12-month total return skipping the most recent month,
  monthly rebalance. Implemented by ``research_data.factors.momentum``
  (252-session lookback, 21-session skip).
- Quality: Novy-Marx (2013), "The Other Side of Value: The Gross
  Profitability Premium", and Asness, Frazzini & Pedersen (2019), "Quality
  Minus Junk" — profitable, stable, conservatively financed names earn a
  premium. Implemented as this repo's cash-based quality composite
  (``research_data.factors.quality_fcf``: FCF/EV, FCF margin, operating-margin
  stability, debt/equity — cross-sectional weighted rank, 0-100).
- Combination: equal 50/50 weight of the two signals (the standard
  non-optimized combination in the quality+momentum literature; see AFP 2019's
  factor-combination discussion). No weight was tuned on our data.

Selection rule per rebalance (every 21 sessions ≈ monthly, JT 1993):

    momentum_pct  = cross-sectional percentile of 12-1 return, 0-100
    quality_score = quality_fcf composite, 0-100
    composite     = 0.5 * momentum_pct + 0.5 * quality_score
    holdings      = top-K composite names, equal weight

Eligibility (fail-closed, never fabricated):

- A symbol needs >= 253 usable sessions for momentum, else it is skipped that
  rebalance with reason INSUFFICIENT_DATA.
- A symbol needs point-in-time fundamentals (snapshots whose fiscal period
  ended at least ``fundamentals_lag_days`` before the rebalance date — a
  conservative one-quarter reporting-availability lag) producing at least one
  quality sub-signal, else it is skipped with reason INSUFFICIENT_DATA. ETFs
  have no issuer fundamentals and are therefore never selectable — they
  participate as benchmark/context only. Missing sub-fields down-weight via
  ``composite_scores``'s renormalization (documented there); a symbol with no
  computable sub-signal at all is skipped.
- Fewer than 2 eligible names → no cross-section → the book holds cash (0.0
  return, no invented yield) and the rebalance records why.

Cash handling is explicit: sessions before the first full momentum window are
not emitted at all; after that, un-invested capital earns exactly 0.0. The
benchmark series (VOO buy-and-hold, same sessions) is always returned
alongside, so every gate comparison is like-for-like.

Cost accounting uses the existing gate cost model (default 5 bps per side —
``research_data.gates.metrics``). ``turnover[i]`` is the two-sided sum of
absolute portfolio-weight changes traded at session i's close (initial entry
from cash = 1.0, full sell-and-replace = 2.0), so cost applies per traded
side; no second cost system is introduced.

No lookahead: decisions at session i use closes up to and including i (the
12-1 window itself ends 21 sessions earlier) and fundamentals already
published under the reporting lag; the new holdings earn returns only from
session i+1 onward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from research_data.factors.momentum import MIN_SESSIONS, twelve_minus_one_return
from research_data.factors.quality_fcf import composite_scores, derive_metrics
from research_data.factors.ranking import ascending_ranks
from research_data.fundamentals.models import FundamentalsSnapshot
from research_data.fundamentals.store import to_factor_inputs
from research_data.gates.metrics import StrategyReturns
from research_data.read_api import PriceReadAPI

STRATEGY_NAME = "quality_momentum_tilt"

#: Rebalance cadence in sessions (~monthly, Jegadeesh-Titman 1993).
DEFAULT_REBALANCE_EVERY_SESSIONS = 21

#: Top-K equal-weight holdings. With ~10 fundamentals-bearing equities in the
#: locked 14-symbol universe, K=3 approximates the winner tercile (decile
#: portfolios à la JT are meaningless at N≈10).
DEFAULT_TOP_K = 3

#: Conservative reporting-availability lag: a statement is usable only from
#: ``fiscal_period_end + lag`` onward (one quarter; cf. the >= 3-month lags
#: standard since Fama-French 1992 to avoid using unpublished statements).
DEFAULT_FUNDAMENTALS_LAG_DAYS = 90

#: Fixed 50/50 signal weights — a documented default, deliberately not a
#: tunable parameter (tuning weights on 14 symbols is curve-fitting).
MOMENTUM_WEIGHT = 0.5
QUALITY_WEIGHT = 0.5

#: Formulas surfaced with every study so downstream consumers can audit the
#: exact math behind each decision input.
FORMULAS: dict[str, str] = {
    "momentum_12_1": "P[t-21] / P[t-252] - 1 (adjusted close)",
    "momentum_pct": "(rank - 1) / (eligible_count - 1) * 100",
    "quality_score": (
        "weighted rank composite of FCF/EV (0.40), FCF margin (0.25), "
        "op-margin stability (0.15), debt/equity (0.20), scaled 0-100"
    ),
    "composite": "0.5 * momentum_pct + 0.5 * quality_score",
    "turnover": "sum_s |w_new(s) - w_old(s)| (two-sided; entry from cash = 1.0)",
}


class StrategyDataError(ValueError):
    """Raised when stored data cannot support the strategy at all."""


@dataclass(frozen=True)
class RebalanceRecord:
    """Audit record for one rebalance decision: every input, every skip."""

    as_of: date
    session_index: int
    momentum_12_1: dict[str, float]  # candidates' 12-1 returns
    momentum_pct: dict[str, float]  # eligible names' momentum percentile (0-100)
    quality_score: dict[str, float]  # eligible names' quality composite (0-100)
    composite: dict[str, float]  # eligible names' combined score (0-100)
    holdings: list[str]  # selected top-K (equal weight) — [] = cash
    skipped: dict[str, str]  # symbol → INSUFFICIENT_DATA reason
    fundamentals_as_of: dict[str, date]  # eligible names' statement as-of


@dataclass(frozen=True)
class QualityMomentumStudy:
    """Full study output: gate-ready series + the decision audit trail."""

    strategy: StrategyReturns
    benchmark_returns: list[float]
    rebalances: list[RebalanceRecord]
    dropped_symbols: dict[str, str]  # symbol → calendar/data reason
    params: dict = field(default_factory=dict)

    @property
    def latest_holdings(self) -> list[str]:
        for record in reversed(self.rebalances):
            if record.holdings:
                return record.holdings
        return []


def run_quality_momentum_study(
    params: dict,
    price_api: PriceReadAPI,
    universe: list[str],
    start: date,
    end: date,
    benchmark_symbol: str = "VOO",
    fundamentals_snapshots: dict[str, list[FundamentalsSnapshot]] | None = None,
) -> QualityMomentumStudy:
    """Run the tilt over stored prices and return series + audit trail.

    ``fundamentals_snapshots`` maps symbol → stored statement snapshots; the
    caller (study runner or test) loads them — this module never fetches.
    Symbols absent from the map (all ETFs) can never satisfy the quality
    requirement and are skipped at every rebalance.
    """
    top_k = int(params.get("top_k", DEFAULT_TOP_K))
    rebalance_every = int(
        params.get("rebalance_every_sessions", DEFAULT_REBALANCE_EVERY_SESSIONS)
    )
    lag_days = int(params.get("fundamentals_lag_days", DEFAULT_FUNDAMENTALS_LAG_DAYS))
    if top_k < 1:
        raise StrategyDataError(f"top_k must be >= 1, got {top_k}")
    if rebalance_every < 1:
        raise StrategyDataError(f"rebalance_every_sessions must be >= 1")
    fundamentals_snapshots = fundamentals_snapshots or {}

    symbols = [s for s in universe if s != benchmark_symbol]
    records = price_api.get_price_frame(
        symbols=symbols + [benchmark_symbol], start=start, end=end
    )

    closes: dict[str, list[float]] = {s: [] for s in symbols + [benchmark_symbol]}
    dates: dict[str, list[date]] = {s: [] for s in symbols + [benchmark_symbol]}
    for record in records:
        closes[record.symbol].append(record.adjusted_close or record.close)
        dates[record.symbol].append(record.trading_date)

    calendar = dates[benchmark_symbol]
    n = len(calendar)
    if n <= MIN_SESSIONS:
        raise StrategyDataError(
            f"benchmark {benchmark_symbol} has {n} usable sessions in "
            f"[{start} → {end}]; the 12-1 momentum window needs more than "
            f"{MIN_SESSIONS}. Fails closed — no series fabricated."
        )

    # Symbols must share the benchmark session calendar exactly; anything else
    # is dropped (recorded, never guessed into alignment).
    dropped: dict[str, str] = {}
    active: list[str] = []
    for symbol in symbols:
        if dates[symbol] == calendar:
            active.append(symbol)
        else:
            dropped[symbol] = (
                f"session calendar differs from {benchmark_symbol} "
                f"({len(dates[symbol])} vs {n} usable sessions) — excluded"
            )

    first_rebalance = MIN_SESSIONS - 1  # first session with a full 12-1 window
    holdings: list[str] = []
    rebalances: list[RebalanceRecord] = []

    strategy_dates: list[date] = []
    gross: list[float] = []
    turnover: list[float] = []
    benchmark_returns: list[float] = []
    pending_turnover = 0.0

    for i in range(first_rebalance, n):
        # Returns accrue on sessions after the first decision, always under
        # the holdings chosen at a strictly earlier session.
        if i > first_rebalance:
            day_return = (
                sum(closes[s][i] / closes[s][i - 1] - 1.0 for s in holdings)
                / len(holdings)
                if holdings
                else 0.0
            )
            strategy_dates.append(calendar[i])
            gross.append(day_return)
            turnover.append(pending_turnover)
            pending_turnover = 0.0
            benchmark_returns.append(
                closes[benchmark_symbol][i] / closes[benchmark_symbol][i - 1] - 1.0
            )

        if (i - first_rebalance) % rebalance_every == 0:
            record = _rebalance(
                as_of=calendar[i],
                session_index=i,
                symbols=active,
                closes=closes,
                upto=i,
                top_k=top_k,
                lag_days=lag_days,
                fundamentals_snapshots=fundamentals_snapshots,
                dropped=dropped,
            )
            rebalances.append(record)
            # Trade at session i's close; the cost lands on session i+1's
            # net return (the first return the new holdings produce).
            pending_turnover += _weight_turnover(holdings, record.holdings)
            holdings = record.holdings

    strategy = StrategyReturns(
        strategy_name=STRATEGY_NAME,
        dates=strategy_dates,
        gross_returns=gross,
        turnover=turnover,
    )
    return QualityMomentumStudy(
        strategy=strategy,
        benchmark_returns=benchmark_returns,
        rebalances=rebalances,
        dropped_symbols=dropped,
        params={
            "top_k": top_k,
            "rebalance_every_sessions": rebalance_every,
            "fundamentals_lag_days": lag_days,
            "momentum_weight": MOMENTUM_WEIGHT,
            "quality_weight": QUALITY_WEIGHT,
            "formulas": dict(FORMULAS),
        },
    )


def quality_momentum_tilt_hook(
    params: dict,
    price_api: PriceReadAPI,
    universe: list[str],
    start: date,
    end: date,
    benchmark_symbol: str = "VOO",
    fundamentals_snapshots: dict[str, list[FundamentalsSnapshot]] | None = None,
) -> tuple[StrategyReturns, list[float]]:
    """Spec ``hook_ref`` entry point — gate-harness-shaped return value.

    ``hook_ref``: ``research_data.strategies.quality_momentum:quality_momentum_tilt_hook``
    """
    study = run_quality_momentum_study(
        params,
        price_api,
        universe,
        start,
        end,
        benchmark_symbol=benchmark_symbol,
        fundamentals_snapshots=fundamentals_snapshots,
    )
    return study.strategy, study.benchmark_returns


# -- rebalance internals ---------------------------------------------------------


def _rebalance(
    *,
    as_of: date,
    session_index: int,
    symbols: list[str],
    closes: dict[str, list[float]],
    upto: int,
    top_k: int,
    lag_days: int,
    fundamentals_snapshots: dict[str, list[FundamentalsSnapshot]],
    dropped: dict[str, str],
) -> RebalanceRecord:
    """One decision: score the cross-section as of ``as_of``, pick top-K."""
    skipped: dict[str, str] = dict(dropped)
    momentum: dict[str, float] = {}
    inputs_by_symbol = {}
    published_cutoff = as_of - timedelta(days=lag_days)

    for symbol in symbols:
        r = twelve_minus_one_return(closes[symbol][: upto + 1])
        if r is None:
            skipped[symbol] = (
                "momentum INSUFFICIENT_DATA: fewer than "
                f"{MIN_SESSIONS} usable sessions as of {as_of}"
            )
            continue
        momentum[symbol] = r
        published = [
            s
            for s in fundamentals_snapshots.get(symbol, [])
            if s.fiscal_period_end <= published_cutoff
        ]
        inputs = to_factor_inputs(symbol, published)
        if inputs is None:
            skipped[symbol] = (
                "quality INSUFFICIENT_DATA: no fundamentals published on or "
                f"before {published_cutoff} ({lag_days}d reporting lag); "
                "ETFs have no issuer fundamentals by design"
            )
            continue
        inputs_by_symbol[symbol] = inputs

    metrics = {
        s: derive_metrics(inputs, closes[s][upto])
        for s, inputs in inputs_by_symbol.items()
    }
    quality = composite_scores(metrics) if metrics else {}
    eligible = sorted(s for s, v in quality.items() if v is not None)
    for symbol in inputs_by_symbol:
        if symbol not in eligible:
            skipped[symbol] = (
                "quality INSUFFICIENT_DATA: no computable quality sub-signal "
                "(or cross-section too small to rank) — skipped, not imputed"
            )

    if len(eligible) < 2:
        return RebalanceRecord(
            as_of=as_of,
            session_index=session_index,
            momentum_12_1=momentum,
            momentum_pct={},
            quality_score={},
            composite={},
            holdings=[],
            skipped={
                **skipped,
                "_cross_section": (
                    f"only {len(eligible)} eligible name(s) — no cross-section; "
                    "book stays in cash (0.0 return, nothing invented)"
                ),
            },
            fundamentals_as_of={},
        )

    ranks = ascending_ranks({s: momentum[s] for s in eligible})
    count = len(eligible)
    momentum_pct = {
        s: (ranks[s] - 1) / (count - 1) * 100.0 for s in eligible  # type: ignore[operator]
    }
    composite = {
        s: MOMENTUM_WEIGHT * momentum_pct[s] + QUALITY_WEIGHT * quality[s]
        for s in eligible
    }
    selected = sorted(eligible, key=lambda s: (-composite[s], s))[:top_k]

    return RebalanceRecord(
        as_of=as_of,
        session_index=session_index,
        momentum_12_1=momentum,
        momentum_pct=momentum_pct,
        quality_score={s: quality[s] for s in eligible},  # type: ignore[misc]
        composite=composite,
        holdings=selected,
        skipped=skipped,
        fundamentals_as_of={
            s: inputs_by_symbol[s].as_of for s in eligible
        },
    )


def _weight_turnover(old: list[str], new: list[str]) -> float:
    """Two-sided turnover: sum of |Δweight| across all names (equal weight)."""
    old_w = {s: 1.0 / len(old) for s in old} if old else {}
    new_w = {s: 1.0 / len(new) for s in new} if new else {}
    return sum(
        abs(new_w.get(s, 0.0) - old_w.get(s, 0.0)) for s in set(old_w) | set(new_w)
    )
