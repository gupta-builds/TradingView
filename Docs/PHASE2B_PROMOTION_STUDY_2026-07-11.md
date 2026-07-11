# Phase 2b promotion study — 2026-07-11 (tiingo deep DB)

> Live-data promotion study artifact. Every number below comes from this
> run's stdout (saved verbatim in the appendix) or a read-only DuckDB query
> the same session. Research desk output only — no execution language;
> action vocabulary is WATCH | HOLD | ACCUMULATE | REDUCE | AVOID |
> INSUFFICIENT_DATA.

## Setup

- Branch: `feat/phase2b-promotion-study`; DB `data/market.duckdb`
  (backup `data/market.duckdb.bak-phase2b-20260711` taken first; no
  concurrent ingest).
- V1–V5 re-verified green before the run: 14 symbols × 1511 sessions
  (2020-07-06 → 2026-07-10), single source `tiingo` /
  `split_dividend_adjusted`, 0 null adjusted_close, 0 calendar mismatches
  vs VOO, 0 split-residue hits > 35%, SEC quarterly fundamentals back to
  2018–2019 for all 10 equities.
- Command: `python scripts/run_quality_momentum_study.py --db
  data/market.duckdb --source tiingo`, then the same with
  `--record-decision --approver anant --skip-paper` (paper skipped on the
  decision pass so the journal artifact is written exactly once; the
  decision pass re-runs the deterministic gate batch and recorded an
  identical second set of 4 TestRunRecords).
- Gates, hook math, and universe unchanged (504/126/126, min_windows=3,
  OOS 70/30 with segments ≥ 60, MC min 120, DSR ≥ 0.95, 5 bps/side).

## Depth preflight (F2)

N = 1511 → R = 1258 strategy return sessions. All four gates executable;
5 walk-forward windows available (between the 3-window minimum and the
6-window "serious" tier).

## Result — gate batch 4/4 PASS

| Gate | Result | Key numbers |
|---|---|---|
| out_of_sample | PASS | recorded in TestRunRecord (70/30 split over R=1258) |
| monte_carlo | PASS | resampled net-return tail clears the 5th-percentile bar |
| walk_forward | PASS | 5/5 windows positive (fraction_positive=1.00), pooled Sharpe 1.52 |
| deflated_sharpe | PASS | DSR 0.9947 ≥ 0.95 (n_trials=1 → SR0=0, reduces to PSR — conservative-in-spirit, noted per the risk register) |

Walk-forward windows (net of 5 bps/side):

| Window | Test return | Test Sharpe | VOO same window |
|---|---|---|---|
| 1 | +16.32% | +1.36 | +7.58% |
| 2 | +81.68% | +4.15 | +19.62% |
| 3 | +9.52% | +0.74 | +6.64% |
| 4 | +5.68% | +0.47 | +6.57% |
| 5 | +16.68% | +1.52 | +11.99% |

DSR intermediates: sr_hat_per_period 0.0718, SR0 0.0, n_trials 1,
variance_trial_sharpes 0.0, skewness +0.218, kurtosis 6.399, t=1258,
z=2.556 → probability 0.9947.

## Honest performance block

- 1258 net-of-cost sessions, 34 rebalance trades, total two-sided
  turnover 23.67 → cumulative cost drag 1.1833% of book (5 bps/side).
- Cash sessions: 0 of 1258 — the eligible cross-section was 9/9 equities
  at every one of the 60 rebalances (fundamentals depth did its job;
  the cash-drag failure mode never triggered).
- Strategy net: total +356.82%, annualized +35.57%, Sharpe 1.14,
  max drawdown −33.46%.
- VOO same window: +87.10%. Strategy net ≥ VOO.
- Caveat (risk register): 2020-07 → 2026-07 is one bull-heavy regime and
  n_trials=1 gives no selection-bias deflation credit beyond PSR. The
  gates passing here is evidence, not proof of edge.

## Decision (policy: 4/4 and strategy net ≥ VOO → DEMO_ELIGIBLE)

- Decision recorded by `anant` via `--record-decision`:
  **promote (unproven → demo_eligible)**; decision id
  `6b46e5fb-1674-45ce-9020-016c46b9e01b`, spec
  `5f003778-42bc-4d8a-ac12-839699d98a02` (`quality_momentum_tilt_top3`).
- `is_demo_eligible` now returns True for the spec.

## Journal artifacts

- Holdings dump (F3): 60 `holdings` journal entries, one per rebalance,
  each with symbols/equal weights/as_of; 0 cash rebalances.
- Replay: entry + exit pair; exit `8524d063-1d3e-43cc-9f5a-f0086a7707b3`
  (NVDA, realized +939.09% vs VOO +86.46% same holding period —
  single-name starter-size replay under standard paper rules).
- Pre-existing Phase 2a artifacts (the 2026-07-09 failed OOS TestRunRecord
  and its journal pair) remain untouched on the record.

## Appendix — run 1 stdout (verbatim)

```
Universe: 14 symbols, benchmark VOO; 1511 VOO sessions stored [2020-07-06 → 2026-07-10]; price source filter: tiingo.

Depth preflight: N = 1511 panel sessions -> R = N - 253 = 1258 strategy return sessions.
  out_of_sample: needs R >= 200 (70/30 split, both segments >= 60 returns) — depth ok
  monte_carlo: needs R >= 120 (min_periods=120) — depth ok
  walk_forward: needs R >= 882 (train 504 + test 126 + 2x126 steps (min_windows=3)) — depth ok
  deflated_sharpe: needs R >= 3 (t >= 3 returns) — depth ok
  walk-forward windows available at this depth: 5
  All four gates are executable at this depth (pass not implied).
Fundamentals loaded for 10/10 equities.
Reusing approved spec 5f003778-42bc-4d8a-ac12-839699d98a02 (quality_momentum_tilt_top3).

=== quality_momentum_tilt_top3 study report (as of 2026-07-10) ===
Series: 1258 net-of-cost sessions (5 bps/side), 34 rebalance trades.
Costs: total two-sided turnover 23.67 -> cumulative cost drag 1.1833% of book.
Cash sessions: 0 of 1258 (0.0%) accrued at exactly 0.0 (no eligible cross-section in effect).
Strategy net: total +356.82%, annualized +35.57%, Sharpe 1.14, max drawdown -33.46%.
VOO same window: total +87.10%.
Latest holdings (equal weight): NVDA, GOOGL, AAPL.

Eligible cross-section per rebalance (as_of, eligible, holdings):
  2021-07-06  eligible= 9  NVDA, TSLA, GOOGL
  2021-08-04  eligible= 9  GOOGL, TSLA, NVDA
  2021-09-02  eligible= 9  GOOGL, TSLA, NVDA
  2021-10-04  eligible= 9  GOOGL, TSLA, NVDA
  2021-11-02  eligible= 9  GOOGL, TSLA, MSFT
  2021-12-02  eligible= 9  TSLA, GOOGL, MSFT
  2022-01-03  eligible= 9  GOOGL, MSFT, NVDA
  2022-02-02  eligible= 9  GOOGL, NVDA, COST
  2022-03-04  eligible= 9  NVDA, COST, TSLA
  2022-04-04  eligible= 9  NVDA, COST, AAPL
  2022-05-04  eligible= 9  NVDA, TSLA, AAPL
  2022-06-03  eligible= 9  TSLA, AAPL, COST
  2022-07-06  eligible= 9  AAPL, COST, MSFT
  2022-08-04  eligible= 9  AAPL, COST, BRKB
  2022-09-02  eligible= 9  AAPL, COST, TSLA
  2022-10-04  eligible= 9  AAPL, COST, MSFT
  2022-11-02  eligible= 9  AAPL, MSFT, COST
  2022-12-02  eligible= 9  BRKB, AAPL, COST
  2023-01-04  eligible= 9  BRKB, GOOGL, COST
  2023-02-03  eligible= 9  BRKB, COST, GOOGL
  2023-03-07  eligible= 9  BRKB, AAPL, COST
  2023-04-05  eligible= 9  BRKB, NVDA, AAPL
  2023-05-05  eligible= 9  NVDA, AAPL, BRKB
  2023-06-06  eligible= 9  NVDA, META, AAPL
  2023-07-07  eligible= 9  NVDA, META, AAPL
  2023-08-07  eligible= 9  NVDA, META, MSFT
  2023-09-06  eligible= 9  NVDA, META, GOOGL
  2023-10-05  eligible= 9  META, MSFT, NVDA
  2023-11-03  eligible= 9  NVDA, GOOGL, META
  2023-12-05  eligible= 9  NVDA, META, GOOGL
  2024-01-05  eligible= 9  NVDA, META, GOOGL
  2024-02-06  eligible= 9  NVDA, META, GOOGL
  2024-03-07  eligible= 9  NVDA, META, GOOGL
  2024-04-08  eligible= 9  NVDA, META, GOOGL
  2024-05-07  eligible= 9  NVDA, META, GOOGL
  2024-06-06  eligible= 9  NVDA, META, GOOGL
  2024-07-09  eligible= 9  NVDA, META, GOOGL
  2024-08-07  eligible= 9  NVDA, META, GOOGL
  2024-09-06  eligible= 9  NVDA, META, COST
  2024-10-07  eligible= 9  NVDA, META, AMZN
  2024-11-05  eligible= 9  NVDA, META, GOOGL
  2024-12-05  eligible= 9  NVDA, META, GOOGL
  2025-01-07  eligible= 9  NVDA, META, AMZN
  2025-02-07  eligible= 9  NVDA, GOOGL, META
  2025-03-11  eligible= 9  NVDA, GOOGL, META
  2025-04-09  eligible= 9  NVDA, AAPL, TSLA
  2025-05-09  eligible= 9  NVDA, TSLA, BRKB
  2025-06-10  eligible= 9  TSLA, META, NVDA
  2025-07-11  eligible= 9  NVDA, META, TSLA
  2025-08-11  eligible= 9  NVDA, META, TSLA
  2025-09-10  eligible= 9  NVDA, GOOGL, META
  2025-10-09  eligible= 9  GOOGL, NVDA, META
  2025-11-07  eligible= 9  GOOGL, NVDA, META
  2025-12-09  eligible= 9  GOOGL, NVDA, MSFT
  2026-01-09  eligible= 9  GOOGL, NVDA, MSFT
  2026-02-10  eligible= 9  GOOGL, NVDA, AAPL
  2026-03-12  eligible= 9  GOOGL, NVDA, AAPL
  2026-04-13  eligible= 9  NVDA, GOOGL, TSLA
  2026-05-12  eligible= 9  NVDA, GOOGL, AAPL
  2026-06-11  eligible= 9  NVDA, GOOGL, AAPL

Gate batch (fixed order, stops at first failure):
  out_of_sample: PASS
  monte_carlo: PASS
  walk_forward: PASS
  deflated_sharpe: PASS
Recorded 4 TestRunRecords (trials=1).

Walk-forward test windows (net of costs):
  window  test_start  test_return  test_sharpe  benchmark_return
       1         504      +16.32%        +1.36            +7.58%
       2         630      +81.68%        +4.15           +19.62%
       3         756       +9.52%        +0.74            +6.64%
       4         882       +5.68%        +0.47            +6.57%
       5        1008      +16.68%        +1.52           +11.99%
  fraction_positive=1.00, pooled_sharpe=1.52.

Deflated Sharpe intermediates:
  deflated_sharpe_probability: 0.9946998844687689
  sr_hat_per_period: 0.07176773284544975
  sr0_expected_max: 0.0
  n_trials: 1
  variance_trial_sharpes: 0.0
  skewness: 0.21809019402360963
  kurtosis: 6.398815200131484
  t_periods: 1258
  z_statistic: 2.555608491394646
No promotion decision recorded (pass --record-decision to record one).
Demo-eligible: False.

Journal holdings dump: 60 rebalance records (0 in cash) persisted as 'holdings' entries.
Journal [exit] 8524d063-1d3e-43cc-9f5a-f0086a7707b3: realized +939.0877% vs VOO same period +86.4626%

Reminder: research desk output only — action vocabulary is WATCH | HOLD | ACCUMULATE | REDUCE | AVOID | INSUFFICIENT_DATA.
```

## Appendix — decision pass tail (run 2, `--record-decision --skip-paper`)

```
Promotion decision recorded: promote (unproven → demo_eligible).
Demo-eligible: True.
Paper replay skipped (--skip-paper).
```
