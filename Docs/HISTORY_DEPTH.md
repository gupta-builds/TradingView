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

## Re-probe 2026-07-11 (go/no-go chore session)

Re-ran both tier probes; plan is unchanged from the entry above (no upgrade detected):

```
python scripts/deepen_history.py --probe-only --start-date 2022-01-02   # min tier
python scripts/deepen_history.py --probe-only --start-date 2020-07-06   # recommended tier
```

Both requests truncate identically to **first bar 2024-07-11, 501 bars** — same Basic-tier
cap as before. Per stop condition in `PHASE2B_SOLUTION_DESIGN.md` §2, did not proceed to
ingest or fundamentals backfill this session.

V1–V5 measured against the current 501-session DB (read-only, `PHASE2B_SOLUTION_DESIGN.md` §2 SQL):

| Check | Result | Verdict |
|---|---|---|
| V1 depth | n=501 all 14 symbols, lo=2024-07-10, hi=2026-07-09 | **FAIL** (need n≥1135, lo≤2022-01-02) |
| V2 single source | `polygon` / `split_dividend_adjusted`, 7014 rows, 0 nulls | PASS |
| V3 calendar match vs VOO | 0 mismatches, all 14 symbols | PASS |
| V4 split residue | 0 rows with \|1-day adj move\| > 35% | PASS |
| V5 fundamentals depth | earliest quarterly `fiscal_period_end` 2023-12-31 (BRKB/GOOGL/META) to 2025-04-27 (NVDA); 10–14 quarters/equity | **FAIL** (need ≤2021-04/2022-10; ~20–23 quarters) |

**GO/NO-GO: RED.** V2–V4 already pass at current depth and will keep passing once more
`polygon` rows are appended (same source, same adjustment policy). V1 and V5 are blocked on
provider depth — see "Massive Starter+" row below.

## Resolved 2026-07-11 (Tiingo switch, GREEN)

User explicitly authorized switching the price source to **Tiingo** instead of upgrading
Massive (`TIINGO_API_KEY` added to `.env`). Sequence:

1. Wrote `src/research_data/providers/tiingo.py` (`TiingoProvider`, already registered in
   `providers/base.py` and `config/providers.toml` — only the client module was missing).
   Auth via the `Authorization: Token <key>` header, never the URL/query string, so the key
   never appears in `request_url`, stored raw payloads, or any printed output.
2. Live probe (`scripts/deepen_history.py --provider tiingo --probe-only`) cleared the
   **recommended** tier on the first try: `--start-date 2020-07-06` → 1511 bars, no
   truncation. Used this tier (no need to fall back to the 2022-01-02 minimum).
3. `scripts/rebuild_price_source.py --old-source polygon --confirm` purged the 7014 existing
   `polygon` rows (one source for the whole window — required so the PK-includes-`source`
   calendar risk in the solution design never triggers).
4. `research_data ingest-prices --provider tiingo --start-date 2020-07-06` backfilled all
   14 symbols: 1511 rows each, 0 rejected, `usable`.
5. Fixed a real depth-dilution bug in `fundamentals/sec.py::parse_companyfacts`: SEC's
   `dei:EntityCommonStockSharesOutstanding` is tagged on the filing's cover-page date (not
   the fiscal period end), which was creating ~40% of AAPL's "periods" as noise with no
   statement data — diluting the most-recent-`max_periods` window. Filtered those out before
   slicing; verified 0 regression across `tests/test_fundamentals.py`.
6. `scripts/backfill_fundamentals.py --max-periods 40` backfilled SEC quarterly depth for
   all 10 equities to 2018–2019 (comfortably past the 2021-04 recommended-tier target).

**V1–V5 measured after the rebuild (all PASS):**

| Check | Result |
|---|---|
| V1 | n=1511 all 14 symbols, lo=2020-07-06, hi=2026-07-10 (≥1135 min, ≥1513 target ~met) |
| V2 | `tiingo` / `split_dividend_adjusted`, 21154 rows, 0 nulls |
| V3 | 0 calendar mismatches, all 14 symbols |
| V4 | 0 rows with \|1-day adj move\| > 35% |
| V5 | earliest quarterly `fiscal_period_end` 2018-06-30 → 2019-06-30 for all 10 equities (target ≤2021-04) |

Offline `pytest -q`: 472 passed (was 464; +8 new `tests/test_tiingo.py`), no regressions.
Gate constants, hook code, universe, and Fable's F1–F3/study scope untouched.

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

- [x] Max Basic history ingested (501 sessions) — superseded by Tiingo rebuild below
- [x] `scripts/deepen_history.py` ready (now supports `--provider polygon|tiingo`)
- [x] Phase 2b problem + solution design docs
- [x] Tiingo client active (`TIINGO_API_KEY` in `.env`) — recommended tier cleared, no truncation
- [x] V1: DuckDB ≥ 1135 sessions/symbol (target ≥ 1513) — measured n=1511, lo=2020-07-06
- [x] V2–V4: single source (`tiingo`), calendar match, no split residue — PASS
- [x] V5: SEC quarterly depth matching price start — earliest quarter 2018-06→2019-06, all 10 equities
- [ ] Phase 2b Fable coding (F1–F3 + study) unblocked — **go/no-go is GREEN; Fable may start**
