# Phase 3 — Runbook: AI card live smoke

> Env-gated. Never part of default `pytest -q`.

## Prerequisites

1. Cursor prereqs landed (cards/, agents/ fixture path, CLI).
2. Fable LLM client (`RESEARCH_DATA_LLM=live`, Gemini Flash via litellm.Router).
3. DuckDB with demo_eligible `quality_momentum_tilt_top3` and tiingo NVDA history.
4. Keys in `.env` only (`GEMINI_API_KEY` / `GROQ_API_KEY`); see `.env.example`.

## Commands (after Fable)

```bash
source .venv/bin/activate
export RESEARCH_DATA_LLM=live
# Confirm current Gemini Flash alias at run time
python scripts/live_ai_card_smoke.py --db data/market.duckdb --symbol NVDA
# or:
python -m research_data.cli analyze-symbol NVDA --live   # when Fable wires --live
python -m research_data.cli critique-spec <spec_id> --symbol NVDA
```

## DoD checks (E2 / A3)

1. Card numbers ⊆ NumericAllowlist from ScorePacket + gate projection.
2. Blind-diff vs Phase 2b study facts where applicable (NVDA replay +939.09% vs VOO +86.46% is documented ground truth for journal context — do not invent new study numbers).
3. Planted false Sharpe in critic input → CriticReview reject / fail closed.
4. Default verbosity: pass/fail only (no full prompt dump).

## Blocked path (works before Fable)

```bash
python -m research_data.cli analyze-symbol NVDA --quality missing
# → action=INSUFFICIENT_DATA, zero LLM calls
```
