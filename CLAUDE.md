# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

`tradingview/` is a temporary local folder name. This project is **not affiliated with TradingView**. It is a beginner-safe AI market research desk for learning, strategy testing, and disciplined investment reasoning — not a trading bot, broker, or financial adviser.

The Python package is `research_data` (installed in editable mode via `pip install -e .`). It fetches daily OHLCV data for a fixed US equity universe, stores raw payloads + normalized records in DuckDB with full provenance, and produces data-quality reports consumed by downstream AI agents.

## Commands

```bash
# Install the package in editable mode (required before tests)
pip install -e .

# Run all tests
pytest

# Run a single test file
pytest tests/test_storage.py

# Run a single test by name
pytest tests/test_models.py::test_valid_ohlcv_record_construction

# Run property-based tests only
pytest tests/test_property_*.py

# Run tests with verbose output
pytest -v
```

The `.venv` is already present; activate with `source .venv/bin/activate` if needed.

## Architecture

### Module map (`src/research_data/`)

| File | Responsibility |
|---|---|
| `models.py` | Pydantic v2 models: `OHLCVRecord` (canonical OHLCV row with full provenance), `ProviderFetchResult`, `DataQualityReport`, `DataEvidencePacket`, `QualityStatus` / `PriceAdjustment` enums |
| `config.py` | Loads `config/providers.toml` and `config/assets.toml` into typed `AppConfig`, `ProviderConfig`, `UniverseConfig`; validates required fields; resolves API key env vars |
| `storage.py` | DuckDB schema init (`init_db`), batch upsert (`batch_insert_ohlcv`), ingestion run recording, raw payload file writer (`write_raw_payload`), secret redaction (`redact_secrets`) |
| `normalization.py` | Converts `ProviderFetchResult` → `NormalizationResult`; maps provider `adjustment_policy` strings to `PriceAdjustment` enum; applies defaults (`split_factor=1.0`, `dividend_cash=0.0`); pluggable `MarketCalendarProtocol` for trading-date derivation |
| `calendar.py` | `MarketCalendar` wrapping `exchange_calendars` for NYSE/NASDAQ session detection; `get_trading_sessions`, `get_latest_expected_session`, `get_missing_sessions` |
| `quality.py` | `DataQualityAuditor` → `DataQualityReport`; applies precedence: MISSING > CONTRADICTORY > STALE > INSUFFICIENT_DATA > PARTIAL > USABLE with `confidence_cap`; cross-provider disagreement detection |
| `read_api.py` | `PriceReadAPI.get_price_frame` — downstream-facing query layer over `daily_ohlcv`; supports filtering by source, `PriceAdjustment`, `require_usable`, and `min_rows` (raises `InsufficientDataError`) |

### Data flow

```
provider APIs
→ raw payload on disk (data/raw/provider=.../date=.../)
→ raw_market_payloads table (hash-keyed, secrets redacted)
→ normalization → daily_ohlcv table (upsert, PK: symbol+date+source+adjustment)
→ DataQualityAuditor → data_quality_reports table
→ PriceReadAPI → DataEvidencePacket
→ AI agent layer (not yet implemented) → evidence card
```

### Configuration

- `config/providers.toml` — provider registry; default provider is `polygon`; required fields: `source_name`, `source_url`, `license_note`, `requires_api_key`, `rate_limit`, `adjustment_policy`
- `config/assets.toml` — V1 universe: VOO, VTI, SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META; default benchmark is `VOO`

API keys are read from environment variables (e.g. `POLYGON_API_KEY`). The `csv_fixture` provider requires no key and is used in tests.

### DuckDB schema (key tables)

- `daily_ohlcv` — PK: `(symbol, trading_date, source, price_adjustment)`; stores all provenance fields
- `raw_market_payloads` — PK: `raw_payload_hash`; file paths relative to `data/`
- `ingestion_runs` — UUID-keyed run audit trail
- `data_quality_reports` — per-symbol quality reports keyed by `report_id`

### Evidence card action labels

`WATCH | HOLD | ACCUMULATE | REDUCE | AVOID | INSUFFICIENT_DATA`

AI agents must cite timestamped evidence from `DataEvidencePacket`; they must not invent metrics, prices, or recommendations.

### Testing

Tests use `pytest` + `hypothesis` (property-based). Property-based test files are prefixed `test_property_`. The `tests/fixtures/` directory has CSV files for VOO, SPY, MSFT used by `csv_fixture` provider tests.

## Non-Negotiable Guardrails

These rules come from `.kiro/specs/data-ingestion-foundation/design.md` ("Guardrails to Preserve", "Non-Goals") and apply to every phase of this project, not just ingestion:

- No execution language anywhere in code, CLI output, or docs (`BUY`, `SELL`, "guaranteed", "risk-free"). Action fields use only `WATCH | HOLD | ACCUMULATE | REDUCE | AVOID | INSUFFICIENT_DATA`.
- No data fabrication. Missing or empty provider responses must surface as `MISSING`/`INSUFFICIENT_DATA`, never as a synthesized value.
- Confidence is always capped by data quality (see `quality.py` precedence: MISSING > CONTRADICTORY > STALE > INSUFFICIENT_DATA > PARTIAL > USABLE).
- No LLM/AI API calls inside the ingestion path (`models.py`, `config.py`, `storage.py`, `normalization.py`, `calendar.py`, `quality.py`, `read_api.py`). AI only ever consumes a `DataEvidencePacket` downstream.
- No secrets in source, fixtures, logs, or stored metadata; `.env` stays out of git.
- No broker/order-routing SDKs, and no intraday, tick, options, futures, crypto, margin, or leverage code paths in this phase.
- Every later backtest must preserve time order, include costs/drawdown/trade count, and compare against the ETF baseline (`VOO`).

Use the `guardrail-auditor` agent or `/guardrail-check` skill to verify these before merging.

## Roadmap

Current phase: **Month 1 — Data Ingestion Foundation** (this repo). Planned phases after this spec is complete: deterministic strategy/backtest engine (trend following, mean reversion, quality, valuation sanity, risk) → evidence-card schema + AI analyst/critic → paper-trading journal → Streamlit dashboard. Each phase is gated by the guardrails above; strategy and AI work should not start until the ingestion foundation's checkpoints in `tasks.md` pass.

## Claude Code tooling (`.claude/`)

- `agents/guardrail-auditor.md` — reviews a diff/PR against the guardrails above.
- `agents/spec-implementer.md` — implements the next open `tasks.md` item per `design.md`, and flags drift between `tasks.md` checkboxes and actual code.
- `skills/kiro-status` — reconciles `tasks.md` against what's actually implemented and tested.
- `skills/guardrail-check` — grep-based sweep for guardrail violations (operationalizes spec task 13).
