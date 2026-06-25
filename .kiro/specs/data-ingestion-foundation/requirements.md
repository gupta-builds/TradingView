# Requirements Document

## Introduction

The Data Ingestion Foundation provides a local, timestamped, auditable market-data substrate for a beginner-safe AI market research desk. It fetches daily OHLCV data through a provider-agnostic architecture, stores raw payloads and normalized records in DuckDB, tracks complete provenance, enforces market-calendar-aware freshness, produces data-quality reports, and exposes a read API for downstream strategy, backtesting, and evidence-card modules.

## Glossary

- **CLI**: The command-line interface (`research-data`) that exposes init-db, ingest-prices, audit-prices, and benchmark commands.
- **Provider_Registry**: The component that loads provider configuration, validates it, and returns a concrete provider implementation.
- **Price_Provider**: A protocol-conforming adapter that fetches daily OHLCV data from an external source (Polygon, Tiingo, FMP, Alpha Vantage, SEC EDGAR, CSV fixture, or OpenBB).
- **Raw_Payload_Writer**: The component that persists raw provider responses to disk and records content hashes in DuckDB before normalization.
- **Normalizer**: The component that converts provider-specific payloads into canonical OHLCVRecord rows.
- **Validator**: The Pydantic-based component that enforces field constraints on OHLCVRecord instances.
- **Market_Calendar**: The component that determines expected trading sessions for NYSE/Nasdaq symbols, accounting for weekends and exchange holidays.
- **Data_Quality_Auditor**: The component that evaluates symbol-level and record-level quality and assigns a QualityStatus.
- **Storage**: The DuckDB-backed persistence layer containing assets, providers, ingestion_runs, raw_market_payloads, daily_ohlcv, and data_quality_reports tables.
- **Read_API**: The downstream-facing interface that returns time-ordered price frames and quality reports.
- **Benchmark_Reporter**: The component that computes return, volatility, drawdown, and benchmark comparison metrics from stored data.
- **Evidence_Packet**: A Pydantic model containing provenance, quality, and coverage metadata for downstream AI consumption.
- **QualityStatus**: An enumeration with values USABLE, PARTIAL, STALE, MISSING, CONTRADICTORY, and INSUFFICIENT_DATA.
- **PriceAdjustment**: An enumeration with values RAW, SPLIT_ADJUSTED, SPLIT_DIVIDEND_ADJUSTED, and UNKNOWN.
- **V1_Universe**: The initial set of symbols: VOO, VTI, SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META.
- **OHLCVRecord**: A canonical normalized daily price record with full provenance fields.

## Requirements

### Requirement 1: Provider Registry and Configuration

**User Story:** As a developer, I want a provider-agnostic registry that loads and validates provider configuration, so that I can swap data sources without changing downstream code.

#### Acceptance Criteria

1. WHEN the CLI starts, THE Provider_Registry SHALL load provider configuration from `config/providers.toml` and validate that each provider entry includes source_name, source_url, license_note, requires_api_key, rate_limit, and adjustment_policy fields.
2. IF a provider entry is missing required fields, THEN THE Provider_Registry SHALL refuse to start and emit an error message identifying the provider name and each missing field by name. THE Provider_Registry SHALL only emit errors for missing required fields and SHALL NOT emit errors for other validation scenarios.
3. IF a required API key environment variable is not set for the configured provider, THEN THE Provider_Registry SHALL exit before any network call and display a message that includes the expected environment variable name and the provider it belongs to.
4. WHEN an unknown provider name is requested, THE Provider_Registry SHALL reject the request with an error message listing all currently registered provider names.
5. THE Provider_Registry SHALL expose provider capabilities including supports_daily_ohlcv, supports_adjusted_prices, supports_corporate_actions, min_history_years_free, and rate_limit_per_minute to the Data_Quality_Auditor.
6. IF the configuration file at `config/providers.toml` does not exist or is not readable, THEN THE Provider_Registry SHALL refuse to start and emit an error message indicating the expected file path.
7. IF the configuration file contains invalid TOML syntax, THEN THE Provider_Registry SHALL refuse to start and emit an error message indicating a parse failure and the line number reported by the TOML parser.

### Requirement 2: Price Provider Interface

**User Story:** As a developer, I want each data source to conform to a common protocol, so that the ingestion pipeline can operate identically regardless of the upstream provider.

#### Acceptance Criteria

1. THE Price_Provider SHALL implement a `fetch_daily_ohlcv` method accepting symbol (string), start date (ISO 8601 date), end date (ISO 8601 date), and adjusted flag (boolean), and returning a ProviderFetchResult.
2. THE Price_Provider SHALL include in ProviderFetchResult the symbol, provider name, request endpoint or redacted URL, request parameters, retrieved_at timestamp, raw payload, content hash, parsed records, provider warnings, and rate limit state (remaining requests and reset timestamp).
3. WHEN a provider rate limit is reached, THE Price_Provider SHALL wait at least ceil(60 / rate_limit_per_minute) seconds, then retry the request up to a maximum of 3 attempts before failing.
4. IF a provider returns an empty response for a symbol, THEN THE Price_Provider SHALL return a ProviderFetchResult with zero records and no fabricated data. Other system components MAY add fabricated data after the provider returns, but the Price_Provider itself SHALL NOT fabricate data.
5. IF a provider request fails due to a network error, HTTP 5xx response, or connection timeout exceeding 30 seconds, THEN THE Price_Provider SHALL retry up to 3 times with exponential backoff starting at 2 seconds, and if all retries fail, return a ProviderFetchResult with zero records, no fabricated data, and a provider warning describing the failure reason. THE Price_Provider SHALL NOT include fabricated or cached data in intermediate responses during retry attempts.

### Requirement 3: Raw Payload Preservation

**User Story:** As a data auditor, I want every raw provider response stored immutably before normalization, so that I can trace any normalized record back to its original source.

#### Acceptance Criteria

1. WHEN a provider fetch completes, THE Raw_Payload_Writer SHALL persist the raw JSON or CSV response to `data/raw/provider=<provider>/date=<retrieved_date>/<symbol>_<content_hash_prefix_8chars>.<format>` before normalization begins.
2. WHEN a raw payload is persisted to disk, THE Raw_Payload_Writer SHALL compute a SHA-256 content hash of the raw payload and store it in the raw_market_payloads table.
3. WHEN a raw payload is persisted to disk, THE Raw_Payload_Writer SHALL record run_id, source_name, symbol, retrieved_at, request_endpoint, request_params_json, payload_path, payload_format, and payload_bytes for each raw payload.
4. IF the raw payload write fails, THEN THE Raw_Payload_Writer SHALL abort normalization for that fetch and record the failure reason in the ingestion run's error_message field.
5. THE Raw_Payload_Writer SHALL NOT store API keys, tokens, or secrets in raw request metadata.
6. THE Raw_Payload_Writer SHALL NOT overwrite or modify an existing raw payload file once written; a repeated fetch of the same provider, symbol, and date SHALL be stored as a separate file with its own content hash.
7. IF a raw payload with an identical SHA-256 content hash already exists in the raw_market_payloads table for the same symbol and source, THEN THE Raw_Payload_Writer SHALL skip inserting a duplicate row and SHALL link the current run_id to the existing payload record.

### Requirement 4: Normalization

**User Story:** As a downstream consumer, I want provider-specific payloads converted into canonical OHLCVRecord rows with consistent semantics, so that strategy code does not depend on provider format details.

#### Acceptance Criteria

1. WHEN a raw payload is successfully stored, THE Normalizer SHALL convert provider-specific fields into canonical OHLCVRecord fields including open, high, low, close, volume, adjusted_close, split_factor, dividend_cash, and price_adjustment, and SHALL populate provenance fields source, retrieved_at, data_as_of, and raw_payload_hash from the corresponding raw payload record.
2. THE Normalizer SHALL set price_adjustment to RAW when the provider's configured adjustment_policy indicates unadjusted prices, SPLIT_ADJUSTED for split-only adjustment, SPLIT_DIVIDEND_ADJUSTED for fully adjusted prices, and UNKNOWN when the provider's adjustment_policy is absent or unrecognized.
3. THE Normalizer SHALL derive trading_date by interpreting the provider's date value in the exchange's local timezone (as determined by the Market_Calendar for the symbol's listed exchange), not the local machine timezone.
4. IF the provider does not supply adjusted_close, split_factor, or dividend_cash, THEN THE Normalizer SHALL set adjusted_close to null, split_factor to 1.0, and dividend_cash to 0.0.
5. IF the provider supplies adjusted_close, THEN THE Normalizer SHALL store adjusted_close separately from close, preserving both values without overwriting.
6. WHEN normalization of an individual record fails due to missing required fields or unparseable values, THE Normalizer SHALL skip that record, preserve the raw payload, and increment the rejected count for the ingestion run's quality report.

### Requirement 5: Data Validation

**User Story:** As a data engineer, I want strict validation on every normalized record, so that impossible or inconsistent data cannot enter the analytical tables.

#### Acceptance Criteria

1. THE Validator SHALL reject any OHLCVRecord where open, high, low, or close is not strictly greater than zero.
2. THE Validator SHALL reject any OHLCVRecord where high is less than any of open, low, or close.
3. THE Validator SHALL reject any OHLCVRecord where low is greater than any of open, high, or close.
4. THE Validator SHALL reject any OHLCVRecord where volume is negative.
5. THE Validator SHALL reject any OHLCVRecord where adjusted_close is present but not strictly greater than zero.
6. THE Validator SHALL reject any OHLCVRecord where trading_date or data_as_of is later than the current UTC date at the time of validation.
7. THE Validator SHALL reject any OHLCVRecord where the symbol is not composed entirely of uppercase ASCII letters or exceeds 10 characters in length.
8. IF the allow-universe-extension flag is not set, THEN THE Validator SHALL reject any OHLCVRecord where the symbol is not present in the configured universe.
9. THE Validator SHALL reject any OHLCVRecord where raw_payload_hash does not match a row in raw_market_payloads.
10. THE Validator SHALL execute all validation checks on a normalized record before that record is written to the daily_ohlcv table, and SHALL NOT write any record that fails validation. THE system SHALL require that validation has been executed (validation_executed is true) before any record can be written, even if validation_passed is true.
11. WHEN a record fails validation, THE Validator SHALL log the record with all failing rule identifiers and include the total rejected count in the quality report for that ingestion run.

### Requirement 6: Market Calendar

**User Story:** As a data quality analyst, I want freshness and gap checks to account for weekends and exchange holidays, so that non-trading days are never flagged as missing data.

#### Acceptance Criteria

1. THE Market_Calendar SHALL determine expected trading sessions for NYSE and Nasdaq symbols using an exchange-calendar package.
2. THE Market_Calendar SHALL exclude weekends and exchange holidays from the set of expected trading sessions.
3. THE Market_Calendar SHALL compute the latest expected trading session as of the current date and time in US Eastern Time, where the current session is considered expected only after the exchange's regular close (16:00 ET); before close, the latest expected session is the previous trading day.
4. WHEN the Data_Quality_Auditor checks for missing sessions, THE Market_Calendar SHALL provide the list of expected sessions within the requested date range, supporting at least 5 years of historical sessions.
5. IF the exchange-calendar package does not cover the requested date range, THEN THE Market_Calendar SHALL return an error indicating the unsupported range and SHALL NOT silently omit sessions from the result.

### Requirement 7: Data Quality Auditing

**User Story:** As a researcher, I want automated quality reports that classify data reliability, so that downstream modules can gate their outputs on data trustworthiness.

#### Acceptance Criteria

1. WHEN an ingestion run completes, THE Data_Quality_Auditor SHALL generate a quality report for each symbol including expected_sessions, valid_sessions, missing_sessions, rejected_records, quality_status, confidence_cap (a decimal value from 0.0 to 1.0), and issues_json.
2. IF the provider returned zero valid rows for a symbol, THEN THE Data_Quality_Auditor SHALL assign MISSING status and set confidence_cap to 0.0.
3. IF the latest stored bar's trading_date is older than the latest expected market session provided by the Market_Calendar, THEN THE Data_Quality_Auditor SHALL assign STALE status and set confidence_cap to no higher than 0.5.
4. IF one or more stored records for a symbol contain adjusted_close changes that are inconsistent with the recorded split_factor and dividend_cash values, THEN THE Data_Quality_Auditor SHALL assign CONTRADICTORY status and set confidence_cap to no higher than 0.3.
5. IF the number of valid sessions for a symbol is fewer than the maximum indicator window requested by downstream modules, THEN THE Data_Quality_Auditor SHALL assign INSUFFICIENT_DATA status and set confidence_cap to no higher than 0.4.
6. IF the number of valid sessions for a symbol is at least 50 but fewer than the maximum requested indicator window, THEN THE Data_Quality_Auditor SHALL assign PARTIAL status and set confidence_cap to no higher than 0.7.
7. IF the number of valid sessions for a symbol meets or exceeds the maximum requested indicator window and no other degrading condition applies, THEN THE Data_Quality_Auditor SHALL assign USABLE status and set confidence_cap to 1.0.
8. THE Data_Quality_Auditor SHALL detect duplicate trading_dates, non-monotonic trading_dates, and records where price_adjustment is UNKNOWN as quality issues recorded in issues_json.
9. IF a secondary provider is configured, THEN THE Data_Quality_Auditor SHALL flag cross-provider disagreement when any OHLCV field for the same symbol and trading_date differs by more than 1% relative to the primary provider's value, without silently averaging values.
10. THE Data_Quality_Auditor SHALL evaluate statuses in the following precedence order (highest to lowest): MISSING, CONTRADICTORY, STALE, INSUFFICIENT_DATA, PARTIAL, USABLE, and assign the highest-precedence status that applies. MISSING status SHALL only be assigned when there is no data to evaluate for other conditions (i.e., zero valid rows); when data exists but other degrading conditions are present, the appropriate non-MISSING status SHALL be assigned.

### Requirement 8: Storage Schema

**User Story:** As a developer, I want a well-defined DuckDB schema with proper indexing, so that ingestion, auditing, and read operations are efficient and consistent.

#### Acceptance Criteria

1. WHEN the `init-db` command is executed, THE Storage SHALL create the assets, providers, ingestion_runs, raw_market_payloads, daily_ohlcv, and data_quality_reports tables in DuckDB using CREATE TABLE IF NOT EXISTS semantics, preserving any existing data.
2. THE Storage SHALL enforce a composite primary key of (symbol, trading_date, source, price_adjustment) on the daily_ohlcv table.
3. THE Storage SHALL create indexes on daily_ohlcv for (symbol, trading_date) and (quality_status).
4. THE Storage SHALL use batch inserts of up to 5000 records per transaction for writing normalized records to DuckDB.
5. IF a DuckDB write fails, THEN THE Storage SHALL abort the batch transaction and leave the previous state intact.
6. THE Storage SHALL record each ingestion run with run_id, source_name, started_at, completed_at, symbols_requested, start_date, end_date, adjusted flag, status, records_fetched, records_stored, error_message, and config_hash.
7. IF a batch insert encounters a record whose primary key already exists in daily_ohlcv, THEN THE Storage SHALL overwrite the existing record with the new data within the same transaction.

### Requirement 9: CLI Interface

**User Story:** As a user, I want a simple command-line interface to initialize the database, ingest prices, audit data quality, and compute benchmark metrics, so that I can operate the system without writing code.

#### Acceptance Criteria

1. WHEN the user runs `init-db`, THE CLI SHALL create the DuckDB database file and all required tables at the specified path, or at `data/market_data.duckdb` relative to the project root if no path is provided.
2. WHEN the user runs `ingest-prices` without specifying symbols, THE CLI SHALL default to the V1_Universe symbol set; WHEN start-date is omitted, THE CLI SHALL default to 365 calendar days before the current date; WHEN end-date is omitted, THE CLI SHALL default to the current date; WHEN provider is omitted, THE CLI SHALL use the first configured provider; WHEN adjusted is omitted, THE CLI SHALL default to split-dividend-adjusted prices.
3. WHEN the user runs `ingest-prices` with valid parameters, THE CLI SHALL fetch daily OHLCV, store raw payloads, normalize rows, and write quality reports, printing a per-symbol summary of records stored and quality status upon completion.
4. WHEN the user runs `audit-prices` with optional symbols and provider parameters, THE CLI SHALL print latest coverage, freshness, gaps, and quality status for each requested symbol, defaulting to V1_Universe when symbols are omitted.
5. WHEN the user runs `benchmark` with optional symbols, benchmark-symbol, and period parameters, THE CLI SHALL print total return, annualized return, annualized volatility, maximum drawdown, latest data date, missing-session count, benchmark excess return, and quality status, defaulting to V1_Universe for symbols, VOO for benchmark-symbol, and 1 year for period when omitted. THE CLI SHALL require all 8 metrics to be calculable and SHALL fail the command with a non-zero exit code if any metric cannot be computed.
6. IF the user provides an unrecognized command or invalid argument value, THEN THE CLI SHALL exit with a non-zero exit code and print a usage message describing valid commands and expected argument formats.
7. THE CLI SHALL NOT produce output containing BUY, SELL, HOLD, or any directive language that could be interpreted as a trade execution instruction. This prohibition is limited to explicit trade directives and does not extend to performance comparisons or risk metrics.

### Requirement 10: Read API

**User Story:** As a downstream module developer, I want a typed read API that returns time-ordered price frames with quality metadata, so that strategy and evidence modules do not query raw tables directly.

#### Acceptance Criteria

1. THE Read_API SHALL return OHLCV rows ordered by symbol ascending and trading_date ascending.
2. WHEN require_usable is set to true, THE Read_API SHALL exclude records with MISSING, CONTRADICTORY, or INSUFFICIENT_DATA quality status and SHALL include records with USABLE, PARTIAL, or STALE status. THE Read_API SHALL never return data with MISSING, CONTRADICTORY, or INSUFFICIENT_DATA status when require_usable is true, even if it means returning an empty collection.
3. IF a requested symbol has fewer rows than the caller-specified min_rows parameter for the requested date range, THEN THE Read_API SHALL raise an InsufficientDataError indicating the symbol, rows available, and rows requested.
4. THE Read_API SHALL include provenance metadata (source, retrieved_at, data_as_of, raw_payload_hash) and quality_status on each returned record to build an evidence packet without re-querying provenance tables.
5. THE Read_API SHALL support filtering by source provider and price_adjustment type.
6. IF the requested symbol, date range, and filter combination matches zero records, THEN THE Read_API SHALL return an empty collection rather than raising an error.

### Requirement 11: Benchmark Reporter

**User Story:** As a researcher, I want benchmark metrics computed from stored data with quality awareness, so that I can assess data sanity and compare assets against a broad ETF baseline.

#### Acceptance Criteria

1. THE Benchmark_Reporter SHALL compute total return, annualized return, annualized volatility, maximum drawdown, latest data date, missing-session count, benchmark excess return, and quality status using a minimum of 50 valid trading sessions for the requested symbol.
2. THE Benchmark_Reporter SHALL compare each requested symbol against the configured ETF baseline (default VOO) using only the overlapping trading sessions present in both the symbol's and the baseline's stored data.
3. IF a symbol or the baseline symbol has INSUFFICIENT_DATA, MISSING, or STALE quality status, THEN THE Benchmark_Reporter SHALL refuse to compute metrics and report the symbol name and its current quality status. THE Benchmark_Reporter SHALL also refuse computation when a symbol has fewer than 50 valid trading sessions, regardless of quality status. THE system SHALL include failsafe checks to ensure computation never proceeds with MISSING, INSUFFICIENT_DATA, or STALE status.
4. THE Benchmark_Reporter SHALL NOT use labels such as BUY, SELL, or equivalent execution language in its output.
5. THE Benchmark_Reporter SHALL map QualityStatus values to output labels as follows: USABLE to "usable", STALE to "stale", INSUFFICIENT_DATA or MISSING to "insufficient_data", and PARTIAL or CONTRADICTORY to "needs_review".
6. IF the overlapping trading sessions between the requested symbol and the baseline are fewer than 50, THEN THE Benchmark_Reporter SHALL refuse to compute benchmark excess return and report an insufficient overlap condition.

### Requirement 12: Evidence Packet Contract

**User Story:** As an AI integration developer, I want a structured evidence packet with full provenance, so that downstream AI modules cannot operate without citing auditable data sources.

#### Acceptance Criteria

1. THE Evidence_Packet SHALL include symbol, as_of date, source, data_window (start_date and end_date of the covered period), latest_price_date, price_adjustment, rows_available, missing_sessions, quality_status, confidence_cap (a decimal value between 0.0 and 1.0 inclusive), benchmark_symbol, benchmark_available, and evidence_refs.
2. EACH evidence_ref in the Evidence_Packet SHALL include table name, composite primary key of the referenced row, source, retrieved_at timestamp, and data_as_of date.
3. WHEN quality_status is STALE or INSUFFICIENT_DATA, THE Evidence_Packet SHALL set confidence_cap to no greater than 0.5.
4. THE Evidence_Packet SHALL be serializable as a Pydantic model with JSON export for consumption by any downstream AI framework.
5. THE Evidence_Packet SHALL contain at least one evidence_ref entry for each data source contributing to the packet.
6. IF required provenance fields cannot be populated for a symbol, THEN THE Evidence_Packet SHALL NOT be constructed and the system SHALL return an error indicating which provenance fields are unavailable.

### Requirement 13: Error Handling

**User Story:** As a system operator, I want predictable and safe error handling, so that failures never corrupt existing data or fabricate records.

#### Acceptance Criteria

1. IF a provider returns an HTTP 5xx response, a connection timeout after 30 seconds, or a DNS resolution failure, THEN THE CLI SHALL mark the ingestion run status as "failed" for that provider, record the error category in error_message, and SHALL NOT fabricate rows.
2. IF a provider returns insufficient history for requested indicators, THEN THE Storage SHALL store valid rows and THE Data_Quality_Auditor SHALL report INSUFFICIENT_DATA for affected downstream uses.
3. WHEN a rate limit is encountered, THE Price_Provider SHALL back off according to the provider's configured rate_limit_per_minute, retry a maximum of 3 times with a cumulative wait not exceeding 120 seconds, and record the ingestion run status as "partial" with records_fetched and records_stored reflecting only successfully completed symbols. Only rate limit encounters SHALL trigger "partial" status; other failure scenarios SHALL NOT use "partial" status. IF rate limits prevent all data from being retrieved (zero symbols successfully fetched), THEN THE CLI SHALL mark the ingestion run as "failed" instead of "partial".
4. IF a validation failure occurs, THEN THE Normalizer SHALL reject the bad row, preserve the raw payload, and include the rejected count in the quality report.
5. IF a DuckDB write failure occurs, THEN THE Storage SHALL abort the batch transaction and leave previous state intact.
6. IF all retry attempts for a rate-limited provider are exhausted, THEN THE CLI SHALL mark the ingestion run as "failed", preserve any records already stored in prior batches, and report the number of symbols not yet fetched.

### Requirement 14: Security and Privacy

**User Story:** As a security-conscious developer, I want API keys protected and raw metadata sanitized, so that secrets are never exposed in stored data or version control.

#### Acceptance Criteria

1. THE CLI SHALL load API keys exclusively from environment variables or a local `.env` file, and SHALL always verify that the `.env` file path is listed in `.gitignore` before proceeding, regardless of whether API keys are loaded from environment variables or the `.env` file.
2. THE Raw_Payload_Writer SHALL identify secret values in stored request metadata by matching field names containing "key", "token", "secret", "password", or "authorization" (case-insensitive), and SHALL replace each matched value with the literal string `[REDACTED]`.
3. WHEN making SEC EDGAR requests, THE Price_Provider SHALL include a user-agent header containing the application name and contact email, and SHALL enforce a maximum rate of 10 requests per second.
4. THE Storage SHALL NOT store account credentials, broker tokens, or real-money execution code.
5. IF the `.env` file is not listed in `.gitignore`, THEN THE CLI SHALL refuse to start and display an error message indicating the `.env` file must be excluded from version control.

### Requirement 15: Testing Without Network Access

**User Story:** As a developer, I want all tests to pass without live network access, so that CI pipelines and local development do not depend on external services.

#### Acceptance Criteria

1. THE CSV fixture provider SHALL ingest deterministic sample data covering at least 3 symbols from the V1_Universe with a minimum of 5 trading days each, including both valid records and records that trigger validation failures, without any network calls.
2. THE test suite SHALL pass with zero failures and zero skips attributed to network unavailability when run using fixture providers as the default data source. THE fixture providers SHALL successfully load data; tests SHALL NOT pass if a fixture provider fails to load any data.
3. IF any test attempts an outbound network connection during a default (non-live) test run, whether directly or through indirect dependencies, THEN THE test suite SHALL fail that test immediately rather than hanging or timing out.
4. WHERE live provider smoke tests are configured, THE test suite SHALL skip those tests without failure when the opt-in environment variable (RUN_LIVE_MARKET_DATA_TESTS=1) is not set, and SHALL execute them only when the variable is explicitly set to 1.
5. THE CSV fixture provider SHALL conform to the Price_Provider protocol and return ProviderFetchResult objects identical in structure to live providers, so that downstream normalization, validation, and quality auditing paths are exercised.

### Requirement 16: Scope Boundaries

**User Story:** As a product owner, I want explicit scope boundaries enforced, so that the system remains a research tool and never becomes a trading engine.

#### Acceptance Criteria

1. THE system SHALL NOT include any real-money trading path, broker integration, order-execution interface, or autonomous loop that initiates actions without explicit user CLI invocation.
2. THE system SHALL NOT ingest or process intraday, tick, options, futures, crypto, margin, or leverage data; only daily OHLCV equity and ETF data for symbols in the configured universe is permitted.
3. THE system SHALL NOT scrape or automate TradingView data for backend calculations.
4. THE system SHALL NOT invoke LLM calls inside the ingestion path (provider fetch, raw payload write, normalization, validation, or storage steps).
5. THE system SHALL NOT use language claiming predictive capability (e.g., "predicts", "forecasts", "guarantees returns", "will outperform") in any user-facing output, CLI help text, or documentation; permitted terms are limited to "research", "analysis", "historical", and "informational".
6. WHEN a new module or dependency is added, THE system SHALL include a CI check that verifies no broker SDK, order-routing library, or real-money execution dependency is present in the dependency manifest.
