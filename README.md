# research_data — Personal AI Market Research Desk

> The folder/repo name `TradingView` is a historical placeholder only. This project has **no affiliation with TradingView** and is not a trading bot, broker, or financial adviser.

[![CI](https://github.com/gupta-builds/TradingView/actions/workflows/ci.yml/badge.svg)](https://github.com/gupta-builds/TradingView/actions/workflows/ci.yml)

## What this is

A personal, beginner-safe AI market research desk for learning, strategy testing, and disciplined investment reasoning. **`main` holds the year-ahead base:** DuckDB ingestion with provenance, evidence/benchmark/CLI, brain closed loop, factor math, fundamentals (FMP/SEC), four-gate promotion harness, paper-test contracts, and Kronos reserved (no inference).

## What this is not

- Not an auto-trading bot or broker integration.
- Not financial advice, and never speaks in execution language (`BUY`, `SELL`, "guaranteed", "risk-free").
- No real-money, intraday, options, futures, crypto, or margin/leverage paths.
- No LLM calls anywhere in the ingestion path — AI is a downstream consumer of audited evidence, never the source of facts.

## Status

Year-ahead base complete on `main` (ingestion foundation tasks 1–14 + brain/factors/fundamentals/gates/paper). Architecture: `Docs/YEAR_AHEAD_BASE.md`. How to contribute after this: `Docs/GITHUB_WORKFLOW.md`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # fill keys locally; never commit .env
pytest -q
```

API keys (`POLYGON_API_KEY`, `FMP_API_KEY`, `SEC_USER_AGENT`) are read from the environment. The `csv_fixture` provider needs no key and is what CI uses.

## GitHub workflow (required from now on)

1. Branch off `main` (`feat/…`, `fix/…`, `chore/…`) — do not push features straight to `main`.
2. Run `pytest -q` locally.
3. Open a PR → wait for **CI** (pytest on 3.11 + 3.12).
4. Merge only when CI is green.

Details: `Docs/GITHUB_WORKFLOW.md`.

## Roadmap

Live-data shakeout → RankIC/Kronos validation (optional) → agents on evidence packets → UI/charts → real-money instructions later → prediction-market vertical only after stocks paper readiness. Guardrails in `CLAUDE.md` apply to every phase.
