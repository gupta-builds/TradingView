# Design Document: Data Ingestion Foundation

## Overview

The Data Ingestion Foundation is the first trust layer for a beginner-safe AI market research desk. Its job is not just to fetch prices. Its job is to create a local, timestamped, auditable market-data substrate that later strategy, backtesting, risk, evidence-card, and AI-agent modules can rely on without guessing where numbers came from.

This design replaces the earlier yfinance-first sketch with a safer, provider-agnostic architecture:

- Prefer official or licensed API providers for backend calculations.
- Keep yfinance only as a disposable developer fallback, never as the trusted default or demo claim.
- Store raw provider responses separately from normalized analytical tables.
- Preserve adjusted and unadjusted OHLCV semantics so backtests do not mix incompatible price series.
- Track source, retrieval time, data-as-of date, provider terms notes, and quality status on every batch and every normalized record.
- Make freshness checks market-calendar-aware instead of relying on naive calendar-day thresholds.
- Emit deterministic data-quality reports and evidence-ready packets before any LLM or agent workflow can summarize them.

The MVP remains no-money and advisor-only. This layer contains no broker execution, no autonomous trading, no intraday strategy optimization, no options, no crypto, no leverage, and no TradingView scraping. TradingView widgets may be used later only for visual reference UI, not as backend data.

## Research Update: 2026 Baseline

Current finance AI work points in a consistent direction: LLMs can help summarize, critique, and explain financial evidence, but the valuable systems are data-centric, provenance-heavy, and guarded. FinGPT emphasizes curated financial data pipelines. FinRobot and TradingAgents show useful patterns for specialized financial agents, but their ideas must be constrained by deterministic evidence packets, not copied as trade engines. SEC and FINRA investor materials continue to warn against AI-washing, unregistered auto-trading claims, and unrealistic return promises.

The foundation therefore optimizes for auditable data, not flashy agents. AI is a downstream consumer of validated packets. The ingestion layer must make it difficult for a later model to invent prices, filings, or confidence.

## Goals

- Provide one command to initialize local storage and ingest daily OHLCV for the V1 universe.
- Use a provider abstraction so Polygon, Tiingo, Alpha Vantage, FMP, OpenBB, or a local CSV fixture can be swapped without changing downstream strategy code.
- Store immutable raw responses plus normalized analytical records in DuckDB.
- Record complete provenance for every ingestion run, raw payload, and normalized row.
- Support adjusted close and split/dividend adjustment metadata explicitly.
- Produce data-quality reports that can gate downstream backtests and evidence cards.
- Provide a benchmark-ready read API returning time-ordered price series for `VOO`, `VTI`, `SPY`, `QQQ`, `AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, and `META`.
- Keep implementation simple enough for a local Python MVP.

## Non-Goals

- No real-money trading path.
- No broker integration.
- No autonomous agent loops.
- No intraday, tick, options, futures, crypto, margin, leverage, or day-trading workflows.
- No TradingView scraping or automation.
- No claim that AI predicts markets.
- No LLM calls inside the ingestion path.
- No distributed systems, Kafka, cloud database, or streaming infrastructure.
- No parameter optimization or performance claims in this phase.

## Architecture

```mermaid
graph TD
    subgraph External Sources
        POLY[Polygon Basic EOD]
        TIINGO[Tiingo EOD]
        AV[Alpha Vantage]
        FMP[FMP]
        SEC[SEC EDGAR]
        CSV[Local CSV Fixtures]
        OPENBB[Optional OpenBB ODP Adapter]
    end

    subgraph CLI
        CLI[research-data CLI]
    end

    subgraph Ingestion Core
        REG[Provider Registry]
        FETCH[Provider Fetchers]
        RAW[Raw Payload Writer]
        NORM[Normalizer]
        VALID[Pydantic Validators]
        CAL[Market Calendar]
        QUALITY[Data Quality Auditor]
    end

    subgraph Local Store
        DUCK[(DuckDB)]
        RAWT[raw_market_payloads]
        OHLCV[daily_ohlcv]
        RUNS[ingestion_runs]
        QREP[data_quality_reports]
        META[assets and providers]
    end

    subgraph Downstream Contracts
        READ[Price Read API]
        BENCH[Benchmark Inputs]
        PACKET[Evidence Packet Inputs]
    end

    CLI --> REG
    REG --> FETCH
    POLY --> FETCH
    TIINGO --> FETCH
    AV --> FETCH
    FMP --> FETCH
    SEC --> FETCH
    CSV --> FETCH
    OPENBB --> FETCH
    FETCH --> RAW
    RAW --> RAWT
    FETCH --> NORM
    NORM --> VALID
    VALID --> CAL
    CAL --> QUALITY
    QUALITY --> OHLCV
    QUALITY --> QREP
    QUALITY --> RUNS
    META --> QUALITY
    OHLCV --> READ
    READ --> BENCH
    READ --> PACKET
```

## Provider Decision

### Recommended V1 Default: Polygon Basic

Polygon Basic is the recommended first default for daily U.S. equity and ETF OHLCV because its current public pricing page advertises a free stocks tier with end-of-day data, reference data, corporate actions, two years of history, and a 5 calls/minute limit. That fits the V1 universe and supports 200-day moving average work without resorting to an unofficial scraped source.

### Backup Providers

| Provider | Use | Fit | Caveats |
|---|---|---|---|
| Polygon Basic | Primary daily OHLCV and reference data | Best V1 default | API key required; rate-limit-aware batching needed |
| Tiingo EOD | Backup EOD source | Good long-history EOD option | API token required; verify current terms before committing |
| FMP | Backup prices/fundamentals | Broad API surface for prices, company data, news, and statements | Provider-specific normalization and current plan limits must be checked |
| Alpha Vantage | Backup and simple demos | Easy API docs and broad asset coverage | Free daily compact limits may be too short for 200-day indicators |
| SEC EDGAR | Fundamentals and filings | Authoritative company facts and submissions | Not a price source; requires respectful fair-access headers |
| OpenBB ODP | Optional adapter layer | Promising local-first data integration and MCP path | AGPL/commercial licensing and provider configs must be reviewed |
| yfinance | Local dev fallback only | Convenient fixtures and quick experiments | Unofficial, no SLA; do not present as trusted backend source |

### Provider Selection Rules

1. The default provider must be configured in `config/providers.toml`.
2. Each provider must expose a `source_name`, `source_url`, `license_note`, `requires_api_key`, `rate_limit`, and `adjustment_policy`.
3. If a provider lacks enough history for 200-day indicators, the quality report must return `INSUFFICIENT_DATA` for those downstream features.
4. If provider terms are unclear, the provider can be used only for local experimentation and must be marked `experimental`.
5. Backend strategy calculations must use stored API data and timestamps, never chart-widget data.

## Repository Shape

```text
tradingview/
  config/
    assets.toml
    providers.toml
  data/
    market.duckdb
    raw/
      provider=polygon/
        date=YYYY-MM-DD/
          SYMBOL_YYYY-MM-DD.json
  src/
    research_data/
      __init__.py
      cli.py
      config.py
      providers/
        base.py
        polygon.py
        tiingo.py
        alpha_vantage.py
        fmp.py
        sec_edgar.py
        csv_fixture.py
        openbb_adapter.py
      models.py
      normalization.py
      calendar.py
      quality.py
      storage.py
      read_api.py
      benchmark.py
  tests/
    fixtures/
    test_models.py
    test_normalization.py
    test_quality.py
    test_storage.py
    test_cli.py
```

The package name is intentionally `research_data`, not `tradingview`, to avoid implying affiliation with TradingView.

## CLI Interface

Use `click` or `typer`; prefer `typer` if the project wants typed command signatures and richer help output.

```python
def init_db(db_path: str = "data/market.duckdb") -> None:
    """Create DuckDB tables and seed provider/asset metadata."""

def ingest_prices(
    symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    provider: str | None = None,
    adjusted: bool = True,
) -> None:
    """Fetch daily OHLCV, store raw payloads, normalize rows, and write quality reports."""

def audit_prices(
    symbols: list[str] | None = None,
    provider: str | None = None,
) -> None:
    """Print latest coverage, freshness, gaps, and quality status."""

def benchmark(
    symbols: list[str] | None = None,
    benchmark_symbol: str = "VOO",
    period: str = "1y",
) -> None:
    """Print total return, volatility, drawdown, and benchmark comparison from stored data."""
```

Example commands:

```bash
python -m research_data.cli init-db
python -m research_data.cli ingest-prices --symbols VOO SPY MSFT --start-date 2024-01-01 --provider polygon
python -m research_data.cli audit-prices --symbols VOO SPY MSFT
python -m research_data.cli benchmark --symbols VOO SPY MSFT --benchmark-symbol VOO --period 1y
```

## Component Design

### Provider Registry

`ProviderRegistry` loads provider configuration and returns a concrete provider.

```python
class ProviderCapabilities(BaseModel):
    source_name: str
    asset_classes: list[str]
    supports_daily_ohlcv: bool
    supports_adjusted_prices: bool
    supports_corporate_actions: bool
    min_history_years_free: float | None
    rate_limit_per_minute: int | None
    requires_api_key: bool
    license_note: str
    experimental: bool = False
```

Responsibilities:

- Validate provider config at startup.
- Refuse unknown providers.
- Emit a clear error when required API keys are missing.
- Expose capabilities to the quality auditor.

### Price Provider Interface

```python
class PriceProvider(Protocol):
    capabilities: ProviderCapabilities

    def fetch_daily_ohlcv(
        self,
        symbol: str,
        start: date,
        end: date,
        adjusted: bool,
    ) -> ProviderFetchResult:
        ...
```

`ProviderFetchResult` contains:

- `symbol`
- `provider`
- `request_url` or redacted endpoint
- `request_params`
- `retrieved_at`
- `raw_payload`
- `content_hash`
- `records`
- `provider_warnings`
- `rate_limit_state`

### Raw Payload Writer

Raw payloads are written before normalization. This preserves an audit trail when provider parsing changes.

Rules:

- Store raw JSON or CSV under `data/raw/provider=<provider>/date=<retrieved_date>/`.
- Store a SHA-256 content hash in DuckDB.
- Do not store secrets or API keys in raw request metadata.
- If raw write fails, abort normalization for that fetch.

### Normalizer

The normalizer converts provider-specific payloads into canonical `OHLCVRecord` rows.

Canonical semantics:

- `open`, `high`, `low`, `close`, `volume` represent raw traded prices unless `adjusted = true` is explicitly requested and provider returns fully adjusted OHLC.
- `adjusted_close` is stored separately when available.
- `split_factor` and `dividend_cash` are stored when available.
- `price_adjustment` records `raw`, `split_adjusted`, `split_dividend_adjusted`, or `unknown`.
- Timezone for daily bars is the exchange calendar date, not local machine time.

### Pydantic Models

```python
class QualityStatus(str, Enum):
    USABLE = "usable"
    PARTIAL = "partial"
    STALE = "stale"
    MISSING = "missing"
    CONTRADICTORY = "contradictory"
    INSUFFICIENT_DATA = "insufficient_data"

class PriceAdjustment(str, Enum):
    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"
    SPLIT_DIVIDEND_ADJUSTED = "split_dividend_adjusted"
    UNKNOWN = "unknown"

class OHLCVRecord(BaseModel):
    symbol: str
    asset_type: Literal["equity", "etf"]
    exchange: str | None = None
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float | None = None
    volume: int
    split_factor: float | None = None
    dividend_cash: float | None = None
    price_adjustment: PriceAdjustment
    currency: str = "USD"
    source: str
    source_record_id: str | None = None
    retrieved_at: datetime
    data_as_of: date
    raw_payload_hash: str
    quality_status: QualityStatus = QualityStatus.USABLE
```

Validation rules:

- Symbol must be uppercase and in the configured universe unless `--allow-universe-extension` is explicitly set.
- `trading_date` and `data_as_of` cannot be in the future.
- `open`, `high`, `low`, `close` must be positive.
- `high >= open`, `high >= close`, `low <= open`, and `low <= close`.
- `volume >= 0`.
- `adjusted_close`, if present, must be positive.
- `price_adjustment != UNKNOWN` is required for backtest-ready rows.
- `raw_payload_hash` must match a row in `raw_market_payloads`.

### Market Calendar

Use `pandas_market_calendars` or an equivalent exchange-calendar package. Calendar logic is required for freshness, gaps, and holiday handling.

Responsibilities:

- Determine expected trading sessions for NYSE/Nasdaq symbols.
- Avoid flagging weekends and market holidays as missing sessions.
- Support early-close metadata later, even if not needed for daily bars.
- Compute latest expected session at the time of audit.

### Data Quality Auditor

`DataQualityAuditor` evaluates symbol-level and record-level quality.

Checks:

- Provider returned no data.
- Coverage is insufficient for requested indicators.
- Missing expected trading sessions.
- Duplicate dates.
- Non-monotonic dates.
- Contradictory OHLC values.
- Missing adjustment metadata.
- Stale latest record relative to latest expected market session.
- Provider history shorter than requested backtest window.
- Cross-provider disagreement, if a secondary provider is configured.

Quality outputs:

- `USABLE`: enough clean data for requested downstream use.
- `PARTIAL`: usable for simple display or short-window metrics, not all indicators.
- `STALE`: latest bar is older than expected.
- `MISSING`: no valid rows.
- `CONTRADICTORY`: impossible or inconsistent values were found.
- `INSUFFICIENT_DATA`: not enough reliable data for the requested strategy, benchmark, or evidence card.

### Storage

DuckDB remains the local analytical store because it is simple, file-based, fast, and integrates well with pandas, Polars, Arrow, JSON, CSV, and Parquet.

#### `assets`

```sql
CREATE TABLE IF NOT EXISTS assets (
    symbol VARCHAR PRIMARY KEY,
    asset_type VARCHAR NOT NULL,
    name VARCHAR,
    exchange VARCHAR,
    currency VARCHAR DEFAULT 'USD',
    benchmark_symbol VARCHAR,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL
);
```

#### `providers`

```sql
CREATE TABLE IF NOT EXISTS providers (
    source_name VARCHAR PRIMARY KEY,
    source_url VARCHAR NOT NULL,
    requires_api_key BOOLEAN NOT NULL,
    supports_adjusted_prices BOOLEAN NOT NULL,
    supports_corporate_actions BOOLEAN NOT NULL,
    rate_limit_per_minute INTEGER,
    license_note VARCHAR NOT NULL,
    experimental BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP NOT NULL
);
```

#### `ingestion_runs`

```sql
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id UUID PRIMARY KEY,
    source_name VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    symbols_requested VARCHAR[] NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    adjusted BOOLEAN NOT NULL,
    status VARCHAR NOT NULL,
    records_fetched INTEGER DEFAULT 0,
    records_stored INTEGER DEFAULT 0,
    error_message VARCHAR,
    config_hash VARCHAR NOT NULL
);
```

#### `raw_market_payloads`

```sql
CREATE TABLE IF NOT EXISTS raw_market_payloads (
    raw_payload_hash VARCHAR PRIMARY KEY,
    run_id UUID NOT NULL,
    source_name VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    retrieved_at TIMESTAMP NOT NULL,
    request_endpoint VARCHAR,
    request_params_json JSON,
    payload_path VARCHAR NOT NULL,
    payload_format VARCHAR NOT NULL,
    payload_bytes BIGINT NOT NULL
);
```

#### `daily_ohlcv`

```sql
CREATE TABLE IF NOT EXISTS daily_ohlcv (
    symbol VARCHAR NOT NULL,
    asset_type VARCHAR NOT NULL,
    exchange VARCHAR,
    trading_date DATE NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    adjusted_close DOUBLE,
    volume BIGINT NOT NULL,
    split_factor DOUBLE,
    dividend_cash DOUBLE,
    price_adjustment VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    source_record_id VARCHAR,
    retrieved_at TIMESTAMP NOT NULL,
    data_as_of DATE NOT NULL,
    raw_payload_hash VARCHAR NOT NULL,
    quality_status VARCHAR NOT NULL,
    PRIMARY KEY (symbol, trading_date, source, price_adjustment)
);

CREATE INDEX IF NOT EXISTS idx_daily_ohlcv_symbol_date
    ON daily_ohlcv (symbol, trading_date);

CREATE INDEX IF NOT EXISTS idx_daily_ohlcv_quality
    ON daily_ohlcv (quality_status);
```

#### `data_quality_reports`

```sql
CREATE TABLE IF NOT EXISTS data_quality_reports (
    report_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    symbol VARCHAR NOT NULL,
    source_name VARCHAR NOT NULL,
    generated_at TIMESTAMP NOT NULL,
    requested_start_date DATE NOT NULL,
    requested_end_date DATE NOT NULL,
    first_available_date DATE,
    last_available_date DATE,
    expected_sessions INTEGER NOT NULL,
    valid_sessions INTEGER NOT NULL,
    missing_sessions DATE[],
    rejected_records INTEGER NOT NULL,
    quality_status VARCHAR NOT NULL,
    confidence_cap DOUBLE NOT NULL,
    issues_json JSON NOT NULL
);
```

## Read API

Downstream modules must use read APIs rather than querying tables ad hoc.

```python
class PriceReadAPI:
    def get_price_frame(
        self,
        symbols: list[str],
        start: date,
        end: date,
        source: str | None = None,
        price_adjustment: PriceAdjustment = PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
        require_usable: bool = True,
    ) -> pd.DataFrame:
        """Return time-ordered OHLCV rows with one row per symbol and trading_date."""

    def get_quality_report(
        self,
        symbol: str,
        source: str | None = None,
    ) -> DataQualityReport:
        """Return latest symbol-level quality report."""
```

Rules:

- Queries must return records ordered by `symbol, trading_date`.
- `require_usable=True` must exclude `MISSING`, `CONTRADICTORY`, and `INSUFFICIENT_DATA` rows.
- If a requested symbol lacks benchmark-compatible history, raise a typed `InsufficientDataError`.
- Read API responses must include enough metadata to build an evidence packet without re-querying provenance tables.

## Benchmark Reporter

The benchmark reporter is still part of this foundation, but it is now explicitly a data sanity tool, not a strategy engine.

Metrics:

- total return
- annualized return
- annualized volatility
- maximum drawdown
- latest data date
- missing-session count
- benchmark excess return versus `VOO` or configured ETF baseline
- quality status

The reporter must refuse to rank or label assets with `BUY`, `SELL`, or similar language. It can say `usable`, `stale`, `insufficient_data`, or `needs_review`.

## AI-Ready Evidence Contract

This phase does not call LLMs. It does, however, shapes data so later AI cannot escape provenance.

```python
class DataEvidencePacket(BaseModel):
    symbol: str
    as_of: date
    source: str
    data_window: tuple[date, date]
    latest_price_date: date | None
    price_adjustment: PriceAdjustment
    rows_available: int
    missing_sessions: list[date]
    quality_status: QualityStatus
    confidence_cap: float
    benchmark_symbol: str
    benchmark_available: bool
    evidence_refs: list[EvidenceRef]

class EvidenceRef(BaseModel):
    table: str
    key: str
    source: str
    retrieved_at: datetime
    data_as_of: date
```

Later agent frameworks can consume this packet through Pydantic AI, OpenAI Structured Outputs, OpenAI Agents SDK, or LangGraph. The architectural rule is framework-neutral: every AI output must validate against a Pydantic schema, cite packet evidence, obey confidence caps, and pass a guardrail/critic step before storage.

## Error Handling

| Scenario | System behavior |
|---|---|
| Missing API key | CLI exits before network call with provider-specific setup hint |
| Rate limit | Back off according to provider config; persist partial run status |
| Provider outage | Mark run failed for that provider; do not fabricate rows |
| Empty symbol response | Write ingestion log and quality report with `MISSING` |
| Insufficient history | Store valid rows but report `INSUFFICIENT_DATA` for affected downstream use |
| Raw payload write failure | Abort normalization for that payload |
| Validation failure | Reject bad row, keep raw payload, include rejected count in quality report |
| Market holiday/weekend | Do not count as missing session |
| Stale data | Mark latest report `STALE`; downstream evidence confidence cap must drop |
| DuckDB write failure | Abort batch transaction and leave previous state intact |
| Cross-provider disagreement | Flag issue; do not average providers silently |

## Testing Strategy

### Unit Tests

- Pydantic validation accepts valid OHLCV and rejects impossible prices.
- Provider config validation catches missing API keys and unsupported providers.
- Normalizers convert provider fixtures into canonical records.
- Market calendar gap detection skips weekends and exchange holidays.
- Quality auditor marks insufficient 100-day history as unusable for 200-day indicators.
- Raw payload hashing is stable.
- Read API returns sorted rows and excludes unusable rows when requested.

### Integration Tests

- `init-db` creates all tables.
- CSV fixture provider ingests deterministic sample data without network.
- End-to-end pipeline writes raw payloads, normalized rows, ingestion run, and quality report.
- Benchmark command prints metrics for fixture symbols and refuses insufficient data.
- A simulated provider outage produces a failed run without corrupting previous rows.

### Property Tests

Use Hypothesis where useful:

- Stored OHLC relationships remain valid after round trip.
- Ingestion is idempotent for identical raw payloads.
- Date ranges returned by read API are monotonically increasing.
- Missing data is never filled with synthetic bars.

### Optional Live-Provider Smoke Tests

Live provider tests must be opt-in with environment variables:

```bash
RUN_LIVE_MARKET_DATA_TESTS=1 POLYGON_API_KEY=... pytest tests/live/
```

They should cover one or two symbols only and must not be required in normal CI.

## Security and Privacy

- API keys come from environment variables or a local `.env` excluded from version control.
- Raw request metadata must redact tokens and secrets.
- SEC requests must declare a user agent and respect fair-access limits.
- Local data is for personal research and must not be redistributed unless provider terms explicitly allow it.
- No account credentials, broker tokens, or real-money execution code are introduced in this phase.
- AI trace/export features must be disabled or reviewed before sending sensitive local journal data to third-party services in later phases.

## Performance

The V1 universe is tiny, but the design should not force future rewrites:

- Batch inserts into DuckDB.
- Use Parquet or compressed JSON for larger raw payload archives later.
- Use provider delta fetches based on latest stored date.
- Keep read queries narrow by symbol and date.
- Avoid premature partitioning beyond simple raw folder layout.
- Consider Polars only if pandas becomes slow or memory-heavy; pandas is sufficient for MVP.

## Implementation Tasks for Codex/Cursor

1. Create `config/assets.toml` with the V1 universe and benchmark mapping.
2. Create `config/providers.toml` with Polygon as default, CSV fixtures for tests, and yfinance marked experimental if included.
3. Implement Pydantic models in `src/research_data/models.py`.
4. Implement DuckDB schema initialization in `storage.py`.
5. Implement CSV fixture provider first for deterministic tests.
6. Implement Polygon provider behind the same interface.
7. Implement raw payload writer and content hashing.
8. Implement normalizer and quality auditor.
9. Implement read API and benchmark reporter.
10. Add pytest coverage for models, storage, normalization, quality, CLI, and benchmark behavior.

## Acceptance Criteria

- `python -m research_data.cli init-db` creates a local DuckDB database.
- `python -m research_data.cli ingest-prices --provider csv_fixture` ingests fixture data end to end.
- Raw payloads are stored with content hashes before normalized rows are written.
- Every normalized OHLCV row has non-null source, retrieved_at, data_as_of, raw_payload_hash, price_adjustment, and quality_status.
- Quality reports distinguish usable, stale, missing, contradictory, and insufficient data.
- Market calendar logic prevents weekends and market holidays from being counted as missing trading sessions.
- Benchmark output includes ETF baseline comparison and quality status.
- No output uses `BUY NOW`, `SELL NOW`, or equivalent execution language.
- No TradingView data is scraped or used for backend calculations.
- Tests pass without live network access.

## Guardrails to Preserve

- AI is an analyst assistant, not an oracle.
- Missing, stale, contradictory, or too-short data must produce `INSUFFICIENT_DATA` or a lower confidence cap.
- Every later strategy and evidence card must compare against broad ETF baselines.
- Every later backtest must preserve time order and include costs, drawdown, trade count, benchmark comparison, and assumptions.
- Paper trading is practice, not proof of real-world edge.
- The local folder name `tradingview` must not appear as a product affiliation claim.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: OHLCV Validation Rejects Invalid Records

*For any* OHLCVRecord with non-positive prices, high < open, high < close, low > open, low > close, negative volume, non-positive adjusted_close, future dates, non-uppercase symbols, or unmatched raw_payload_hash, the Validator SHALL reject the record and the record SHALL NOT appear in the daily_ohlcv table.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8**

### Property 2: OHLCV Round-Trip Integrity

*For any* valid OHLCVRecord that passes validation, storing it in DuckDB and reading it back via the Read_API SHALL produce a record with identical field values for all price, volume, date, provenance, and quality fields.

**Validates: Requirements 4.1, 10.1, 10.4**

### Property 3: Raw Payload Hash Consistency

*For any* raw payload written to disk, the SHA-256 hash stored in raw_market_payloads SHALL equal the SHA-256 hash recomputed from the file at the recorded payload_path.

**Validates: Requirements 3.2, 3.3**

### Property 4: Raw Before Normalized Ordering Invariant

*For any* successfully normalized OHLCVRecord in daily_ohlcv, there SHALL exist a corresponding row in raw_market_payloads with a matching raw_payload_hash whose retrieved_at timestamp is less than or equal to the normalization write time.

**Validates: Requirements 3.1, 5.8**

### Property 5: Quality Status Classification Correctness

*For any* symbol and ingestion result, the Data_Quality_Auditor SHALL assign exactly one QualityStatus value that is consistent with the data characteristics: MISSING when zero valid rows exist, STALE when the latest bar predates the latest expected session, CONTRADICTORY when impossible OHLC relationships exist, INSUFFICIENT_DATA when history is shorter than the requested indicator window, PARTIAL when data covers some but not all indicators, and USABLE when all checks pass.

**Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**

### Property 6: Market Calendar Excludes Non-Trading Days

*For any* date returned by Market_Calendar as an expected trading session, that date SHALL NOT be a Saturday, Sunday, or recognized exchange holiday, and all returned sessions SHALL fall within the requested date range.

**Validates: Requirements 6.2, 6.4**

### Property 7: Read API Ordering Guarantee

*For any* query to the Read_API, the returned rows SHALL be monotonically ordered by (symbol, trading_date) with no out-of-order entries.

**Validates: Requirements 10.1**

### Property 8: Read API Usability Filter

*For any* query to the Read_API with require_usable=true, no returned record SHALL have a quality_status of MISSING, CONTRADICTORY, or INSUFFICIENT_DATA.

**Validates: Requirements 10.2**

### Property 9: Read API Source and Adjustment Filtering

*For any* query to the Read_API with a source or price_adjustment filter, all returned records SHALL match the specified filter values exactly.

**Validates: Requirements 10.5**

### Property 10: Provider Registry Rejects Invalid Configuration

*For any* provider configuration entry missing one or more required fields (source_name, source_url, license_note, requires_api_key, rate_limit, adjustment_policy), the Provider_Registry SHALL refuse to load that provider and emit an error identifying the missing fields.

**Validates: Requirements 1.1, 1.2**

### Property 11: No Data Fabrication on Empty Provider Response

*For any* provider and symbol combination where the provider returns an empty response, the system SHALL store zero normalized records for that symbol and the quality report SHALL reflect MISSING status.

**Validates: Requirements 2.4, 7.2**

### Property 12: Duplicate Primary Key Rejection

*For any* attempt to insert a record into daily_ohlcv with a (symbol, trading_date, source, price_adjustment) tuple that already exists, the Storage SHALL reject the duplicate insert.

**Validates: Requirements 8.2**

### Property 13: No Secrets in Stored Metadata

*For any* stored raw_market_payloads record, the request_endpoint and request_params_json fields SHALL NOT contain API keys, tokens, or secret values.

**Validates: Requirements 3.5, 14.2, 14.4**

### Property 14: No Execution Language in System Output

*For any* output produced by the CLI, Benchmark_Reporter, or Read_API, the text SHALL NOT contain the phrases "BUY NOW", "SELL NOW", "BUY", "SELL", or equivalent execution directives.

**Validates: Requirements 9.5, 11.4, 11.5**

### Property 15: Evidence Packet Completeness and Confidence Cap

*For any* generated Evidence_Packet, all required fields (symbol, as_of, source, data_window, quality_status, confidence_cap, benchmark_symbol, evidence_refs) SHALL be present, each evidence_ref SHALL include table, key, source, retrieved_at, and data_as_of, and when quality_status is STALE or INSUFFICIENT_DATA the confidence_cap SHALL be strictly less than the default maximum.

**Validates: Requirements 12.1, 12.2, 12.3**

### Property 16: Evidence Packet Serialization Round-Trip

*For any* valid DataEvidencePacket instance, serializing to JSON and deserializing back SHALL produce an equivalent object with all fields preserved.

**Validates: Requirements 12.4**

### Property 17: Rejected Records Counted in Quality Report

*For any* ingestion batch containing N records that fail validation, the resulting quality report SHALL have rejected_records equal to N, and the raw payloads for those records SHALL still exist in raw_market_payloads.

**Validates: Requirements 5.9, 13.4**

### Property 18: Normalizer Price Adjustment Mapping

*For any* provider response, the Normalizer SHALL map the provider's adjustment semantics to exactly one PriceAdjustment enum value (RAW, SPLIT_ADJUSTED, SPLIT_DIVIDEND_ADJUSTED, or UNKNOWN) and SHALL store adjusted_close separately from close when the provider supplies both values.

**Validates: Requirements 4.2, 4.4**

### Property 19: Ingestion Idempotence for Identical Payloads

*For any* raw payload that has already been ingested (same content hash exists in raw_market_payloads), re-ingesting the identical payload SHALL NOT create duplicate normalized records or corrupt existing data.

**Validates: Requirements 8.2, 8.5**

### Property 20: Benchmark Reporter Refuses Insufficient Data

*For any* symbol with quality_status of INSUFFICIENT_DATA or MISSING, the Benchmark_Reporter SHALL refuse to compute metrics and SHALL report the quality issue rather than producing potentially misleading numbers.

**Validates: Requirements 11.3**

## Source Index

| Source | URL | Design implication |
|---|---|---|
| SEC EDGAR APIs | https://www.sec.gov/search-filings/edgar-application-programming-interfaces | Use SEC company facts/submissions for authoritative fundamentals; no API key; JSON APIs and nightly bulk files exist. |
| SEC Accessing EDGAR Data | https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm | Declare user agent, respect fair-access request limits, and avoid wasteful crawling. |
| Polygon Stocks Pricing | https://polygon.io/stocks/ | Current free tier supports EOD U.S. stocks, reference data, corporate actions, two years of history, and 5 calls/minute. |
| Alpha Vantage Documentation | https://www.alphavantage.co/documentation/ | Useful backup provider, but free/compact history limits can be too short for 200-day features. |
| Alpha Vantage Support | https://www.alphavantage.co/support/ | Free tier currently advertises 25 requests/day and notes licensing concerns around realtime/delayed market data. |
| Tiingo EOD Ingestion Guide | https://www.tiingo.com/kb/article/the-fastest-method-to-ingest-tiingo-end-of-day-stock-api-data/ | Good backup pattern for historical EOD cache plus daily delta updates. |
| FMP Quickstart | https://site.financialmodelingprep.com/developer/docs/quickstart | Backup provider option with API-key auth and broad financial endpoints. |
| OpenBB Docs | https://docs.openbb.co/ | Optional future adapter for local-first financial data integration and AI/MCP workflows after licensing review. |
| DuckDB Python API | https://duckdb.org/docs/stable/clients/python/overview | DuckDB supports local analytical storage and direct interoperability with pandas, Polars, Arrow, CSV, JSON, and Parquet. |
| Pydantic AI Agents | https://pydantic.dev/docs/ai/core-concepts/agent/ | Later AI agents can be typed and schema-bound using Pydantic models. |
| OpenAI Structured Outputs | https://platform.openai.com/docs/guides/structured-outputs | Later LLM outputs should use JSON-schema-constrained structured outputs where supported. |
| OpenAI Agents SDK Guardrails | https://openai.github.io/openai-agents-python/guardrails/ | Later agent workflows should use input, output, and tool guardrails with tripwires. |
| LangGraph Durable Execution | https://docs.langchain.com/oss/python/langgraph/durable-execution | Future long-running/human-in-the-loop agent review can use durable execution if needed. |
| FinGPT Paper | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4489826 | Reinforces data-centric financial LLM design and temporal sensitivity. |
| FinRobot Paper | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4841493 | Supports specialized financial agents, but only downstream of deterministic evidence. |
| FINRA AI Investment Fraud Alert | https://www.finra.org/investors/insights/artificial-intelligence-and-investment-fraud | Preserve conservative AI language and avoid AI-powered return promises. |
| FINRA Auto-Trading Risk Alert | https://www.finra.org/investors/insights/auto-trading-unregistered-entities | Reinforces no autonomous trading and no beginner-friendly risk-free automation claims. |
| SEC AI-Washing Enforcement Release | https://www.sec.gov/newsroom/press-releases/2024-36 | Avoid false or exaggerated claims about AI capabilities. |
