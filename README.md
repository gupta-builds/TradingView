# research_data — AI Market Research Desk (Data Ingestion Foundation)

> The folder/repo name `TradingView` is a historical placeholder only. This project has **no affiliation with TradingView** and is not a trading bot, broker, or financial adviser.

## What this is

A personal, beginner-safe AI market research desk for learning, strategy testing, and disciplined investment reasoning. This repository currently implements the **Data Ingestion Foundation**: a provider-agnostic pipeline that fetches daily OHLCV data for a fixed US equity/ETF universe, stores raw payloads and normalized records in DuckDB with full provenance, and produces data-quality reports that gate any downstream strategy or AI work.

## What this is not

- Not an auto-trading bot or broker integration.
- Not financial advice, and never speaks in execution language (`BUY`, `SELL`, "guaranteed", "risk-free").
- No real-money, intraday, options, futures, crypto, or margin/leverage paths.
- No LLM calls anywhere in the ingestion path — AI is a downstream consumer of audited evidence, never the source of facts.

## Status

Implementing `.kiro/specs/data-ingestion-foundation/` (a design-first spec: `requirements.md` → `design.md` → `tasks.md`). See `tasks.md` for granular task status and `CLAUDE.md` for the architecture, module map, and data flow.

## Setup

```bash
pip install -e .
pytest
```

Activate the existing `.venv` with `source .venv/bin/activate` if needed. API keys (e.g. `POLYGON_API_KEY`) are read from environment variables; the `csv_fixture` provider needs no key and is what the test suite uses.

## Roadmap

Data foundation → deterministic strategy/backtest engine → evidence cards → AI analyst + risk critic → paper-trading journal → dashboard. `CLAUDE.md` documents the guardrails every later phase must respect (provenance, confidence caps, no fabrication, ETF-baseline comparisons, no execution language).
