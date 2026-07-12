# Phase 3 — Runbook: AI card live smoke

> Env-gated. Never part of default `pytest -q`.
> Status 2026-07-12: LLM seam landed on `feat/phase3-llm-seam` (Fable).

## Prerequisites

1. Phase 3 prereqs + LLM seam on the branch (cards/, agents/, CLI).
2. `RESEARCH_DATA_LLM=live` and provider key(s) in `.env` (`GEMINI_API_KEY` and/or `GROQ_API_KEY`; optional `OLLAMA_API_BASE`).
3. DuckDB with demo_eligible `quality_momentum_tilt_top3` and **tiingo** NVDA history.
4. Confirm current Gemini alias in `.env` / `.env.example` (as of 2026-07-12: `gemini/gemini-3.5-flash` — `gemini-2.0-flash` retired).

## Commands

```bash
source .venv/bin/activate
export RESEARCH_DATA_LLM=live

# Full E2 smoke (card + critic + planted false Sharpe + vault mirror)
python scripts/live_ai_card_smoke.py --db data/market.duckdb --symbol NVDA

# Desk CLI (mixed-source DBs need --price-source tiingo)
python -m research_data.cli analyze-symbol NVDA \
  --as-of 2026-07-10 --price-source tiingo \
  --spec-id 5f003778-42bc-4d8a-ac12-839699d98a02

python -m research_data.cli critique-spec 5f003778-42bc-4d8a-ac12-839699d98a02 \
  --symbol NVDA --as-of 2026-07-10 --price-source tiingo
```

## DoD checks (E2 / A3)

1. Card numbers ⊆ NumericAllowlist from ScorePacket + gate projection.
2. Blind-diff vs Phase 2b study facts where applicable (NVDA replay +939.09% vs VOO +86.46% — journal context only; do not invent new study numbers).
3. Planted false Sharpe in critic input → CriticReview reject / fail closed.
4. Default verbosity: pass/fail only (no full prompt dump).
5. One-way vault mirror file written under `data/cards/` (or `--vault-mirror` path).

## Blocked path (no LLM)

```bash
RESEARCH_DATA_LLM=fixture python -m research_data.cli analyze-symbol NVDA --quality missing
# → action=INSUFFICIENT_DATA, zero LLM calls
```

## Mixed-source note

If `daily_ohlcv` holds both `polygon` and `tiingo` rows, always pass `--price-source tiingo` (smoke defaults to it). Unfiltered frames duplicate calendar dates and corrupt scores.
