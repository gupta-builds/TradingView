# Implementation Plan: Data Ingestion Foundation

## Overview

This plan implements a provider-agnostic market data ingestion system in Python using DuckDB for local storage, Pydantic for validation, and a CLI interface via Typer. The implementation proceeds bottom-up: configuration and models first, then storage, providers, normalization pipeline, quality auditing, read API, benchmark reporter, evidence packets, and finally the CLI that wires everything together.

## Tasks

- [x] 1. Set up project structure, configuration, and core models
  - [x] 1.1 Create project directory structure and configuration files
    - Create `config/assets.toml` with V1 universe (VOO, VTI, SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META) and benchmark mappings
    - Create `config/providers.toml` with Polygon as default, csv_fixture for tests, and provider metadata fields (source_name, source_url, license_note, requires_api_key, rate_limit, adjustment_policy)
    - Create `src/research_data/__init__.py`
    - Create `src/research_data/config.py` to load and validate TOML configuration
    - _Requirements: 1.1, 1.5, 1.6, 1.7, 9.2_

  - [x] 1.2 Implement Pydantic models and enumerations
    - Create `src/research_data/models.py` with QualityStatus enum, PriceAdjustment enum, OHLCVRecord model, ProviderCapabilities model, ProviderFetchResult model, DataQualityReport model, DataEvidencePacket model, and EvidenceRef model
    - Implement all validation rules on OHLCVRecord: positive prices, high >= open/close, low <= open/close, non-negative volume, positive adjusted_close when present, no future dates, uppercase symbol constraint, raw_payload_hash reference check
    - Define InsufficientDataError exception class
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 12.1, 12.2, 12.4_

  - [x] 1.3 Write property test for OHLCV validation (Property 1)
    - **Property 1: OHLCV Validation Rejects Invalid Records**
    - Use Hypothesis to generate OHLCVRecords with invalid fields (non-positive prices, high < low, future dates, lowercase symbols) and verify all are rejected
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8**

  - [x] 1.4 Write unit tests for models
    - Test valid OHLCVRecord construction succeeds
    - Test each validation rule rejects invalid data independently
    - Test enum serialization/deserialization
    - Test ProviderCapabilities and ProviderFetchResult construction
    - _Requirements: 5.1–5.7_

- [x] 2. Implement storage layer and DuckDB schema
  - [x] 2.1 Implement DuckDB schema initialization in `src/research_data/storage.py`
    - Create `init_db` function that creates assets, providers, ingestion_runs, raw_market_payloads, daily_ohlcv, and data_quality_reports tables using CREATE TABLE IF NOT EXISTS
    - Create indexes on daily_ohlcv for (symbol, trading_date) and (quality_status)
    - Enforce composite primary key (symbol, trading_date, source, price_adjustment) on daily_ohlcv
    - Implement batch insert (up to 5000 records per transaction) with transaction abort on failure
    - Implement upsert logic for duplicate primary keys (overwrite existing record)
    - Seed provider and asset metadata from config files
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 2.2 Write property test for OHLCV round-trip integrity (Property 2)
    - **Property 2: OHLCV Round-Trip Integrity**
    - Use Hypothesis to generate valid OHLCVRecords, store in DuckDB, read back, and verify all fields are identical
    - **Validates: Requirements 4.1, 10.1, 10.4**

  - [x] 2.3 Write property test for duplicate primary key handling (Property 12)
    - **Property 12: Duplicate Primary Key Rejection**
    - Use Hypothesis to generate records with identical (symbol, trading_date, source, price_adjustment) and verify upsert behavior
    - **Validates: Requirements 8.2**

  - [x] 2.4 Write unit tests for storage
    - Test init_db creates all tables
    - Test batch insert writes correct number of records
    - Test transaction abort on simulated write failure leaves previous state intact
    - Test ingestion run recording with all fields
    - _Requirements: 8.1, 8.4, 8.5, 8.6_

- [x] 3. Implement provider registry and base provider interface
  - [x] 3.1 Implement Provider Registry in `src/research_data/providers/base.py`
    - Define PriceProvider Protocol with `fetch_daily_ohlcv` method signature
    - Implement ProviderRegistry class that loads config/providers.toml, validates required fields, and returns concrete provider instances
    - Validate API key presence from environment variables before network calls
    - Reject unknown provider names with error listing registered providers
    - Expose provider capabilities to quality auditor
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2_

  - [x] 3.2 Write property test for provider registry validation (Property 10)
    - **Property 10: Provider Registry Rejects Invalid Configuration**
    - Use Hypothesis to generate provider configs with missing required fields and verify registry refuses to load them
    - **Validates: Requirements 1.1, 1.2**

  - [x] 3.3 Write unit tests for provider registry
    - Test valid config loads successfully
    - Test missing required fields produce specific error messages
    - Test missing API key exits before network call
    - Test unknown provider name rejected with available providers listed
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.7_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement CSV fixture provider and raw payload writer
  - [x] 5.1 Implement CSV fixture provider in `src/research_data/providers/csv_fixture.py`
    - Conform to PriceProvider protocol
    - Load deterministic sample data from `tests/fixtures/` covering at least 3 V1 symbols with minimum 5 trading days each
    - Include both valid records and records that trigger validation failures
    - Return ProviderFetchResult objects identical in structure to live providers
    - No network calls
    - _Requirements: 15.1, 15.2, 15.5_

  - [x] 5.2 Create test fixture data files in `tests/fixtures/`
    - Create CSV files for VOO, SPY, MSFT with at least 60 trading days of realistic OHLCV data
    - Include records with invalid data (negative prices, future dates) to test validation rejection
    - Include records with gaps to test quality auditing
    - _Requirements: 15.1, 15.2_

  - [x] 5.3 Implement raw payload writer in `src/research_data/storage.py`
    - Write raw JSON/CSV to `data/raw/provider=<provider>/date=<retrieved_date>/<symbol>_<hash_prefix_8chars>.<format>`
    - Compute SHA-256 content hash and store in raw_market_payloads table
    - Record run_id, source_name, symbol, retrieved_at, request_endpoint, request_params_json, payload_path, payload_format, payload_bytes
    - Abort normalization if raw write fails
    - Never overwrite existing raw payload files
    - Skip duplicate hash insertion, link to existing payload
    - Redact secrets from request metadata (match field names containing key, token, secret, password, authorization)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 14.2_

  - [x] 5.4 Write property test for raw payload hash consistency (Property 3)
    - **Property 3: Raw Payload Hash Consistency**
    - Use Hypothesis to generate raw payloads, write to disk, and verify stored SHA-256 matches recomputed hash from file
    - **Validates: Requirements 3.2, 3.3**

  - [x] 5.5 Write property test for no secrets in stored metadata (Property 13)
    - **Property 13: No Secrets in Stored Metadata**
    - Use Hypothesis to generate request metadata with secret-like fields and verify they are redacted in stored records
    - **Validates: Requirements 3.5, 14.2, 14.4**

  - [x] 5.6 Write property test for no data fabrication (Property 11)
    - **Property 11: No Data Fabrication on Empty Provider Response**
    - Use Hypothesis to generate empty provider responses and verify zero normalized records stored and MISSING quality status
    - **Validates: Requirements 2.4, 7.2**

- [x] 6. Implement normalizer and market calendar
  - [x] 6.1 Implement normalizer in `src/research_data/normalization.py`
    - Convert provider-specific payloads into canonical OHLCVRecord rows
    - Map provider adjustment_policy to PriceAdjustment enum (RAW, SPLIT_ADJUSTED, SPLIT_DIVIDEND_ADJUSTED, UNKNOWN)
    - Store adjusted_close separately from close when provider supplies both
    - Set defaults: split_factor=1.0, dividend_cash=0.0 when not supplied
    - Derive trading_date using exchange timezone from Market_Calendar
    - Skip records that fail normalization, preserve raw payload, increment rejected count
    - Populate provenance fields (source, retrieved_at, data_as_of, raw_payload_hash)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 6.2 Implement market calendar in `src/research_data/calendar.py`
    - Use `pandas_market_calendars` or `exchange_calendars` package
    - Determine expected trading sessions for NYSE/Nasdaq symbols
    - Exclude weekends and exchange holidays
    - Compute latest expected session considering 16:00 ET close
    - Support at least 5 years of historical sessions
    - Return error for unsupported date ranges
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 6.3 Write property test for market calendar (Property 6)
    - **Property 6: Market Calendar Excludes Non-Trading Days**
    - Use Hypothesis to generate date ranges and verify no returned session is a Saturday, Sunday, or known holiday
    - **Validates: Requirements 6.2, 6.4**

  - [x] 6.4 Write property test for normalizer price adjustment mapping (Property 18)
    - **Property 18: Normalizer Price Adjustment Mapping**
    - Use Hypothesis to generate provider responses with various adjustment policies and verify correct PriceAdjustment mapping
    - **Validates: Requirements 4.2, 4.4**

  - [x] 6.5 Write unit tests for normalizer and calendar
    - Test normalizer converts fixture data correctly
    - Test normalizer skips unparseable records and increments rejected count
    - Test calendar excludes weekends and holidays
    - Test calendar latest expected session logic around 16:00 ET
    - _Requirements: 4.1–4.6, 6.1–6.5_

- [ ] 7. Implement data quality auditor
  - [x] 7.1 Implement quality auditor in `src/research_data/quality.py`
    - Generate per-symbol quality reports after ingestion
    - Assign QualityStatus based on precedence: MISSING > CONTRADICTORY > STALE > INSUFFICIENT_DATA > PARTIAL > USABLE
    - Compute confidence_cap: MISSING=0.0, CONTRADICTORY≤0.3, STALE≤0.5, INSUFFICIENT_DATA≤0.4, PARTIAL≤0.7, USABLE=1.0
    - Detect: zero valid rows, stale data vs latest expected session, contradictory OHLC, insufficient history, duplicate dates, non-monotonic dates, UNKNOWN price_adjustment
    - Record expected_sessions, valid_sessions, missing_sessions, rejected_records, issues_json
    - Support cross-provider disagreement detection (>1% difference)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10_

  - [-] 7.2 Write property test for quality status classification (Property 5)
    - **Property 5: Quality Status Classification Correctness**
    - Use Hypothesis to generate various data scenarios and verify correct QualityStatus assignment per precedence rules
    - **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**

  - [-] 7.3 Write property test for rejected records counting (Property 17)
    - **Property 17: Rejected Records Counted in Quality Report**
    - Use Hypothesis to generate batches with N invalid records and verify rejected_records equals N
    - **Validates: Requirements 5.9, 13.4**

  - [-] 7.4 Write unit tests for quality auditor
    - Test MISSING status when zero rows
    - Test STALE status when latest bar is old
    - Test CONTRADICTORY status for impossible OHLC
    - Test INSUFFICIENT_DATA for short history
    - Test PARTIAL for moderate history
    - Test USABLE for complete data
    - Test precedence ordering
    - _Requirements: 7.1–7.10_

- [~] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Implement Read API and evidence packets
  - [-] 9.1 Implement Read API in `src/research_data/read_api.py`
    - Implement `get_price_frame` returning OHLCV rows ordered by (symbol, trading_date)
    - Filter by source and price_adjustment when specified
    - Exclude MISSING, CONTRADICTORY, INSUFFICIENT_DATA when require_usable=True
    - Include provenance metadata (source, retrieved_at, data_as_of, raw_payload_hash, quality_status) on each record
    - Raise InsufficientDataError when symbol has fewer rows than min_rows
    - Return empty collection for zero-match queries (no error)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [-] 9.2 Implement evidence packet builder in `src/research_data/evidence.py`
    - Build DataEvidencePacket from stored data with all required fields
    - Set confidence_cap ≤ 0.5 for STALE or INSUFFICIENT_DATA
    - Include at least one evidence_ref per contributing data source
    - Refuse construction when required provenance fields are unavailable
    - Ensure JSON serialization round-trip via Pydantic
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [~] 9.3 Write property test for Read API ordering (Property 7)
    - **Property 7: Read API Ordering Guarantee**
    - Use Hypothesis to generate multi-symbol datasets and verify returned rows are monotonically ordered by (symbol, trading_date)
    - **Validates: Requirements 10.1**

  - [~] 9.4 Write property test for Read API usability filter (Property 8)
    - **Property 8: Read API Usability Filter**
    - Use Hypothesis to generate records with various quality statuses and verify require_usable=True excludes MISSING, CONTRADICTORY, INSUFFICIENT_DATA
    - **Validates: Requirements 10.2**

  - [~] 9.5 Write property test for Read API source/adjustment filtering (Property 9)
    - **Property 9: Read API Source and Adjustment Filtering**
    - Use Hypothesis to generate records with multiple sources/adjustments and verify filters return exact matches only
    - **Validates: Requirements 10.5**

  - [~] 9.6 Write property test for evidence packet completeness (Property 15)
    - **Property 15: Evidence Packet Completeness and Confidence Cap**
    - Use Hypothesis to generate evidence packets and verify all required fields present and confidence_cap constraints hold
    - **Validates: Requirements 12.1, 12.2, 12.3**

  - [~] 9.7 Write property test for evidence packet serialization (Property 16)
    - **Property 16: Evidence Packet Serialization Round-Trip**
    - Use Hypothesis to generate valid DataEvidencePacket instances, serialize to JSON, deserialize, and verify equivalence
    - **Validates: Requirements 12.4**

- [ ] 10. Implement benchmark reporter
  - [~] 10.1 Implement benchmark reporter in `src/research_data/benchmark.py`
    - Compute total return, annualized return, annualized volatility, maximum drawdown, latest data date, missing-session count, benchmark excess return, and quality status
    - Compare against configured ETF baseline (default VOO) using overlapping sessions only
    - Refuse computation when symbol has INSUFFICIENT_DATA, MISSING, or STALE status
    - Refuse computation when fewer than 50 valid sessions
    - Refuse benchmark excess return when overlapping sessions < 50
    - Map QualityStatus to output labels: USABLE→"usable", STALE→"stale", INSUFFICIENT_DATA/MISSING→"insufficient_data", PARTIAL/CONTRADICTORY→"needs_review"
    - Never use BUY, SELL, HOLD or execution language
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [~] 10.2 Write property test for benchmark refuses insufficient data (Property 20)
    - **Property 20: Benchmark Reporter Refuses Insufficient Data**
    - Use Hypothesis to generate symbols with INSUFFICIENT_DATA or MISSING status and verify metrics computation is refused
    - **Validates: Requirements 11.3**

  - [~] 10.3 Write property test for no execution language (Property 14)
    - **Property 14: No Execution Language in System Output**
    - Use Hypothesis to generate various benchmark outputs and verify no BUY/SELL/HOLD directives appear
    - **Validates: Requirements 9.5, 11.4, 11.5**

  - [~] 10.4 Write unit tests for benchmark reporter
    - Test correct metric computation with known fixture data
    - Test refusal for insufficient data
    - Test overlapping session logic
    - Test quality status label mapping
    - _Requirements: 11.1–11.6_

- [ ] 11. Implement Polygon provider
  - [~] 11.1 Implement Polygon provider in `src/research_data/providers/polygon.py`
    - Conform to PriceProvider protocol
    - Implement fetch_daily_ohlcv with rate limiting (5 calls/minute for free tier)
    - Implement retry logic: up to 3 retries with exponential backoff starting at 2 seconds
    - Handle empty responses (return zero records, no fabrication)
    - Handle network errors and HTTP 5xx with retries
    - Include rate_limit_state in ProviderFetchResult
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [~] 11.2 Write unit tests for Polygon provider
    - Test successful fetch with mocked HTTP responses
    - Test rate limit backoff behavior
    - Test retry on 5xx errors
    - Test empty response handling
    - _Requirements: 2.1–2.5_

- [ ] 12. Implement CLI interface
  - [~] 12.1 Implement CLI in `src/research_data/cli.py`
    - Use Typer for typed command signatures
    - Implement `init-db` command: create DuckDB and all tables at specified or default path
    - Implement `ingest-prices` command: fetch, store raw, normalize, validate, write quality reports, print per-symbol summary
    - Implement `audit-prices` command: print coverage, freshness, gaps, quality status
    - Implement `benchmark` command: print all 8 metrics, fail with non-zero exit code if any metric cannot be computed
    - Default symbols to V1_Universe, start_date to 365 days ago, end_date to today, provider to first configured, adjusted to True
    - Exit with non-zero code and usage message for invalid commands/arguments
    - Never output BUY/SELL/HOLD language
    - Verify .env is in .gitignore before loading API keys
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 14.1, 14.5_

  - [~] 12.2 Wire ingestion pipeline end-to-end
    - Connect CLI → ProviderRegistry → Provider → RawPayloadWriter → Normalizer → Validator → MarketCalendar → QualityAuditor → Storage
    - Record ingestion runs with all metadata
    - Handle partial runs (rate limit) and failed runs (provider outage)
    - Implement error handling per design: missing API key exits early, rate limit backs off, provider outage marks failed, validation rejects bad rows
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [~] 12.3 Write property test for ingestion idempotence (Property 19)
    - **Property 19: Ingestion Idempotence for Identical Payloads**
    - Use Hypothesis to generate payloads, ingest twice, and verify no duplicate normalized records or data corruption
    - **Validates: Requirements 8.2, 8.5**

  - [~] 12.4 Write property test for raw-before-normalized ordering (Property 4)
    - **Property 4: Raw Before Normalized Ordering Invariant**
    - Verify that for every normalized record, a raw_market_payloads row exists with matching hash and earlier/equal timestamp
    - **Validates: Requirements 3.1, 5.8**

  - [~] 12.5 Write integration tests for CLI
    - Test `init-db` creates all tables in fresh DuckDB
    - Test `ingest-prices --provider csv_fixture` end-to-end pipeline
    - Test `audit-prices` prints correct quality status
    - Test `benchmark` computes metrics from fixture data
    - Test `benchmark` refuses insufficient data with non-zero exit
    - Test invalid command exits with usage message
    - _Requirements: 9.1–9.7, 15.1, 15.2_

- [ ] 13. Implement scope boundary enforcement and security checks
  - [~] 13.1 Add scope boundary validation
    - Ensure no broker SDK or order-routing dependencies in requirements/setup files
    - Ensure no intraday/tick/options/futures/crypto data paths exist
    - Ensure no LLM calls in ingestion path
    - Add `.env` to `.gitignore` if not present
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 14.1, 14.5_

  - [~] 13.2 Write unit tests for security and scope boundaries
    - Test API keys loaded only from env vars or .env
    - Test .gitignore check refuses start when .env not listed
    - Test no execution language in CLI help text
    - Test no predictive language in outputs
    - _Requirements: 14.1, 14.5, 16.5_

- [~] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Hypothesis
- Unit tests validate specific examples and edge cases
- All tests run without network access using the CSV fixture provider
- Python is the implementation language throughout (Pydantic, DuckDB, Typer, Hypothesis, pytest)
- The V1 universe is: VOO, VTI, SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3", "6.1", "6.2"] },
    { "id": 5, "tasks": ["5.4", "5.5", "5.6", "6.3", "6.4", "6.5"] },
    { "id": 6, "tasks": ["7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "7.4", "9.1", "9.2"] },
    { "id": 8, "tasks": ["9.3", "9.4", "9.5", "9.6", "9.7", "10.1"] },
    { "id": 9, "tasks": ["10.2", "10.3", "10.4", "11.1"] },
    { "id": 10, "tasks": ["11.2", "12.1"] },
    { "id": 11, "tasks": ["12.2"] },
    { "id": 12, "tasks": ["12.3", "12.4", "12.5", "13.1"] },
    { "id": 13, "tasks": ["13.2"] }
  ]
}
```
