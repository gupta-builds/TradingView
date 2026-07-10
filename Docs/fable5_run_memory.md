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
  → always normalize to naive UTC before insert (`_to_db_ts` in brain/store.py; reused pattern for paper store).
  Existing `storage.py` has the same latent issue — flagged as a Cursor leftover, do not fix drive-by.
- Long factor fixtures: generating synthetic OHLCV records in-test (seeded, `tests/synthetic.py`) beats
  committing 14 × 600-row CSVs; existing short CSVs stay for ingestion/provider tests.
- Missing-benchmark exits: never write a placeholder (NaN) into `voo_return_same_period` — an "exit" journal
  entry requires the real figure; when VOO data is absent, write a "review" entry that says so instead.
- Synthetic random walks with high vol can out-drift the intended winner — pin per-symbol seeds in tests
  after checking the actual 12-1 numbers (TSLA needed seed=4).

## Resume (2026-07-10, after session limit)

- Session limits mid-build are survivable: code was already green; the resume job was verify → sync notes →
  report, NOT rebuild. Re-confirm state from tool output before touching anything.
- Post-resume verified baseline: **420 tests passing** (Fable slice + Cursor's completed `.kiro` plumbing:
  `evidence.py`, `benchmark.py`, `cli.py`, `providers/polygon.py`, quality/property/scope tests — 60/60 tasks).
- Guardrail sweep note: `benchmark.py` legitimately *contains* the strings BUY/SELL — as a forbidden-token
  checklist it asserts its own output against. Grep sweeps must whitelist enforcement code.
- When Bash/Edit throttle ("classifier unavailable"): wait and retry; read-only tools keep working — do not
  switch architectures or improvise alternate write paths.
