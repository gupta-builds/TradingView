# Fable 5 run memory — year-ahead base build (started 2026-07-10)

Short lessons only: corrections + confirmed approaches. Read at each work block. No duplication of git/chat.

## Confirmed approaches

- Vault edits: use the **jarvis MCP** (`vault_patch` by heading, `vault_append`, `vault_read`) — not
  `jarvis-fs` (repo-only) and not raw writes on the `/mnt/d` mount. Patch by heading preserves frontmatter.
- Source of truth on conflicts: `Session Findings — Cursor Alignment Pass (2026-07-10).md`.
- Baseline before any new code: 255 tests passed (2026-07-10). Any regression below that is mine.
- Keep dependencies minimal: gates math in pure Python (`statistics.NormalDist` has cdf + inv_cdf — no scipy);
  HTTP via `urllib.request` (requests/httpx are not project deps).
- Existing short fixtures (65 rows) are for ingestion tests; factor/gate tests use seeded synthetic series
  from `tests/synthetic.py` — synthetic *test* data is fine, fabricated *product* data is not.
- `BRK.B` fails the `^[A-Z]{1,10}$` symbol rule → use `BRKB` in the universe with a note (provider clients map
  to their own punctuation, e.g. Polygon `BRK.B`, SEC `BRK-B`).

## Corrections

- DuckDB `TIMESTAMP` columns convert tz-aware datetimes to **local** naive time on insert (machine is UTC+4)
  → always normalize to naive UTC before insert (`_to_db_ts`). Applied in brain/paper/fundamentals stores
  and, as of 2026-07-11, the ingestion spine `storage.py` as well.
- Long factor fixtures: generating synthetic OHLCV records in-test (seeded, `tests/synthetic.py`) beats
  committing 14 × 600-row CSVs; existing short CSVs stay for ingestion/provider tests.
- Missing-benchmark exits: never write a placeholder (NaN) into `voo_return_same_period` — an "exit" journal
  entry requires the real figure; when VOO data is absent, write a "review" entry that says so instead.
- Synthetic random walks with high vol can out-drift the intended winner — pin per-symbol seeds in tests
  after checking the actual 12-1 numbers (TSLA needed seed=4).
- Polygon.io rebranded to **Massive.com**; keys live at https://massive.com/dashboard/api-keys
  (not polygon.technology). `api.polygon.io` still works. Free tier rejects old history windows —
  use ~last 400 trading days; retry HTTP 429 with ≥60s backoff.
- FMP moved to `/stable/...` query endpoints; `/api/v3/...` is legacy-only after 2025-08-31 for new keys.
- `FundamentalsStore` auto-creates `fundamentals_snapshots` on construct (do not assume `init_db` did it).

## Resume (2026-07-10, after session limit)

- Session limits mid-build are survivable: code was already green; the resume job was verify → sync notes →
  report, NOT rebuild. Re-confirm state from tool output before touching anything.
- Post-resume verified baseline: **420 tests passing** (Fable slice + Cursor's completed `.kiro` plumbing:
  `evidence.py`, `benchmark.py`, `cli.py`, `providers/polygon.py`, quality/property/scope tests — 60/60 tasks).
- Guardrail sweep note: `benchmark.py` legitimately *contains* the strings BUY/SELL — as a forbidden-token
  checklist it asserts its own output against. Grep sweeps must whitelist enforcement code.
- When Bash/Edit throttle ("classifier unavailable"): wait and retry; read-only tools keep working — do not
  switch architectures or improvise alternate write paths.

## Post-main shakeout (2026-07-11)

- `main` commit `69b1d0c` verified on `origin/main`; `.env` gitignored with keys set.
- Live shakeout: Polygon 14/14 OHLCV; FMP 9/10 equities (BRKB 402 free-plan); SEC 10/10 equities.
- Still deferred: Kronos inference (RankIC first), UI/charting, multi-agent, real-money/PM.
