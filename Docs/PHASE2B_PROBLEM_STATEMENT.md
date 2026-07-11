# Phase 2b — Problem statement: promotion-grade evidence on real bars

> Analysis by Fable 5, 2026-07-11, at branch tip `f6f26c6` (PR #1, CI green).
> Every number below was measured this session from the repo, the gate source
> constants, or a read-only query against `data/market.duckdb` (+ its
> pre-study backup). Companion: `Docs/PHASE2B_SOLUTION_DESIGN.md`.

## Problem

Phase 2a proved the machinery; it could not prove the strategy. The gap, in
measured numbers:

- **What we have (live DB, 2026-07-11):** 14/14 symbols × **274 usable
  sessions** each (2025-06-05 → 2026-07-09), identical calendar to VOO, all
  `polygon` / `split_dividend_adjusted`, zero null `adjusted_close`.
  Fundamentals: 12 SEC snapshots per equity (8–10 quarterly + 2–4 annual),
  earliest **quarterly** `fiscal_period_end` = 2023-12-31 (BRKB, GOOGL,
  META), 2024-06-30 (JPM), 2025-Q1+ for the rest; FMP has only 4 quarters
  from 2025-06 on and no BRKB.
- **What the production hook consumes:** momentum needs `MIN_SESSIONS = 253`
  before the first rebalance decision (`factors/momentum.py`), so a panel of
  N sessions yields **R = N − 253** strategy return sessions.
- **What the gates demand (constants read from source at this tip):**

  | Gate | Binding size rule | Minimum R | Minimum panel N |
  |---|---|---|---|
  | 1 OOS (`oos.py`) | `train_fraction=0.70`, both segments ≥ `min_oos_periods=60` → `0.3·R ≥ 60` | 200 | 453 (~1.8y) |
  | 2 Monte Carlo (`monte_carlo.py`) | `min_periods=120` | 120 | 373 (subsumed) |
  | 3 Walk-forward (`walk_forward.py`) | `train=504`, `test=126`, `step=126`, `min_windows=3` → `R ≥ 504 + 126 + 2·126 = 882` | 882 | **1135 (~4.50y)** |
  | 4 Deflated Sharpe (`deflated_sharpe.py`) | `t ≥ 3`, `min_probability=0.95` | 3 | (subsumed) |

- **Phase 2a live outcome (recorded in `brain_test_runs`):** N = 274 →
  R = 21 → OOS split is train 14 / test 7, both < 60 → **gate 1 failed
  closed** and, because `GateHarness.run` short-circuits on first failure
  (`gates/harness.py`), gates 2–4 have never executed on real data. Spec
  `quality_momentum_tilt_top3` sits `approved / unproven`.

So the desk today has a synthetic four-gate pass (capability) and a real-data
sample **4.1× too shallow** for the binding walk-forward constraint
(274 vs 1135 sessions). "Desk is real" — gated replay + journal vs VOO with
trade count / costs / max drawdown, promotion path to demo-eligible — is
physically impossible until history deepens. Phase 2b closes exactly that.

A second, quieter gap: **fundamentals depth must track price depth.** The
hook's quality eligibility requires a quarterly statement with
`fiscal_period_end ≤ rebalance_date − 90d`. First rebalance lands ~1 calendar
year after the price panel starts; every rebalance where fewer than 2 names
are eligible holds cash at exactly 0.0. Cash sessions poison walk-forward:
a test window of zeros has `test_return == 0`, which does **not** count as
positive (`> 0` strictly), dragging `fraction_positive` below the 0.60 bar
even when the invested part of the series is healthy. With prices deepened to
2022-01 but fundamentals still starting 2023-12, roughly the first year of
rebalances would sit in cash — a self-inflicted walk-forward failure.

## Non-goals (Phase 2b will refuse)

- **No gate weakening.** `504/126`, `min_windows=3`, `60`, `120`, `0.95`,
  5 bps/side stay exactly as shipped. A pass earned any other way is noise.
- **No fabricated or padded history.** Depth comes from a provider, or the
  gates keep failing closed — both are acceptable outcomes; fake bars are not.
- **No new strategy family.** Phase 2b promotes (or honestly fails)
  `research_data.strategies.quality_momentum:quality_momentum_tilt_hook` —
  no parallel toy strategy, no parameter re-fit to the deep window.
- **No orchestration kitchen-sink.** Extend
  `scripts/run_quality_momentum_study.py`; do not build a pipeline framework.
- **No Kronos inference, no UI/Streamlit, no LLM proposer, no universe
  expansion, no PM vertical.**

## Success metric

Phase 2b is done when, on a real DuckDB (no synthetic rows):

1. `GateHarness.run_and_record` executes **all four gates in order** at
   unchanged defaults over the production hook's series (pass or fail — but
   the data makes a pass physically possible: N ≥ 1135, fundamentals-eligible
   cross-section from the first rebalance).
2. Every executed gate has a `TestRunRecord`; failures stop the batch.
3. If and only if all four pass: `--record-decision` by `anant` →
   `DEMO_ELIGIBLE` (or an explicit, justified HOLD).
4. A historical replay journal exists for the study window with honest net
   return, trade count, costs, max drawdown, and `voo_return_same_period` on
   every exit (or a review entry stating the benchmark figure was
   unavailable — never a placeholder).
5. Offline CI stays green; deepening and the live study never enter pytest.

## Blockers owned by Cursor (before Fable codes anything)

1. **Deepen daily OHLCV to ≥ 1135 sessions per symbol** (recommended ≥ 1513;
   see solution design §1) for all 14 symbols, **split-and-dividend-adjusted**,
   single source for the whole window, ending at the current live edge.
   Free-tier facts measured from `config/providers.toml` and run memory:
   - `polygon` free ≈ 2.0y (`min_history_years_free = 2.0`; free tier
     rejects older windows with NOT_AUTHORIZED) — **insufficient**; a paid
     Massive tier would reuse the existing client unchanged (plan depth is a
     user decision — see final questions).
   - `tiingo`: registry says 5.0y free, 50/min, `split_dividend_adjusted` —
     covers the 4.5y minimum, not the 6y recommendation. **No client exists
     yet** (`providers/` has only `csv_fixture` and `polygon`).
   - `alpha_vantage`: registry says 20y free, 5/min, but
     `adjustment_policy = "split_adjusted"` (no dividends) — total-return
     momentum and the VOO comparison would be systematically biased; avoid
     for this study unless the adjusted-close endpoint is confirmed
     dividend-inclusive.
2. **Deepen quarterly fundamentals** via SEC companyfacts (free; already the
   richer source: 12 snapshots vs FMP's 4) so every equity has quarterly
   statements with `fiscal_period_end ≤ (price_start + ~12 months − 90d)` —
   concretely ~20 quarters/equity back to ~2021-Q3 for the minimum depth,
   ~23 quarters to ~2020-Q4 for the recommended depth. BRKB stays SEC-only
   (FMP 402 on free plan). ETFs stay empty by design.
3. **Respect rate limits** during backfill (polygon/Massive ≈ 5/min with
   ≥60s retry on 429; SEC fair-access). Backfill is a batch job, not a loop
   fix.
4. **Do not touch gate constants, hook code, or `config/assets.toml`.**
5. Verification queries and stop conditions are specified in the solution
   design §2 — Cursor's deepen is done only when they pass.

## Blockers owned by Fable (implement in the later coding session)

1. **Source-seam guard (real gap, found this turn):** neither
   `run_quality_momentum_study` nor the study script filters
   `daily_ohlcv.source`, and the table's PK includes `source` — if two
   providers' rows coexist for the same symbol/date, `get_price_frame`
   returns both and the per-symbol close series gets duplicate dates
   (benchmark calendar corrupts; equities get dropped by the calendar
   guard). Fix: `--source` CLI flag → `price_source` parameter on the
   hook/study (mirroring `FactorEngine(price_source=...)`) → passed to
   `get_price_frame(source=...)`. Required before any second price source
   ever lands in the DB; harmless otherwise.
2. **Study report upgrades (reporting only, no math):** per-window
   walk-forward table, DSR intermediates, cash-session count, and eligible
   cross-section size per rebalance in the stdout report, so the promotion
   decision reads off one artifact.
3. **Depth preflight in the study script:** print the R = N − 253 arithmetic
   against the four gate minima before running, so an under-depth run says
   *which* gate must fail before it fails.
4. Nothing else. The harness, brain loop, paper engine, and hook math were
   proven in Phase 2a and are not redesigned.

## Risk register

| Risk | Reality check | Mitigation |
|---|---|---|
| **Synthetic pass read as evidence** | The 1300-session pass used favorable seeded drifts; it proves plumbing, not edge | Success metric counts only real-bar gates; docs and report label the synthetic pass "capability" |
| **Regime luck on one deep window** | 2020-07→2026-07 is one bull-heavy regime; 3–6 WF windows is thin | Record it honestly: report per-window returns and the vs-VOO note the OOS gate already emits; DSR with honest `n_trials`; promotion stays a human call even on 4/4 |
| **Cash-drag walk-forward failure from shallow fundamentals** | Measured: earliest quarterly statement 2023-12 vs price target 2020-07/2022-01 | Cursor's stop condition #2; study report prints cash-session count per WF window |
| **Split/dividend adjustment errors across 5y** | NVDA/AMZN/GOOGL/TSLA all split 2022–2024; unadjusted bars would fabricate momentum | Single `split_dividend_adjusted` source; verification query flags any 1-day adjusted move > 35% |
| **Costs/turnover dishonesty** | Two-sided Σ\|Δw\| costing shipped and tested in 2a | Unchanged; report prints trade count + cost drag explicitly |
| **Lookahead regression while touching the study path** | Prefix-invariance test exists (`tests/test_strategy_quality_momentum.py`) | Any Fable change re-runs it; no signal-path edits are in scope |
| **DB mutation safety** | The study writes brain/paper rows; DuckDB is single-writer (a concurrent lock was hit live this session, PID of another ingest process) | Keep 2a discipline: file-copy backup before every writing run; never run study concurrently with ingest |
| **DSR self-deception via trial accounting** | Only 1 spec ever tested → `n_trials=1`, SR0=0 → DSR degenerates to plain PSR | Acceptable and conservative-in-spirit for one spec; note it in the report; trial count grows naturally as specs accumulate |
