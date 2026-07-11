# Year-Ahead Base — Architecture Contract (repo mirror)

> Mirror of the vault note `20_Progress/Projects/CS/TradingView/Year-Ahead Base — Fable 5 Architecture Contract.md`
> (decisions locked in `Session Findings — Cursor Alignment Pass (2026-07-10)`). If this file and the vault
> conflict, the vault session-findings note wins. Built by Fable 5, 2026-07-10.
>
> **Status 2026-07-10:** base complete. Fable 5 slice (brain/factors/fundamentals/gates/paper/kronos-reserved)
> and Cursor's `.kiro` ingestion plumbing (evidence, benchmark, CLI, polygon — all 60 spec tasks) are both
> landed. Full offline suite: **420 tests passing**.

## One-sentence goal

Leave a durable base for this personal US stocks/ETFs research desk that is still correct a year from now:
brain loop, factor(+fundamentals) math, four-gate promotion, paper-test contracts, Kronos reserved — not a
disposable demo.

## Settled law (do not re-open)

1. Personal-only local desk; no auth/tenancy/billing; never sold (portfolio may mention it).
2. Stocks/ETFs only. Zero Kalshi/Polymarket code, schema fields, stubs, or shared-core placeholders.
3. Python owns facts/factors/tests/paper fills. AI proposes/explains from evidence only — never invents numbers.
4. Action vocabulary everywhere: `WATCH | HOLD | ACCUMULATE | REDUCE | AVOID | INSUFFICIENT_DATA`.
5. This app is the research hub. TradingView.com = later real-trade record — out of this build.
6. Brain closed loop is the x-factor: citation → proposed spec → **human approve** → Python hook → four gates →
   promote/demote → journal link → next proposal.
7. Primary math = fixed factor stack (momentum 12-1, safety/vol, quality_fcf, valuation FCF/EV, ETF baseline
   vs VOO). TA (MA/RSI/Bollinger) = context only, never a sole action driver.
8. Kronos: reserved schema/gates only (USABLE-only input, RankIC ≥ 0.03 threshold). No inference, no
   promote/demote influence, until a RankIC validation pass happens later.
9. Demo-paper eligibility only after all four gates pass **in order**: out-of-sample → Monte Carlo →
   walk-forward → deflated Sharpe. Always vs VOO; costs, drawdown, trade count; no lookahead;
   literature-default parameters over curve-fit.
10. Paper trading: pre-approved thesis → timed auto-entry inside approved test windows. Two modes:
    (a) accelerated historical replay writing journal-as-if-time-passed; (b) live-calendar paper book with
    review jump-ahead hooks.
11. Guardrails: no fabrication; quality caps confidence; no LLM calls in the ingestion path; no broker SDKs;
    no options/futures/crypto/margin/intraday this phase; no execution language (`BUY`/`SELL`/"guaranteed"/
    "risk-free") anywhere.

## Module map

```text
src/research_data/
  models.py            # OHLCV + quality + evidence-packet models (ingestion spine — keep clean)
  config.py            # providers.toml / assets.toml loaders, API-key env validation
  env.py               # safe .env loader (gitignored file only; values never logged)
  storage.py           # DuckDB ingestion schema: daily_ohlcv, raw payloads, runs, quality reports
  normalization.py     # ProviderFetchResult → OHLCVRecord (prices only; no factor logic here)
  calendar.py          # NYSE/NASDAQ session math (shared by quality, factors, gates, paper)
  quality.py           # DataQualityAuditor: MISSING > CONTRADICTORY > STALE > INSUFFICIENT_DATA > PARTIAL > USABLE
  read_api.py          # PriceReadAPI.get_price_frame — sole price read path for downstream modules
  evidence.py          # DataEvidencePacket builder for downstream AI (no LLM calls)
  benchmark.py         # data-sanity benchmark reporter vs ETF baseline (refuses execution language)
  cli.py, __main__.py  # Typer CLI: init-db | ingest-prices | audit-prices | benchmark
  kronos_reserved.py   # Kronos evidence schema + admission gates ONLY — no inference imports
  providers/           # csv_fixture (offline default), polygon.py (rate-limited live client)
  brain/               # THE X-FACTOR — closed research loop
    models.py          #   Citation, StrategySpec (proposed|approved|rejected|retired), TestRunRecord,
                       #   PromotionDecision, JournalLink; params_delta + parent_spec_id (provenance)
    store.py           #   BrainStore: DuckDB persistence + typed APIs (approve requires a human identity)
    loop.py            #   Loop rules: legal state transitions, gate-order enforcement, eligibility
    citations.py       #   Deterministic cite-add / vault / journal_lesson ingest (no LLM)
  cards/               # EvidenceCard + CriticReview (no LLM); allowlist + gate projection + validators
  agents/              # AI harness boundary only — llm_client (fixture; Fable adds provider SDK),
                       # assemble, runner, analyst/critic prompt modules
  factors/             # deterministic scorers → structured score packets
    packets.py         #   ScorePacket + sub-score models (formula, inputs, as_of on every score)
    momentum.py        #   12-1 month total-return rank in universe
    safety.py          #   inverse rank of 12m realized vol (annualized σ of daily returns)
    quality_fcf.py     #   composite: FCF/EV, FCF margin, op-margin stability, debt (needs fundamentals)
    etf_baseline.py    #   symbol vs VOO on overlapping usable sessions
    ta_context.py      #   SMA50/200, RSI14, Bollinger, 52w drawdown — DESCRIPTIVE ONLY
    engine.py          #   FactorEngine: universe prices+fundamentals → packets (quality caps confidence)
  fundamentals/        # minimal FCF/EV-margins-debt path
    models.py          #   FundamentalsSnapshot (per statement period, full provenance)
    fmp.py             #   FMP statements client (FMP_API_KEY)
    sec.py             #   SEC EDGAR companyfacts client (SEC_USER_AGENT header, fair-access rate limit)
    store.py           #   fundamentals_snapshots DuckDB table + read API
  gates/               # four-gate promotion harness (order fixed)
    metrics.py         #   returns, Sharpe, max drawdown, trade count, cost model (bps per side)
    oos.py             #   gate 1: time-ordered train/test split, OOS degradation + net-Sharpe check
    monte_carlo.py     #   gate 2: seeded bootstrap of daily returns, tail-percentile checks
    walk_forward.py    #   gate 3: rolling windows, fraction-positive + pooled OOS Sharpe
    deflated_sharpe.py #   gate 4: Bailey/López de Prado DSR with trial count from brain test records
    harness.py         #   runs gates in order, writes TestRunRecords, sets demo-paper eligibility
  strategies/          # production strategy packs (spec hook_refs live here, not in tests/)
    quality_momentum.py#   50/50 momentum 12-1 + quality_fcf composite tilt, top-K equal weight
                       #   (Docs/PHASE2_STRATEGY_PACK.md; hook: quality_momentum_tilt_hook)
  paper/               # paper-test contracts (UI thin; storage/APIs real)
    models.py          #   Thesis (source_card_id + spec_id), PaperFill, JournalEntry, ReplayRun
    store.py           #   PaperStore: DuckDB persistence
    engine.py          #   timed auto-entry; on_lesson_journaled callback (cite lessons)
  cli.py, cli_desk.py, __main__.py  # Typer: ingest + brain/cite/analyze desk commands
scripts/
  run_quality_momentum_study.py  # manual live study: real DuckDB → hook → gates → brain + paper artifacts
tests/                 # offline by default; property tests prefixed test_property_
  synthetic.py         # seeded synthetic OHLCV + fundamentals generators (long series for factor/gate/paper tests)
  fixtures/            # short CSVs (ingestion tests) + fundamentals/ (FMP + SEC statement fixtures)
config/
  assets.toml          # 14-symbol universe: VOO VTI SPY QQQ AAPL MSFT NVDA AMZN GOOGL META BRKB JPM COST TSLA
  providers.toml       # price + fundamentals providers; API keys via env vars only
Docs/
  YEAR_AHEAD_BASE.md   # this file — keep the module map accurate when files move
  fable5_run_memory.md # short lessons from the build run (corrections + confirmed approaches)
```

## Data flow

```text
provider APIs → raw payloads (disk + DuckDB, secrets redacted)
  → normalization → daily_ohlcv → DataQualityAuditor → PriceReadAPI
  → factors (deterministic math, quality-capped confidence) ┐
  fundamentals (FMP/SEC, provenance per field) ─────────────┤
                                                            ▼
                                              ScorePacket (typed, as-of, provenance)
                                                            ▼
brain: citation → proposed spec → human approve → Python hook (strategy returns)
  → gates harness (OOS → MC → WF → DSR, vs VOO, costs) → promote/demote decision
  → paper: approved thesis → timed auto-entry (replay or live book) → journal (+VOO same-period)
  → journal lesson feeds the next proposal via Citation ingest
  → AI agents (Phase 3): assemble packets → analyst EvidenceCard → critic CriticReview
    (LLM only under agents/; human anant still approves/decides)
```

## The four gates (fixed order, literature defaults)

| # | Gate | Default pass rule | Source |
|---|---|---|---|
| 1 | Out-of-sample | time-ordered split (70/30); OOS net Sharpe > 0 AND OOS Sharpe ≥ 0.5 × in-sample Sharpe | Pardo 1992 degradation heuristic |
| 2 | Monte Carlo | seeded bootstrap (1000 paths) of daily net returns; 5th-percentile annualized return > 0 | resampling stress standard |
| 3 | Walk-forward | rolling train 504 / test 126 bars; ≥ 60% of OOS windows positive AND pooled OOS Sharpe > 0 | Pardo 1992 |
| 4 | Deflated Sharpe | DSR probability ≥ 0.95, trial count taken from recorded brain test runs | Bailey & López de Prado 2014/2018 |

Every gate report includes: net-of-cost returns (default 5 bps/side), max drawdown, trade count, and the
same-window VOO comparison. A failed gate is recorded, never silent — the spec is not demo-eligible.

## Fundamentals field set (minimal, provenance on every field)

revenue, operating_income (→ operating margin), operating cash flow, capex (→ FCF = OCF − capex),
total_debt, cash_and_equivalents, shares_outstanding, equity. Derived at scoring time with explicit as-of:
market_cap = price × shares; EV = market_cap + total_debt − cash; FCF/EV; FCF margin; debt/equity.
ETFs have no issuer fundamentals → quality/valuation scores return `INSUFFICIENT_DATA`, never a synthesized value.

## Kronos reservation (no inference)

`kronos_reserved.py` defines the evidence shape a future Kronos integration must fill
(`model_rankic_on_universe` is required — untested forecasts cannot surface) and two admission gates:
input quality must be `USABLE`, and validated RankIC ≥ 0.03 on this universe. Nothing downloads or runs
the model; nothing feeds promote/demote.

## Out of scope here (later phases)

- ~~`.kiro` leftovers~~ — completed by Cursor 2026-07-10 (quality tests, evidence builder, benchmark,
  polygon client, CLI, scope checks).
- ~~Live-data shakeout~~ — completed 2026-07-10/11: Polygon/Massive 14/14 OHLCV (~400d free-tier window),
  FMP `/stable` for 9/10 equities (BRKB 402 on free plan; SEC covers it), SEC companyfacts 10/10 equities.
  ETF fundamentals remain empty by design (no fabrication).
- ~~`storage.py` naive-UTC timestamps~~ — fixed 2026-07-11 (`_to_db_ts` on all TIMESTAMP inserts).
- Multi-agent debate layer, Streamlit UI, charting library choice.
- Kronos download/inference + RankIC validation pass (separate session).
- Real-money surface, TradingView.com record-keeping, Kalshi/Polymarket vertical (only after paper readiness).

## How to run

```bash
source .venv/bin/activate
pip install -e .          # once
pytest                    # offline; all tests must pass without network or keys
```

Live keys (`.env`, gitignored):
- `POLYGON_API_KEY` from [Massive dashboard](https://massive.com/dashboard/api-keys)
  (Polygon.io rebranded to Massive; **not** polygon.technology).
  Optional alias: `MASSIVE_API_KEY`. Hosts: `api.polygon.io` / `api.massive.com`.
- `FMP_API_KEY` — client uses `https://financialmodelingprep.com/stable/...` (legacy `/api/v3` is closed for new keys).
- `SEC_USER_AGENT` (format `AppName your.email@example.com`).

`research_data.env.load_dotenv()` loads them safely; values are never printed or stored unredacted.

Free-tier notes: Polygon rejects very old history with `NOT_AUTHORIZED` timeframe errors — use a recent
window (≈ last 1–2 years). Rate limit ≈ 5/min; the client retries HTTP 429. FMP may return HTTP 402
for some tickers on free plans; SEC is the free backup for equities.