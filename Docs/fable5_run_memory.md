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

## Strategy-pack slice (2026-07-11)

- `tests/test_models.py::test_today_trading_date_accepted` flakes for ~4h after local midnight on this
  UTC+4 machine: the validator's clock is UTC, the test used local `date.today()`. Fixed the test to use
  UTC today — date-boundary tests must use the same clock as the code under test.
- `BrainStore.record_test_run` refuses unapproved specs — gate tests must `approve_spec(..., "anant")`
  before `run_and_record`, even for throwaway specs.
- Live free-tier depth is **274 sessions** (2025-06 → 2026-07), not "400 trading days": momentum warm-up
  (253) leaves ~21 strategy sessions, so even the OOS gate fails closed on live data (needs 60+60).
  Walk-forward needs ≥ 1,010 sessions (~4 years). Offline synthetic proves capability; live records
  honest failures until history deepens.
- Fundamentals in the live DB: SEC 12 quarters vs FMP 4 for every equity — pick ONE source per symbol
  (most snapshots wins) before `to_factor_inputs`, or duplicated quarters distort margin-stability stdev.
- Confirmed: point-in-time fundamentals gating (fiscal_period_end + 90d lag ≤ rebalance date) plus
  "decide at close i, earn from i+1" makes prefix-invariance provable in a test — truncating the future
  must leave past returns/decisions bit-identical.

## Phase 2b analysis pass (2026-07-11)

- Exact gate minima re-derived from source (R = panel sessions − 253): OOS needs R ≥ 200 (0.3·R ≥ 60);
  MC R ≥ 120; walk-forward k windows need R ≥ 630 + (k−1)·126 → 3 windows = R 882 = **panel 1135
  (~4.5y)**, 6 windows = R 1260 = **panel 1513 (~6.0y)**. Walk-forward is always the binding gate.
- Cash sessions are walk-forward poison: a test window of 0.0 returns is NOT > 0, so it counts against
  `fraction_positive`. Fundamentals depth must reach (price_start + ~12mo − 90d) or early rebalances
  sit in cash and WF fails for data reasons, not edge reasons.
- Found (not yet fixed): the study path never filters `daily_ohlcv.source` and the PK includes source —
  two providers for the same symbol/date would duplicate calendar dates and corrupt the series. Guard
  needed before any second price source lands (Phase 2b item F1).
- Live DB fundamentals are shallower than they look: 12 SEC snapshots/equity but earliest *quarterly*
  fiscal_period_end is 2023-12 (BRKB/GOOGL/META) and 2025-Q1+ for most — insufficient even for the
  4.5y price tier; SEC companyfacts backfill required.
- `providers.toml` already encodes provider depth facts: polygon free 2.0y, tiingo 5.0y (50/min,
  div-adjusted, no client yet), alpha_vantage 20y free but `split_adjusted` only (dividend-blind —
  wrong for total-return momentum vs VOO).
- DuckDB is single-writer: hit a live lock (concurrent ingest) mid-analysis; the pre-study backup copy
  in scratchpad answered the remaining read-only queries. Backup-before-write also gives you a
  queryable snapshot when the main file is locked.

## Post-main shakeout (2026-07-11)

- `main` commit `69b1d0c` verified on `origin/main`; `.env` gitignored with keys set.
- Live shakeout: Polygon 14/14 OHLCV; FMP 9/10 equities (BRKB 402 free-plan); SEC 10/10 equities.
- Still deferred: Kronos inference (RankIC first), UI/charting, multi-agent, real-money/PM.

## History deepen attempt (2026-07-11, Cursor)

- Max Basic ingest raised DuckDB from 274 → **501** sessions/symbol (first bar 2024-07-10).
- Probe for 2021-01-01 still truncates — current key is Massive **Basic** (2y), not Starter (5y).
- Default WF still needs ≥ ~1135 sessions; Phase 2b blocked until Starter+ upgrade.
- Do not loosen gate constants. Use `scripts/deepen_history.py` after upgrade.
- Graphify rebuilt (1844 nodes). Vault SoT: Session Findings — Post Base (2026-07-11).

## Go/no-go V1–V5 chore (2026-07-11, Cursor)

- Re-probed both tiers (`--start-date 2022-01-02` and `2020-07-06`): both truncate to the
  same first bar 2024-07-11 / 501 bars as the prior attempt — key is still Massive Basic,
  no upgrade detected. Stopped per solution-design §2 stop condition; did not ingest,
  did not touch SEC backfill, did not run the study.
- Measured V1–V5 read-only against the current 501-session DB: V2 (single source,
  `polygon`/`split_dividend_adjusted`, 0 nulls), V3 (0 calendar mismatches vs VOO), and V4
  (0 split-residue hits >35%) all **pass already** and are depth-independent — they will
  keep passing once more same-source rows are appended. V1 (n=501 < 1135) and V5 (earliest
  quarterly `fiscal_period_end` 2023-12-31 → 2025-04-27, 10–14 quarters vs ~20–23 needed)
  are the two real RED items, both gated on provider depth (price rows unlock later SEC
  quarters implicitly needing the same backfill window).
- Next action is a human decision (Massive plan upgrade or explicit Tiingo-client approval),
  not more Cursor automation — do not re-run probes speculatively; they cost nothing but the
  bottleneck is the plan, not the script.

## Tiingo switch resolves V1/V5 (2026-07-11, Cursor)

- User added `TIINGO_API_KEY` and explicitly ordered switching to Tiingo instead of a Massive
  upgrade. `config/providers.toml` already had a `tiingo` entry and `providers/base.py`
  already dispatched to `providers.tiingo.TiingoProvider` — only the client module itself was
  missing. Wrote it mirroring `polygon.py`'s contract; auth via `Authorization: Token <key>`
  header (never the URL), so the key never touches `request_url`, raw payloads, or stdout.
- Live probe cleared the **recommended** tier (`--start-date 2020-07-06`) on the first try:
  1511 bars, no truncation — no need to fall back to the 2022-01-02 minimum.
- Mixing two sources in `daily_ohlcv` was a stated risk (PK includes `source`) — purged all
  7014 existing `polygon` rows (`scripts/rebuild_price_source.py`, dry-run then `--confirm`)
  before backfilling the full window fresh from Tiingo, so the table stays single-source by
  construction rather than needing the F1 guard early.
- Found and fixed a real bug in `fundamentals/sec.py::parse_companyfacts`: SEC's
  `dei:EntityCommonStockSharesOutstanding` is tagged on the filing's cover-page date, not the
  fiscal period end — for AAPL this created 50 of 123 "quarter" periods with zero statement
  data, diluting the most-recent-`max_periods` tail window so raising `max_periods` alone
  couldn't reach 2020. Filtered cover-date-only periods out before slicing; 0 test regression.
- Result: V1–V5 all GREEN. N=1511/symbol (2020-07-06→2026-07-10), single source, 0 nulls,
  0 calendar mismatches, 0 split-residue hits, SEC quarterly depth to 2018–2019 for all 10
  equities. 472 tests passed (was 464). Phase 2b go/no-go is now GREEN — Fable F1–F3 may
  start; still did not touch gates/hook/universe or run the study itself.

## Phase 2b promotion study (2026-07-11, Fable)

- F1 seam is a keyword param all the way down (`--source` → `price_source` → `get_price_frame(source=...)`);
  the mixed-source failure mode is loud, not silent — duplicate calendar dates trip StrategyReturns'
  strictly-increasing-dates validator, which made the guard test easy to write (assert ValueError unfiltered,
  bit-identical study filtered).
- DuckDB reserves `rows` and `nulls` as bare column aliases — the solution design's V2 SQL needs `AS n_rows`
  / `AS null_count` when run verbatim through the Python client.
- The `--record-decision` pass re-runs the whole deterministic study, so it records a second identical
  4-record gate batch; pass `--skip-paper` on that pass or the journal/holdings artifact is written twice.
- Live result on real tiingo bars (N=1511, R=1258): 4/4 PASS at unchanged defaults — WF 5/5 windows
  positive, pooled Sharpe 1.52; DSR 0.9947 with n_trials=1 (pure PSR, no deflation credit). Net +356.82%
  vs VOO +87.10%; 0 cash sessions (SEC quarterly backfill fully prevented the cash-drag failure mode).
  Decision recorded: promote → demo_eligible. One bull-heavy regime — evidence, not proof.
- Holdings dump: `entry_type` on JournalEntry is a free string, so a new `"holdings"` entry type needed
  zero model/store changes — smallest-diff wins.

## Phase 3 LLM seam (2026-07-12)

- `gemini/gemini-2.0-flash` was retired 2026-06-01; current litellm alias is `gemini/gemini-3.5-flash`.
  `.env` / `.env.example` lag reality — confirm the alias at implement time, every time.
- Gemini 3.x Flash is a reasoning model: "thinking" tokens spend the same `max_tokens` completion
  budget, so 2048 truncated instructor's JSON mid-object. Fix: `max_tokens=8192` +
  `reasoning_effort="low"` (with `litellm.drop_params=True` so Groq/Ollama fallbacks don't 400).
- Latent bug only a first caller finds: DuckDB UUID columns come back as `uuid.UUID` objects and
  fail pydantic `str` fields — `read_api.get_quality_report` needed `str(row[0])` despite the
  table existing since Month 1. Storage round-trip tests used in-memory inserts, not UUID casts.
- Numeric-allowlist prose discipline: models leak digits through indicator names ("the RSI 14.")
  and dates even when told to quote only listed numbers. Ban digits in prose wholesale, name the
  indicator-digit trap explicitly in the system prompt, and give the runner ONE corrective retry
  that feeds the exact validator error back — that combination went from 1/2 to green live runs.
- Instructor + litellm.Router: `instructor.from_litellm(router.completion, mode=Mode.JSON)` works
  as-is; keep both imports lazy inside `LiveLLMClient.__init__` so fixture-mode CI never pays the
  litellm import cost (and C4 grep stays trivially true).
