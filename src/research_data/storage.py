"""DuckDB storage layer for the research data system.

Provides schema initialization, batch insert with upsert semantics,
ingestion run recording, raw payload writing, and metadata seeding
from configuration files.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 14.2
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from research_data.config import AppConfig
from research_data.models import OHLCVRecord, ProviderFetchResult


# ---------------------------------------------------------------------------
# SQL Schema Definitions
# ---------------------------------------------------------------------------

_CREATE_ASSETS = """\
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
"""

_CREATE_PROVIDERS = """\
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
"""

_CREATE_INGESTION_RUNS = """\
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
"""

_CREATE_RAW_MARKET_PAYLOADS = """\
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
"""

_CREATE_DAILY_OHLCV = """\
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
"""

_CREATE_INDEX_SYMBOL_DATE = """\
CREATE INDEX IF NOT EXISTS idx_daily_ohlcv_symbol_date
    ON daily_ohlcv (symbol, trading_date);
"""

_CREATE_INDEX_QUALITY = """\
CREATE INDEX IF NOT EXISTS idx_daily_ohlcv_quality
    ON daily_ohlcv (quality_status);
"""

_CREATE_DATA_QUALITY_REPORTS = """\
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
"""


# ---------------------------------------------------------------------------
# Schema Initialization
# ---------------------------------------------------------------------------


def init_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all required tables and indexes using CREATE TABLE IF NOT EXISTS.

    Preserves any existing data. Creates indexes on daily_ohlcv for
    (symbol, trading_date) and (quality_status).

    Requirements: 8.1, 8.2, 8.3
    """
    conn.execute(_CREATE_ASSETS)
    conn.execute(_CREATE_PROVIDERS)
    conn.execute(_CREATE_INGESTION_RUNS)
    conn.execute(_CREATE_RAW_MARKET_PAYLOADS)
    conn.execute(_CREATE_DAILY_OHLCV)
    conn.execute(_CREATE_INDEX_SYMBOL_DATE)
    conn.execute(_CREATE_INDEX_QUALITY)
    conn.execute(_CREATE_DATA_QUALITY_REPORTS)


# ---------------------------------------------------------------------------
# Batch Insert with Upsert
# ---------------------------------------------------------------------------


def batch_insert_ohlcv(
    conn: duckdb.DuckDBPyConnection,
    records: list[OHLCVRecord],
    batch_size: int = 5000,
) -> int:
    """Insert OHLCV records in batches with upsert semantics.

    Inserts up to batch_size records per transaction. If a record's primary key
    (symbol, trading_date, source, price_adjustment) already exists, the existing
    record is overwritten with the new data (INSERT OR REPLACE).

    If a write fails, the batch transaction is aborted and previous state is
    left intact.

    Args:
        conn: DuckDB connection.
        records: List of validated OHLCVRecord instances.
        batch_size: Maximum records per transaction (default 5000).

    Returns:
        Total number of records successfully inserted/upserted.

    Raises:
        Exception: Re-raises any DuckDB write error after aborting the
                   transaction for the failed batch.

    Requirements: 8.4, 8.5, 8.7
    """
    if not records:
        return 0

    total_inserted = 0

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        try:
            conn.execute("BEGIN TRANSACTION")
            for record in batch:
                _upsert_single_record(conn, record)
            conn.execute("COMMIT")
            total_inserted += len(batch)
        except Exception:
            conn.execute("ROLLBACK")
            raise

    return total_inserted


def _upsert_single_record(
    conn: duckdb.DuckDBPyConnection, record: OHLCVRecord
) -> None:
    """Insert or replace a single OHLCV record.

    Uses INSERT OR REPLACE to handle duplicate primary keys by overwriting
    the existing record.

    Requirement: 8.7
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_ohlcv (
            symbol, asset_type, exchange, trading_date,
            open, high, low, close, adjusted_close, volume,
            split_factor, dividend_cash, price_adjustment, currency,
            source, source_record_id, retrieved_at, data_as_of,
            raw_payload_hash, quality_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            record.symbol,
            record.asset_type,
            record.exchange,
            record.trading_date,
            record.open,
            record.high,
            record.low,
            record.close,
            record.adjusted_close,
            record.volume,
            record.split_factor,
            record.dividend_cash,
            record.price_adjustment.value,
            record.currency,
            record.source,
            record.source_record_id,
            record.retrieved_at,
            record.data_as_of,
            record.raw_payload_hash,
            record.quality_status.value,
        ],
    )


# ---------------------------------------------------------------------------
# Ingestion Run Recording
# ---------------------------------------------------------------------------


def record_ingestion_run(
    conn: duckdb.DuckDBPyConnection, run_data: dict[str, Any]
) -> str:
    """Record an ingestion run with all metadata.

    Args:
        conn: DuckDB connection.
        run_data: Dictionary containing run metadata. Expected keys:
            - source_name (str): Provider name
            - started_at (datetime): Run start time
            - completed_at (datetime | None): Run completion time
            - symbols_requested (list[str]): Symbols requested
            - start_date (date): Requested start date
            - end_date (date): Requested end date
            - adjusted (bool): Whether adjusted prices were requested
            - status (str): Run status (e.g., "completed", "failed", "partial")
            - records_fetched (int): Number of records fetched
            - records_stored (int): Number of records stored
            - error_message (str | None): Error message if failed
            - config_hash (str): Hash of the configuration used

    Returns:
        The generated run_id as a string.

    Requirement: 8.6
    """
    run_id = run_data.get("run_id", str(uuid.uuid4()))

    conn.execute(
        """
        INSERT INTO ingestion_runs (
            run_id, source_name, started_at, completed_at,
            symbols_requested, start_date, end_date, adjusted,
            status, records_fetched, records_stored, error_message,
            config_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run_id,
            run_data["source_name"],
            run_data["started_at"],
            run_data.get("completed_at"),
            run_data["symbols_requested"],
            run_data["start_date"],
            run_data["end_date"],
            run_data["adjusted"],
            run_data["status"],
            run_data.get("records_fetched", 0),
            run_data.get("records_stored", 0),
            run_data.get("error_message"),
            run_data["config_hash"],
        ],
    )

    return run_id


# ---------------------------------------------------------------------------
# Metadata Seeding
# ---------------------------------------------------------------------------


def seed_metadata(conn: duckdb.DuckDBPyConnection, config: AppConfig) -> None:
    """Seed providers and assets tables from application configuration.

    Uses INSERT OR REPLACE to update existing entries without failing on
    duplicate primary keys.

    Args:
        conn: DuckDB connection.
        config: Loaded and validated AppConfig instance.
    """
    now = datetime.now(timezone.utc)

    # Seed providers
    for provider in config.providers.values():
        conn.execute(
            """
            INSERT OR REPLACE INTO providers (
                source_name, source_url, requires_api_key,
                supports_adjusted_prices, supports_corporate_actions,
                rate_limit_per_minute, license_note, experimental,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                provider.source_name,
                provider.source_url,
                provider.requires_api_key,
                provider.supports_adjusted_prices,
                provider.supports_corporate_actions,
                provider.rate_limit_per_minute,
                provider.license_note,
                provider.experimental,
                now,
            ],
        )

    # Seed assets
    for asset in config.universe.assets.values():
        conn.execute(
            """
            INSERT OR REPLACE INTO assets (
                symbol, asset_type, name, exchange, currency,
                benchmark_symbol, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                asset.symbol,
                asset.asset_type,
                asset.name,
                asset.exchange,
                asset.currency,
                asset.benchmark_symbol,
                True,
                now,
            ],
        )


# ---------------------------------------------------------------------------
# Secret Redaction
# ---------------------------------------------------------------------------

# Pattern matches field names containing key, token, secret, password, or
# authorization (case-insensitive).
_SECRET_FIELD_PATTERN = re.compile(
    r"(key|token|secret|password|authorization)", re.IGNORECASE
)


def redact_secrets(params: dict[str, Any]) -> dict[str, Any]:
    """Redact secret values from request metadata.

    Matches field names containing "key", "token", "secret", "password", or
    "authorization" (case-insensitive) and replaces their values with
    "[REDACTED]".

    Args:
        params: Dictionary of request parameters that may contain secrets.

    Returns:
        A new dictionary with secret values replaced by "[REDACTED]".

    Requirements: 3.5, 14.2
    """
    redacted: dict[str, Any] = {}
    for field_name, value in params.items():
        if _SECRET_FIELD_PATTERN.search(field_name):
            redacted[field_name] = "[REDACTED]"
        else:
            redacted[field_name] = value
    return redacted


# ---------------------------------------------------------------------------
# Raw Payload Writer
# ---------------------------------------------------------------------------


def write_raw_payload(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    fetch_result: ProviderFetchResult,
    data_dir: str | Path,
) -> str:
    """Write a raw provider payload to disk and record it in the database.

    Persists the raw JSON or CSV response to:
        data/raw/provider=<provider>/date=<YYYY-MM-DD>/<symbol>_<hash_prefix_8chars>.<format>

    Computes a SHA-256 content hash and stores metadata in the
    raw_market_payloads table. Never overwrites existing files. If a payload
    with an identical hash already exists for the same symbol and source,
    skips the insert and returns the existing hash.

    Args:
        conn: DuckDB connection.
        run_id: UUID string identifying the current ingestion run.
        fetch_result: The ProviderFetchResult from a provider fetch.
        data_dir: Base data directory (e.g., "data" or Path("data")).

    Returns:
        The SHA-256 content hash of the raw payload.

    Raises:
        IOError: If the file write fails (caller should abort normalization).
        Exception: If the database insert fails.

    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 14.2
    """
    data_dir = Path(data_dir)

    # Compute SHA-256 content hash of the raw payload
    payload_bytes = fetch_result.raw_payload.encode("utf-8")
    content_hash = hashlib.sha256(payload_bytes).hexdigest()

    # Check if this hash already exists for the same symbol and source
    existing = conn.execute(
        """
        SELECT raw_payload_hash FROM raw_market_payloads
        WHERE raw_payload_hash = ?
          AND symbol = ?
          AND source_name = ?
        """,
        [content_hash, fetch_result.symbol, fetch_result.provider],
    ).fetchone()

    if existing is not None:
        # Duplicate hash for same symbol/source — skip insert, return existing
        return content_hash

    # Determine payload format from content
    payload_format = _detect_payload_format(fetch_result.raw_payload)

    # Build the file path
    retrieved_date = fetch_result.retrieved_at.strftime("%Y-%m-%d")
    hash_prefix = content_hash[:8]
    filename = f"{fetch_result.symbol}_{hash_prefix}.{payload_format}"
    relative_dir = Path("raw") / f"provider={fetch_result.provider}" / f"date={retrieved_date}"
    full_dir = data_dir / relative_dir
    full_path = full_dir / filename

    # Never overwrite existing files
    if full_path.exists():
        # File already exists — this is a separate fetch with same content
        # Still record in DB if hash wasn't already there (handled above)
        pass
    else:
        # Create directory structure and write file
        try:
            full_dir.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(payload_bytes)
        except OSError as e:
            raise IOError(
                f"Failed to write raw payload to {full_path}: {e}"
            ) from e

    # Redact secrets from request params before storing
    redacted_params = redact_secrets(fetch_result.request_params)

    # Store the relative path for portability
    payload_path = str(relative_dir / filename)

    # Insert into raw_market_payloads table
    conn.execute(
        """
        INSERT INTO raw_market_payloads (
            raw_payload_hash, run_id, source_name, symbol,
            retrieved_at, request_endpoint, request_params_json,
            payload_path, payload_format, payload_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            content_hash,
            run_id,
            fetch_result.provider,
            fetch_result.symbol,
            fetch_result.retrieved_at,
            fetch_result.request_url,
            json.dumps(redacted_params),
            payload_path,
            payload_format,
            len(payload_bytes),
        ],
    )

    return content_hash


def _detect_payload_format(payload: str) -> str:
    """Detect whether a raw payload is JSON or CSV.

    Uses a simple heuristic: if the content starts with '{' or '[' after
    stripping whitespace, it's JSON. Otherwise, it's CSV.

    Args:
        payload: The raw payload string.

    Returns:
        "json" or "csv".
    """
    stripped = payload.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    return "csv"
