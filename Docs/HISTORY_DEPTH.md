# History depth for default walk-forward (Phase 2b prerequisite)

> Cursor ops note. **SoT for minima:** `Docs/PHASE2B_PROBLEM_STATEMENT.md` +
> `Docs/PHASE2B_SOLUTION_DESIGN.md` (Fable 5, 2026-07-11). Gate constants are
> **not** changed.

## Binding math (from gate source)

Hook emits `R = N − 253` strategy returns. Walk-forward is binding:

| Tier | WF windows | R | Panel N | ≈ years | Price start (end ≈ 2026-07) |
|---|---|---|---|---|---|
| Gates-can-complete | 3 | 882 | **1135** | 4.50 | ≈ **2022-01** |
| Recommended serious WF | 6 | 1260 | **1513** | 6.00 | ≈ **2020-07** |

Fundamentals must match: earliest quarterly `fiscal_period_end` ≤ first
rebalance − 90d (~20 quarters for min tier, ~23 for recommended). SEC
companyfacts backfill required; FMP optional; BRKB SEC-only.

## Measured 2026-07-11

| Source | Depth | Verdict |
|---|---|---|
| Phase 2a live study DB | 274 sessions (2025-06-05 → 2026-07-09) | OOS fail-closed |
| After max Basic ingest | **501 sessions** (2024-07-10 → 2026-07-09) | Still below N≥1135 |
| Probe 2021-01-01 → today | Truncates to first bar **2024-07-10** | Current key = Massive **Basic** |

Massive ([pricing](https://massive.com/pricing)): Basic 2y (blocked) ·
**Starter $29 / 5y** clears min tier · **Developer $79 / 10y** clears
recommended 6y tier. Tiingo (5y free, div-adjusted) covers min only — **no
client yet**; do not mix sources until F1 `--source` lands. Alpha Vantage
rejected (dividend-blind per registry).

## Deepen (Cursor; after paid key or Tiingo client)

```bash
source .venv/bin/activate
# Min tier:
python scripts/deepen_history.py --probe-only --start-date 2022-01-02
# Recommended tier:
python scripts/deepen_history.py --probe-only --start-date 2020-07-06

# When probe says depth sufficient:
python scripts/deepen_history.py --start-date 2022-01-02   # or 2020-07-06
# Then SEC quarterly fundamentals backfill to match (V5) — required before study
```

**Go/no-go:** V1–V5 in `PHASE2B_SOLUTION_DESIGN.md` §2 must all pass.
Do **not** loosen gates. Do **not** stitch a second price source as filler
before F1. If deepen truncates after a believed upgrade: **stop and ping**
with probe output + deepest date.

## Status

- [x] Max Basic history ingested (501 sessions)
- [x] `scripts/deepen_history.py` ready
- [x] Phase 2b problem + solution design docs
- [ ] Massive Starter+ (or Tiingo client) active
- [ ] V1: DuckDB ≥ 1135 sessions/symbol (target ≥ 1513)
- [ ] V2–V4: single source, calendar match, no split residue
- [ ] V5: SEC quarterly depth matching price start
- [ ] Phase 2b Fable coding (F1–F3 + study) unblocked
