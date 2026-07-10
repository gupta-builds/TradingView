# Phase 2 — First Production Strategy Pack: quality + momentum tilt

> Built by Fable 5, 2026-07-11, on top of the year-ahead base (`Docs/YEAR_AHEAD_BASE.md`).
> Research desk output only — action vocabulary is
> `WATCH | HOLD | ACCUMULATE | REDUCE | AVOID | INSUFFICIENT_DATA`.

## What this is

The first strategy implementation that lives in the installed package (not under
`tests/`), wired as a real spec `hook_ref`, provable through the four-gate
harness, and runnable as a study against the live DuckDB file:

```
hook_ref: research_data.strategies.quality_momentum:quality_momentum_tilt_hook
```

## Formula (literature defaults — nothing fit to our data)

Per rebalance (every 21 sessions ≈ monthly, Jegadeesh-Titman 1993):

```
momentum_12_1  = P[t-21] / P[t-252] - 1                (adjusted close)
momentum_pct   = (rank - 1) / (eligible_count - 1) * 100
quality_score  = quality_fcf composite, 0-100          (FCF/EV 0.40, FCF margin 0.25,
                                                        op-margin stability 0.15, D/E 0.20)
composite      = 0.5 * momentum_pct + 0.5 * quality_score
holdings       = top-K composite names, equal weight   (K=3 default ≈ winner tercile
                                                        of the ~10 fundamentals-bearing
                                                        equities in the locked universe)
turnover       = Σ |Δweight|  (two-sided; entry from cash = 1.0, full swap = 2.0)
```

Costs use the existing gate cost model (5 bps per traded side,
`research_data.gates.metrics`); no second cost system.

### Eligibility (fail-closed)

- < 253 usable sessions → momentum `INSUFFICIENT_DATA`, skipped that rebalance.
- Fundamentals count only when the fiscal period ended ≥ 90 calendar days before
  the rebalance date (one-quarter reporting-availability lag, cf. the ≥3-month
  lags standard since Fama-French 1992). No published statement → quality
  `INSUFFICIENT_DATA`, skipped. **ETFs never have issuer fundamentals and are
  never selectable** — they participate as benchmark/context only.
- Missing sub-fields down-weight through `composite_scores` renormalization; a
  symbol with **no** computable sub-signal is skipped, never imputed.
- Fewer than 2 eligible names → no cross-section → the book holds cash at
  exactly 0.0 return (no invented yield), with the reason recorded.

Every rebalance emits a `RebalanceRecord` (inputs, scores, skips, statement
as-of dates), and every study carries the formula strings — auditable end to end.

### No lookahead

Decisions at session *i* use closes through *i* (the 12-1 window itself ends 21
sessions earlier) and only fundamentals already published under the lag; new
holdings earn returns from *i+1* onward. Verified by a prefix-invariance test
(truncating the future changes nothing in the past).

## Citations

- Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers* —
  12-1 cross-sectional momentum, monthly rebalance.
- Novy-Marx (2013), *The Other Side of Value: The Gross Profitability Premium* —
  quality/profitability premium (our composite is the repo's cash-based variant).
- Asness, Frazzini & Pedersen (2019), *Quality Minus Junk* — quality composite
  construction and the non-optimized equal combination of signals.
- Pardo (1992) / Bailey & López de Prado (2014) — gate defaults (unchanged).

## Free-tier data reality

The live DB holds ~274 sessions per symbol (Polygon/Massive free window,
2025-06 → 2026-07). Momentum warm-up consumes 253 of them, leaving ~21 strategy
sessions — the **out-of-sample gate fails closed** (needs ≥ 60 train + 60 test)
and later gates are not run. That recorded failure is the correct behavior, not
a defect: capability is proven offline on long synthetic history
(`tests/test_strategy_quality_momentum.py` includes a full four-gate pass at
unchanged literature defaults on 1300 synthetic sessions). Do **not** loosen
gate parameters to force a live pass; the desk waits for deeper history.

## How to run

Offline proof (no network, part of CI):

```bash
source .venv/bin/activate
pytest -q tests/test_strategy_quality_momentum.py tests/test_closed_loop_production.py
```

Live study (manual; reads the existing DB, performs zero network calls,
writes brain TestRunRecords + a paper replay journal artifact):

```bash
python scripts/run_quality_momentum_study.py                 # data/market.duckdb
python scripts/run_quality_momentum_study.py --db other.duckdb --skip-paper
python scripts/run_quality_momentum_study.py --record-decision --approver anant
```

The runner registers the spec once (citations → proposed → approved by
`anant`), reuses it on later runs, runs the production hook over stored
history, records every executed gate, and only marks demo-eligibility through
the standard human-decision path (`--record-decision`) — a failed batch can
never silently pass.

First live study (2026-07-11, as of 2026-07-09): 21 net sessions, strategy
+0.43% vs VOO +1.62% same window; OOS gate failed closed on depth; not
demo-eligible; replay journal exit recorded NVDA −2.60% vs VOO +1.92% same
period. Honest numbers, honestly behind the benchmark so far.
