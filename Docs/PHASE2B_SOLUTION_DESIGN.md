# Phase 2b — Solution design: four live gates at unchanged defaults

> Companion to `Docs/PHASE2B_PROBLEM_STATEMENT.md`. Written 2026-07-11 at
> branch tip `f6f26c6`. All constants below are quoted from gate source files
> at this tip; all DB numbers were queried read-only this session.

## 1. Target history depth (derived, not estimated)

The hook consumes a panel of N aligned sessions and emits
**R = N − 253** strategy returns (`MIN_SESSIONS = 253` in
`factors/momentum.py`: 252-session lookback + 1; first rebalance decision at
session index 252, first return the session after).

Binding gate: walk-forward (`gates/walk_forward.py`:
`train_sessions=504, test_sessions=126, step_sessions=126, min_windows=3`).
Window k starts at offset (k−1)·126 and needs 504+126 sessions, so k windows
need `R ≥ 630 + (k−1)·126`:

| Depth tier | WF windows | R needed | **Panel N = R + 253** | ≈ years (252/yr) | Start date for end ≈ 2026-07 |
|---|---|---|---|---|---|
| Gates-can-complete minimum | 3 | 882 | **1135** | 4.50 | ≈ 2022-01 |
| Recommended “serious WF” | 6 | 1260 | **1513** | 6.00 | ≈ 2020-07 |

Cross-checks (all subsumed by the WF row): OOS needs both segments ≥ 60 with
a 70/30 split → R ≥ 200 → N ≥ 453; Monte Carlo needs R ≥ 120 → N ≥ 373;
DSR needs t ≥ 3.

Why 6 windows for “serious”: 3 windows is the literal floor — one bad
6-month window out of 3 already fails the 0.60 `fraction_positive` bar on
granularity alone (2/3 = 0.67 passes, 1 failure in 3 is the knife edge).
Six windows = 3 years of pooled out-of-sample sessions and a meaningful
fraction. Current live depth is 274 sessions — 4.1× short of the minimum
tier; do not attempt the promotion study before Cursor lands ≥ 1135.

**Fundamentals depth must match**: quality eligibility needs a quarterly
statement with `fiscal_period_end ≤ rebalance_date − 90d`
(`DEFAULT_FUNDAMENTALS_LAG_DAYS = 90`). The first rebalance falls ~253
sessions (~12 months) after price start, so:

| Price start | First rebalance ≈ | Earliest quarterly statement needed | ≈ quarters per equity to 2026-Q2 |
|---|---|---|---|
| 2022-01 | 2023-01 | ≤ 2022-10 fiscal end | ~19–20 |
| 2020-07 | 2021-07 | ≤ 2021-04 fiscal end | ~22–23 |

Measured current coverage: earliest quarterly `fiscal_period_end` is
2023-12-31 (BRKB/GOOGL/META), 2024-06-30 (JPM), 2025-Q1+ elsewhere — enough
for **neither** tier. SEC companyfacts (free, already the deeper source at
12 snapshots/equity) is the backfill path; BRKB stays SEC-only.

## 2. Data plan interface for Cursor

**Inputs**
- Symbols: all 14 from `config/assets.toml` (BRKB letters-only in the DB;
  provider punctuation mapping is the client's problem: Polygon `BRK.B`,
  SEC `BRK-B`).
- Window: `start ≤ 2022-01-02` (minimum) / `≤ 2020-07-06` (recommended),
  end = current live edge; contiguous with the existing 2025-06-05 →
  2026-07-09 rows (no interior gaps).
- Adjustment: `split_dividend_adjusted` with non-null `adjusted_close` on
  every row (current DB: 100% polygon `split_dividend_adjusted`, 0 nulls —
  keep that invariant). AMZN/GOOGL 20:1 (2022), TSLA 3:1 (2022), NVDA 10:1
  (2024) splits sit inside the window; unadjusted bars would fabricate
  momentum.
- Source: **one provider for the entire deepened window per symbol.** The
  study path does not yet filter by source and `daily_ohlcv`'s PK includes
  `source`, so mixed-source rows for the same date corrupt the session
  calendar (see Fable item F1). Options, with registry facts
  (`config/providers.toml`):
  - Paid Massive/Polygon tier — existing client, zero new code, depth per
    plan (user decision).
  - Tiingo — registry: 5.0y free, 50/min, split+dividend adjusted; covers
    minimum tier only; **client must be written**.
  - Alpha Vantage — 20y free but registry policy is `split_adjusted`
    (dividend-blind): rejected for this study unless verified
    dividend-inclusive.
- Fundamentals: SEC companyfacts quarterly backfill per §1's table
  (~20–23 quarters × 10 equities). FMP optional; ETFs stay empty.
- Rate limits: Massive free ≈ 5/min with ≥ 60s backoff on 429; SEC
  fair-access UA + throttle. Backfill is a one-shot batch, resumable.

**Outputs**
- `daily_ohlcv`: ≥ 1135 (target ≥ 1513) rows per symbol, one source,
  usable quality, full provenance; raw payloads under
  `data/raw/provider=.../date=.../` exactly as the ingest spine already
  writes them; `raw_market_payloads` + `ingestion_runs` rows as usual.
- `fundamentals_snapshots`: quarterly rows per §1.

**Verification queries (deepen is done only when all pass)**

```sql
-- V1: depth + window per symbol (expect n >= 1135, lo <= target start)
SELECT symbol, COUNT(*) n, MIN(trading_date) lo, MAX(trading_date) hi
FROM daily_ohlcv GROUP BY symbol ORDER BY symbol;

-- V2: one source, adjusted, no nulls (expect a single row; nulls = 0)
SELECT source, price_adjustment, COUNT(*) rows,
       SUM(CASE WHEN adjusted_close IS NULL THEN 1 ELSE 0 END) nulls
FROM daily_ohlcv GROUP BY source, price_adjustment;

-- V3: identical calendar to VOO (expect 0 for every symbol)
WITH voo AS (SELECT trading_date FROM daily_ohlcv WHERE symbol='VOO')
SELECT symbol,
       COUNT(*) FILTER (WHERE trading_date NOT IN (SELECT trading_date FROM voo))
         + (SELECT COUNT(*) FROM voo)
         - COUNT(*) FILTER (WHERE trading_date IN (SELECT trading_date FROM voo))
       AS calendar_mismatch
FROM daily_ohlcv GROUP BY symbol HAVING calendar_mismatch > 0;

-- V4: split residue (expect 0 rows; a hit means adjustment is broken)
SELECT symbol, trading_date, adjusted_close / lag_close - 1 AS move
FROM (SELECT symbol, trading_date, adjusted_close,
             LAG(adjusted_close) OVER (PARTITION BY symbol ORDER BY trading_date) lag_close
      FROM daily_ohlcv)
WHERE lag_close IS NOT NULL AND ABS(adjusted_close / lag_close - 1) > 0.35;

-- V5: fundamentals depth (expect earliest_q <= tier target for all 10 equities)
SELECT symbol, MIN(fiscal_period_end) earliest_q, COUNT(*) quarters
FROM fundamentals_snapshots WHERE period_type = 'quarter'
GROUP BY symbol ORDER BY symbol;
```

**Stop conditions (do not keep pulling past these)**
- Provider refuses the window (e.g. free-tier NOT_AUTHORIZED): stop, report
  the deepest date obtained; do not stitch a second source in as filler
  without flagging F1 to Fable first.
- Any V4 hit: stop and fix adjustment before adding more rows.
- Never modify gate constants, hook code, or the universe to “make it fit.”

## 3. Study plan (after deepen; Fable coding session)

Extend `scripts/run_quality_momentum_study.py` — no new framework. Changes:

- **F1 — source filter:** `--source` flag → new optional `price_source`
  parameter on `run_quality_momentum_study`/hook → forwarded to
  `get_price_frame(source=...)`. (Mirrors `FactorEngine(price_source=...)`.)
- **F2 — depth preflight:** before running gates, print
  `N, R = N − 253` against the table in §1 and name any gate that cannot
  pass at this depth (informational; fail-closed behavior unchanged).
- **F3 — report upgrades:** per-window WF table (test return, Sharpe,
  benchmark return), DSR intermediates (`sr_hat`, `SR0`, `n_trials`,
  skew/kurtosis), cash-session count, and eligible-cross-section size per
  rebalance.
- Re-run the existing offline suite (prefix-invariance, eligibility,
  thin-data fail-closed, four-gate synthetic pass) untouched.

Execution sequence for the promotion study (manual, by `anant`):

```bash
cp data/market.duckdb data/market.duckdb.bak-$(date +%Y%m%d)   # 1. backup
# 2. verify depth: run V1–V5 (read-only) — all pass or stop
python scripts/run_quality_momentum_study.py --db data/market.duckdb \
    [--source polygon]                                          # 3–5. hook → gates → records
# 6. read the report; if and only if 4/4 PASS and the human agrees:
python scripts/run_quality_momentum_study.py --record-decision --approver anant
# 7. replay journal is written by the same run (or --skip-paper to defer)
```

Never run the study while an ingest process holds the DuckDB write lock
(single-writer; a conflicting lock was observed live this session).

Report fields (stdout, no execution language): sessions/R, trade count,
cost model, net total/annualized/Sharpe/max DD, VOO same-window total, gate
table with PASS/FAIL/NOT RUN + notes, TestRunRecord count + n_trials,
demo-eligibility, journal entry ids, F2/F3 additions.

## 4. Pass / fail matrix

| Outcome | What happens | What it means / next |
|---|---|---|
| OOS fails | Batch stops; 1 TestRunRecord; not eligible | On ≥ 1135 sessions this is a real edge failure (net OOS Sharpe ≤ 0 or > 50% degradation), not a data artifact. Record; spec stays UNPROVEN; lesson feeds next proposal. No re-fit on the same window. |
| MC fails | 2 records; stops | Tail of resampled net returns is negative at the 5th percentile — the “edge” is path luck. Same handling. |
| WF fails | 3 records; stops | Inconsistent across sub-periods (< 60% positive windows or pooled Sharpe ≤ 0). Check the F3 cash-session count first: if early windows are cash-dragged, the fix is *fundamentals depth* (Cursor), not gate surgery. |
| DSR fails | 4 records; stops | Sharpe not distinguishable from best-of-N luck at 95%. Record; UNPROVEN. |
| **All 4 pass, strategy ≥ VOO** | 4 records; `--record-decision` by `anant` → DEMO_ELIGIBLE | The desk’s first promotion-grade artifact. Paper replay journal is the demo record. |
| All 4 pass, strategy < VOO same-window | Gates can legitimately pass while trailing the benchmark (OOS gate emits exactly this note) | Recommend explicit HOLD: record the decision with rationale “passed gates, trails baseline — demo adds nothing over VOO.” Promotion is a human call, not an automatic consequence of 4/4. |
| Fundamentals thin in early years despite deep prices | Early rebalances hold cash (0.0, honest) | Expect WF drag (zeros are not > 0). Preflight V5 exists to prevent starting in this state. |
| Provider can’t reach 1135 sessions | Study still runs; preflight names the gate that must fail; batch fails closed | Same as today, at greater depth. No synthetic filler, ever. |

## 5. Definition of Done (measured 2026-07-11, branch `feat/phase2b-promotion-study`)

- [x] Cursor’s V1–V5 all pass at ≥ 1135 sessions (target ≥ 1513) with
      matching fundamentals depth — **before any Fable code is written**.
      Measured: 14 × 1511 sessions (2020-07-06 → 2026-07-10), single source
      `tiingo`, 0 nulls/mismatches/split residue; SEC quarterly depth to
      2018–2019 for all 10 equities.
- [x] F1 source filter implemented + unit test (mixed-source fixture proves
      the guard; single-source path unchanged) —
      `tests/test_strategy_quality_momentum.py::test_price_source_filter_guards_against_mixed_sources`.
- [x] F2 depth preflight prints the R-vs-gate-minima table. Measured run:
      N=1511 → R=1258, all four gates executable, 5 WF windows.
- [x] F3 report additions present in stdout (per-window WF table, DSR
      intermediates, cash-session count, eligible cross-section per
      rebalance, cost drag) plus a per-rebalance `holdings` journal dump.
- [x] `pytest -q` green offline; prefix-invariance and thin-history
      fail-closed tests untouched and passing; no gate constant differs from
      this document.
- [x] One live promotion-study artifact exists: 4 TestRunRecords per batch
      (two identical deterministic batches recorded — study pass and
      decision pass), replay journal entries with `voo_return_same_period`
      on every exit, 60 holdings entries, stdout report saved in
      `Docs/PHASE2B_PROMOTION_STUDY_2026-07-11.md`.
- [x] Promotion state reflects a recorded `anant` decision — measured
      outcome was the 4/4-and-≥-VOO cell (net +356.82% vs VOO +87.10%), so
      **promote (unproven → demo_eligible)** was recorded
      (decision `6b46e5fb-1674-45ce-9020-016c46b9e01b`).
- [x] Guardrail sweep clean (no execution language in new strings; no new
      dependencies; Kronos untouched).

## 6. Explicit split

**Cursor finishes first (no Fable coding before this):** provider depth
decision executed (paid Massive tier or new Tiingo client), OHLCV backfill
to tier target, SEC quarterly fundamentals backfill, V1–V5 green, rate-limit
compliant, gate/hook/universe untouched.

**Fable implements (one coding session):** F1 source-seam guard, F2 depth
preflight, F3 report upgrades, their tests, then executes the promotion
study end-to-end (with backup) and writes the artifact + docs.

**`anant` alone decides:** which provider/plan pays for depth (the only
open user fact); whether a 4/4 pass becomes DEMO_ELIGIBLE or an explicit
HOLD (especially in the passes-but-trails-VOO cell); when to run
`--record-decision`.
