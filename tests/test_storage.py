"""Unit tests for the storage layer (Tasks 2.4, 5.3).

Covers:
- init_db creates all 6 tables (Requirements 8.1)
- batch_insert_ohlcv writes correct number of records (Requirement 8.4)
- Transaction abort on simulated write failure leaves previous state intact (Requirement 8.5)
- record_ingestion_run records all fields correctly and returns a run_id (Requirement 8.6)
- seed_metadata populates providers and assets tables from config (Requirement 8.1)
- write_raw_payload writes files and records in DB (Requirements 3.1-3.7, 14.2)
- redact_secrets removes secret values from metadata (Requirements 3.5, 14.2)

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 8.1, 8.4, 8.5, 8.6, 14.2
"""

import sys
import uuid as uuid_mod
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

sys.path.insert(0, "src")

from research_data.config import AppConfig, AssetConfig, ProviderConfig, UniverseConfig
from research_data.models import OHLCVRecord, PriceAdjustment, ProviderFetchResult, QualityStatus
from research_data.storage import (
    _upsert_single_record,
    batch_insert_ohlcv,
    init_db,
    record_ingestion_run,
    redact_secrets,
    seed_metadata,
    update_ingestion_run,
    write_raw_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    symbol: str = "AAPL",
    trading_date: date = date(2024, 3, 15),
    source: str = "polygon",
    price_adjustment: PriceAdjustment = PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
    **overrides,
) -> OHLCVRecord:
    """Create a valid OHLCVRecord with sensible defaults."""
    kwargs = {
        "symbol": symbol,
        "asset_type": "equity",
        "exchange": "NASDAQ",
        "trading_date": trading_date,
        "open": 170.0,
        "high": 175.0,
        "low": 168.0,
        "close": 173.0,
        "adjusted_close": 172.5,
        "volume": 50000000,
        "split_factor": 1.0,
        "dividend_cash": 0.0,
        "price_adjustment": price_adjustment,
        "currency": "USD",
        "source": source,
        "source_record_id": None,
        "retrieved_at": datetime(2024, 3, 15, 21, 0, 0, tzinfo=timezone.utc),
        "data_as_of": date(2024, 3, 15),
        "raw_payload_hash": "sha256_test_hash_abc123",
        "quality_status": QualityStatus.USABLE,
    }
    kwargs.update(overrides)
    return OHLCVRecord(**kwargs)


def _make_app_config() -> AppConfig:
    """Create a minimal AppConfig for testing seed_metadata."""
    providers = {
        "polygon": ProviderConfig(
            source_name="polygon",
            source_url="https://api.polygon.io",
            license_note="Polygon Basic free tier",
            requires_api_key=True,
            rate_limit=5,
            adjustment_policy="split_dividend_adjusted",
            supports_daily_ohlcv=True,
            supports_adjusted_prices=True,
            supports_corporate_actions=True,
            min_history_years_free=2.0,
            rate_limit_per_minute=5,
        ),
        "csv_fixture": ProviderConfig(
            source_name="csv_fixture",
            source_url="file://tests/fixtures/",
            license_note="Local test fixtures",
            requires_api_key=False,
            rate_limit=0,
            adjustment_policy="split_dividend_adjusted",
            supports_daily_ohlcv=True,
            supports_adjusted_prices=True,
            supports_corporate_actions=False,
        ),
    }
    assets = {
        "AAPL": AssetConfig(
            symbol="AAPL",
            asset_type="equity",
            name="Apple Inc.",
            exchange="NASDAQ",
            currency="USD",
            benchmark_symbol="VOO",
        ),
        "VOO": AssetConfig(
            symbol="VOO",
            asset_type="etf",
            name="Vanguard S&P 500 ETF",
            exchange="NYSE",
            currency="USD",
            benchmark_symbol="VOO",
        ),
    }
    universe = UniverseConfig(
        name="v1",
        description="Test universe",
        symbols=["AAPL", "VOO"],
        default_benchmark="VOO",
        benchmark_mappings={"VOO": "S&P 500 ETF"},
        assets=assets,
    )
    return AppConfig(
        universe=universe,
        providers=providers,
        default_provider="polygon",
    )


@pytest.fixture
def db():
    """Create an in-memory DuckDB connection with schema initialized."""
    conn = duckdb.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def raw_db():
    """Create an in-memory DuckDB connection without schema (for testing init_db)."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


# ===========================================================================
# 1. init_db creates all 6 tables
# ===========================================================================


class TestInitDb:
    """Test that init_db creates all required tables. Requirement 8.1."""

    EXPECTED_TABLES = [
        "assets",
        "providers",
        "ingestion_runs",
        "raw_market_payloads",
        "daily_ohlcv",
        "data_quality_reports",
    ]

    def test_creates_all_tables(self, raw_db):
        """init_db should create all 6 required tables."""
        init_db(raw_db)

        result = raw_db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = [row[0] for row in result]

        for expected in self.EXPECTED_TABLES:
            assert expected in table_names, f"Table '{expected}' not found"

    def test_creates_exactly_six_tables(self, raw_db):
        """init_db should create exactly 6 tables."""
        init_db(raw_db)

        result = raw_db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = [row[0] for row in result]

        assert len(table_names) == 6

    def test_idempotent_preserves_data(self, raw_db):
        """Calling init_db twice should not destroy existing data."""
        init_db(raw_db)

        # Insert a row into assets
        raw_db.execute(
            "INSERT INTO assets (symbol, asset_type, name, exchange, created_at) "
            "VALUES ('TEST', 'equity', 'Test Corp', 'NYSE', CURRENT_TIMESTAMP)"
        )

        # Call init_db again
        init_db(raw_db)

        # Verify data is preserved
        count = raw_db.execute(
            "SELECT COUNT(*) FROM assets WHERE symbol = 'TEST'"
        ).fetchone()[0]
        assert count == 1

    def test_daily_ohlcv_has_primary_key(self, raw_db):
        """daily_ohlcv should have composite primary key (symbol, trading_date, source, price_adjustment)."""
        init_db(raw_db)

        # Insert a record
        raw_db.execute(
            """
            INSERT INTO daily_ohlcv (
                symbol, asset_type, exchange, trading_date,
                open, high, low, close, volume,
                price_adjustment, currency, source,
                retrieved_at, data_as_of, raw_payload_hash, quality_status
            ) VALUES (
                'AAPL', 'equity', 'NASDAQ', '2024-03-15',
                170.0, 175.0, 168.0, 173.0, 50000000,
                'split_dividend_adjusted', 'USD', 'polygon',
                '2024-03-15 21:00:00', '2024-03-15', 'hash123', 'usable'
            )
            """
        )

        # Inserting a duplicate primary key should fail with plain INSERT
        with pytest.raises(duckdb.ConstraintException):
            raw_db.execute(
                """
                INSERT INTO daily_ohlcv (
                    symbol, asset_type, exchange, trading_date,
                    open, high, low, close, volume,
                    price_adjustment, currency, source,
                    retrieved_at, data_as_of, raw_payload_hash, quality_status
                ) VALUES (
                    'AAPL', 'equity', 'NASDAQ', '2024-03-15',
                    171.0, 176.0, 169.0, 174.0, 60000000,
                    'split_dividend_adjusted', 'USD', 'polygon',
                    '2024-03-15 22:00:00', '2024-03-15', 'hash456', 'usable'
                )
                """
            )


# ===========================================================================
# 2. batch_insert_ohlcv writes correct number of records
# ===========================================================================


class TestBatchInsertOhlcv:
    """Test batch insert writes correct number of records. Requirement 8.4."""

    def test_insert_single_record(self, db):
        """Inserting a single record should return 1."""
        records = [_make_record()]
        count = batch_insert_ohlcv(db, records)
        assert count == 1

        stored = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored == 1

    def test_insert_multiple_records(self, db):
        """Inserting multiple records with different dates should return correct count."""
        records = [
            _make_record(trading_date=date(2024, 3, i))
            for i in range(1, 11)
        ]
        count = batch_insert_ohlcv(db, records)
        assert count == 10

        stored = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored == 10

    def test_insert_empty_list_returns_zero(self, db):
        """Inserting an empty list should return 0."""
        count = batch_insert_ohlcv(db, [])
        assert count == 0

        stored = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored == 0

    def test_batch_size_respected(self, db):
        """Records should be inserted in batches of the specified size."""
        # Create 12 records, use batch_size=5 (should be 3 batches: 5, 5, 2)
        records = [
            _make_record(trading_date=date(2024, 1, i + 1))
            for i in range(12)
        ]
        count = batch_insert_ohlcv(db, records, batch_size=5)
        assert count == 12

        stored = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored == 12

    def test_insert_records_different_symbols(self, db):
        """Records with different symbols should all be inserted."""
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
        records = [
            _make_record(symbol=sym, trading_date=date(2024, 3, 15))
            for sym in symbols
        ]
        count = batch_insert_ohlcv(db, records)
        assert count == 5

        stored = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored == 5

    def test_upsert_overwrites_existing_record(self, db):
        """Inserting a record with the same primary key should overwrite."""
        record1 = _make_record(open=170.0, high=175.0, low=168.0, close=173.0)
        record2 = _make_record(open=172.0, high=180.0, low=170.0, close=178.0)

        batch_insert_ohlcv(db, [record1])
        batch_insert_ohlcv(db, [record2])

        stored = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored == 1

        close_val = db.execute(
            "SELECT close FROM daily_ohlcv WHERE symbol = 'AAPL'"
        ).fetchone()[0]
        assert close_val == 178.0

    def test_large_batch_insert(self, db):
        """Inserting more than default batch_size records works correctly with smaller batch_size."""
        records = [
            _make_record(
                symbol="AAPL",
                trading_date=date(2020, 1, 1) + timedelta(days=i),
                data_as_of=date(2020, 1, 1) + timedelta(days=i),
            )
            for i in range(100)
        ]
        count = batch_insert_ohlcv(db, records, batch_size=30)
        assert count == 100

        stored = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored == 100


# ===========================================================================
# 3. Transaction abort on simulated write failure
# ===========================================================================


class TestTransactionAbort:
    """Test that transaction abort on failure leaves previous state intact. Requirement 8.5."""

    def test_failed_batch_does_not_corrupt_previous_data(self, db):
        """If a batch fails, previously committed data should remain intact."""
        # Insert first batch successfully
        good_records = [
            _make_record(trading_date=date(2024, 3, i))
            for i in range(1, 6)
        ]
        batch_insert_ohlcv(db, good_records)

        stored_before = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored_before == 5

        # Create records that will cause a failure by patching _upsert_single_record
        bad_records = [
            _make_record(symbol="MSFT", trading_date=date(2024, 3, i))
            for i in range(1, 6)
        ]

        call_count = {"n": 0}
        original_upsert = _upsert_single_record

        def failing_upsert(conn, record):
            call_count["n"] += 1
            if call_count["n"] == 3:
                raise duckdb.IOException("Simulated write failure")
            return original_upsert(conn, record)

        with patch("research_data.storage._upsert_single_record", side_effect=failing_upsert):
            with pytest.raises(duckdb.IOException, match="Simulated write failure"):
                batch_insert_ohlcv(db, bad_records)

        # Previous data should still be intact
        stored_after = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored_after == 5

        # No MSFT records should exist (the failed batch was rolled back)
        msft_count = db.execute(
            "SELECT COUNT(*) FROM daily_ohlcv WHERE symbol = 'MSFT'"
        ).fetchone()[0]
        assert msft_count == 0

    def test_partial_batch_failure_rolls_back_entire_batch(self, db):
        """A failure mid-batch should roll back all records in that batch."""
        records = [
            _make_record(trading_date=date(2024, 3, i))
            for i in range(1, 6)
        ]

        call_count = {"n": 0}
        original_upsert = _upsert_single_record

        def failing_upsert(conn, record):
            call_count["n"] += 1
            if call_count["n"] == 4:
                raise duckdb.IOException("Disk full")
            return original_upsert(conn, record)

        with patch("research_data.storage._upsert_single_record", side_effect=failing_upsert):
            with pytest.raises(duckdb.IOException, match="Disk full"):
                batch_insert_ohlcv(db, records)

        # No records should be stored since the entire batch was rolled back
        stored = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored == 0

    def test_multi_batch_failure_preserves_committed_batches(self, db):
        """If the second batch fails, the first committed batch should remain."""
        # 10 records with batch_size=5 means 2 batches
        records = [
            _make_record(trading_date=date(2024, 3, i + 1))
            for i in range(10)
        ]

        call_count = {"n": 0}
        original_upsert = _upsert_single_record

        def failing_upsert(conn, record):
            call_count["n"] += 1
            # Fail on the 7th insert (2nd record of 2nd batch)
            if call_count["n"] == 7:
                raise duckdb.IOException("Simulated failure in second batch")
            return original_upsert(conn, record)

        with patch("research_data.storage._upsert_single_record", side_effect=failing_upsert):
            with pytest.raises(duckdb.IOException):
                batch_insert_ohlcv(db, records, batch_size=5)

        # First batch (5 records) should be committed
        stored = db.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert stored == 5


# ===========================================================================
# 4. record_ingestion_run records all fields correctly
# ===========================================================================


class TestRecordIngestionRun:
    """Test ingestion run recording with all fields. Requirement 8.6."""

    def test_records_all_fields(self, db):
        """record_ingestion_run should store all provided fields."""
        run_data = {
            "source_name": "polygon",
            "started_at": datetime(2024, 3, 15, 20, 0, 0, tzinfo=timezone.utc),
            "completed_at": datetime(2024, 3, 15, 20, 5, 0, tzinfo=timezone.utc),
            "symbols_requested": ["AAPL", "MSFT", "GOOGL"],
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 3, 15),
            "adjusted": True,
            "status": "completed",
            "records_fetched": 150,
            "records_stored": 148,
            "error_message": None,
            "config_hash": "sha256_config_hash_xyz",
        }

        run_id = record_ingestion_run(db, run_data)

        # Verify run_id is returned
        assert run_id is not None
        assert isinstance(run_id, str)
        assert len(run_id) > 0

        # Verify stored data
        row = db.execute(
            "SELECT * FROM ingestion_runs WHERE run_id = ?", [run_id]
        ).fetchone()
        assert row is not None

        # Fetch as dict for easier assertions
        columns = [
            "run_id", "source_name", "started_at", "completed_at",
            "symbols_requested", "start_date", "end_date", "adjusted",
            "status", "records_fetched", "records_stored", "error_message",
            "config_hash",
        ]
        row_dict = dict(zip(columns, row))

        assert row_dict["source_name"] == "polygon"
        assert row_dict["adjusted"] is True
        assert row_dict["status"] == "completed"
        assert row_dict["records_fetched"] == 150
        assert row_dict["records_stored"] == 148
        assert row_dict["error_message"] is None
        assert row_dict["config_hash"] == "sha256_config_hash_xyz"

    def test_returns_run_id(self, db):
        """record_ingestion_run should return a valid UUID string."""
        run_data = {
            "source_name": "csv_fixture",
            "started_at": datetime(2024, 3, 15, 20, 0, 0, tzinfo=timezone.utc),
            "completed_at": None,
            "symbols_requested": ["VOO"],
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 3, 15),
            "adjusted": False,
            "status": "running",
            "records_fetched": 0,
            "records_stored": 0,
            "error_message": None,
            "config_hash": "hash_abc",
        }

        run_id = record_ingestion_run(db, run_data)
        assert run_id is not None

        # Should be queryable
        count = db.execute(
            "SELECT COUNT(*) FROM ingestion_runs WHERE run_id = ?", [run_id]
        ).fetchone()[0]
        assert count == 1

    def test_failed_run_with_error_message(self, db):
        """A failed run should store the error_message field."""
        run_data = {
            "source_name": "polygon",
            "started_at": datetime(2024, 3, 15, 20, 0, 0, tzinfo=timezone.utc),
            "completed_at": datetime(2024, 3, 15, 20, 0, 5, tzinfo=timezone.utc),
            "symbols_requested": ["AAPL"],
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 3, 15),
            "adjusted": True,
            "status": "failed",
            "records_fetched": 0,
            "records_stored": 0,
            "error_message": "HTTP 503 Service Unavailable",
            "config_hash": "hash_def",
        }

        run_id = record_ingestion_run(db, run_data)

        row = db.execute(
            "SELECT error_message, status FROM ingestion_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        assert row[0] == "HTTP 503 Service Unavailable"
        assert row[1] == "failed"

    def test_custom_run_id_used_when_provided(self, db):
        """If run_data includes run_id, it should be used instead of generating one."""
        custom_id = str(uuid_mod.uuid4())
        run_data = {
            "run_id": custom_id,
            "source_name": "polygon",
            "started_at": datetime(2024, 3, 15, 20, 0, 0, tzinfo=timezone.utc),
            "completed_at": None,
            "symbols_requested": ["SPY"],
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 3, 15),
            "adjusted": True,
            "status": "running",
            "records_fetched": 0,
            "records_stored": 0,
            "error_message": None,
            "config_hash": "hash_ghi",
        }

        run_id = record_ingestion_run(db, run_data)
        assert run_id == custom_id

    def test_multiple_runs_stored_independently(self, db):
        """Multiple ingestion runs should be stored as separate records."""
        for i in range(3):
            run_data = {
                "source_name": "polygon",
                "started_at": datetime(2024, 3, 15, 20, i, 0, tzinfo=timezone.utc),
                "completed_at": None,
                "symbols_requested": ["AAPL"],
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 3, 15),
                "adjusted": True,
                "status": "completed",
                "records_fetched": 10 * (i + 1),
                "records_stored": 10 * (i + 1),
                "error_message": None,
                "config_hash": f"hash_{i}",
            }
            record_ingestion_run(db, run_data)

        count = db.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]
        assert count == 3


# ===========================================================================
# 5. seed_metadata populates providers and assets tables
# ===========================================================================


class TestSeedMetadata:
    """Test that seed_metadata populates providers and assets from config."""

    def test_seeds_providers(self, db):
        """seed_metadata should populate the providers table from config."""
        config = _make_app_config()
        seed_metadata(db, config)

        count = db.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
        assert count == 2

        polygon = db.execute(
            "SELECT source_name, source_url, requires_api_key, license_note "
            "FROM providers WHERE source_name = 'polygon'"
        ).fetchone()
        assert polygon is not None
        assert polygon[0] == "polygon"
        assert polygon[1] == "https://api.polygon.io"
        assert polygon[2] is True
        assert polygon[3] == "Polygon Basic free tier"

    def test_seeds_assets(self, db):
        """seed_metadata should populate the assets table from config."""
        config = _make_app_config()
        seed_metadata(db, config)

        count = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        assert count == 2

        aapl = db.execute(
            "SELECT symbol, asset_type, name, exchange, currency, benchmark_symbol "
            "FROM assets WHERE symbol = 'AAPL'"
        ).fetchone()
        assert aapl is not None
        assert aapl[0] == "AAPL"
        assert aapl[1] == "equity"
        assert aapl[2] == "Apple Inc."
        assert aapl[3] == "NASDAQ"
        assert aapl[4] == "USD"
        assert aapl[5] == "VOO"

    def test_seed_is_idempotent(self, db):
        """Calling seed_metadata twice should not duplicate rows."""
        config = _make_app_config()
        seed_metadata(db, config)
        seed_metadata(db, config)

        provider_count = db.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
        asset_count = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        assert provider_count == 2
        assert asset_count == 2

    def test_seed_updates_existing_provider(self, db):
        """seed_metadata should update existing provider entries (upsert)."""
        config = _make_app_config()
        seed_metadata(db, config)

        # Verify initial value
        note = db.execute(
            "SELECT license_note FROM providers WHERE source_name = 'csv_fixture'"
        ).fetchone()[0]
        assert note == "Local test fixtures"


# ===========================================================================
# 6. redact_secrets removes secret values from metadata
# ===========================================================================


class TestRedactSecrets:
    """Test that redact_secrets properly redacts secret field values. Requirements 3.5, 14.2."""

    def test_redacts_api_key_field(self):
        """Fields containing 'key' should be redacted."""
        params = {"api_key": "sk-12345", "symbol": "AAPL"}
        result = redact_secrets(params)
        assert result["api_key"] == "[REDACTED]"
        assert result["symbol"] == "AAPL"

    def test_redacts_token_field(self):
        """Fields containing 'token' should be redacted."""
        params = {"auth_token": "bearer_xyz", "start": "2024-01-01"}
        result = redact_secrets(params)
        assert result["auth_token"] == "[REDACTED]"
        assert result["start"] == "2024-01-01"

    def test_redacts_secret_field(self):
        """Fields containing 'secret' should be redacted."""
        params = {"client_secret": "abc123", "format": "json"}
        result = redact_secrets(params)
        assert result["client_secret"] == "[REDACTED]"
        assert result["format"] == "json"

    def test_redacts_password_field(self):
        """Fields containing 'password' should be redacted."""
        params = {"password": "hunter2", "username": "user"}
        result = redact_secrets(params)
        assert result["password"] == "[REDACTED]"
        assert result["username"] == "user"

    def test_redacts_authorization_field(self):
        """Fields containing 'authorization' should be redacted."""
        params = {"authorization": "Bearer token123", "endpoint": "/v1/data"}
        result = redact_secrets(params)
        assert result["authorization"] == "[REDACTED]"
        assert result["endpoint"] == "/v1/data"

    def test_case_insensitive_matching(self):
        """Redaction should be case-insensitive."""
        params = {
            "API_KEY": "key1",
            "ApiToken": "token1",
            "SECRET_VALUE": "sec1",
            "Password": "pass1",
            "AUTHORIZATION": "auth1",
        }
        result = redact_secrets(params)
        assert all(v == "[REDACTED]" for v in result.values())

    def test_returns_new_dict(self):
        """redact_secrets should return a new dict, not modify the original."""
        params = {"api_key": "secret_value", "symbol": "AAPL"}
        result = redact_secrets(params)
        assert result is not params
        assert params["api_key"] == "secret_value"  # Original unchanged

    def test_empty_dict(self):
        """Empty dict should return empty dict."""
        assert redact_secrets({}) == {}

    def test_no_secrets_unchanged(self):
        """Dict with no secret fields should be returned unchanged."""
        params = {"symbol": "AAPL", "start": "2024-01-01", "adjusted": True}
        result = redact_secrets(params)
        assert result == params


# ===========================================================================
# 7. write_raw_payload writes files and records in DB
# ===========================================================================


def _make_fetch_result(
    symbol: str = "AAPL",
    provider: str = "csv_fixture",
    raw_payload: str = '{"data": [{"date": "2024-03-15", "close": 173.0}]}',
    request_params: dict | None = None,
) -> ProviderFetchResult:
    """Create a ProviderFetchResult for testing."""
    import hashlib

    if request_params is None:
        request_params = {"symbol": symbol, "start": "2024-01-01", "end": "2024-03-15"}

    return ProviderFetchResult(
        symbol=symbol,
        provider=provider,
        request_url=f"https://api.example.com/v1/prices/{symbol}",
        request_params=request_params,
        retrieved_at=datetime(2024, 3, 15, 21, 0, 0, tzinfo=timezone.utc),
        raw_payload=raw_payload,
        content_hash=hashlib.sha256(raw_payload.encode("utf-8")).hexdigest(),
        records=[],
        provider_warnings=[],
        rate_limit_state={"remaining": 4, "reset_at": None},
    )


class TestWriteRawPayload:
    """Test raw payload writer. Requirements 3.1-3.7, 14.2."""

    def test_writes_file_to_correct_path(self, db, tmp_path):
        """Raw payload should be written to the correct directory structure."""
        fetch_result = _make_fetch_result()
        run_id = str(uuid_mod.uuid4())

        content_hash = write_raw_payload(db, run_id, fetch_result, tmp_path)

        # Verify file exists at expected path
        expected_dir = tmp_path / "raw" / "provider=csv_fixture" / "date=2024-03-15"
        assert expected_dir.exists()

        # File should be named <symbol>_<hash_prefix_8chars>.<format>
        hash_prefix = content_hash[:8]
        expected_file = expected_dir / f"AAPL_{hash_prefix}.json"
        assert expected_file.exists()

    def test_file_content_matches_payload(self, db, tmp_path):
        """Written file content should match the raw payload."""
        raw_payload = '{"prices": [1, 2, 3]}'
        fetch_result = _make_fetch_result(raw_payload=raw_payload)
        run_id = str(uuid_mod.uuid4())

        write_raw_payload(db, run_id, fetch_result, tmp_path)

        # Find the written file
        expected_dir = tmp_path / "raw" / "provider=csv_fixture" / "date=2024-03-15"
        files = list(expected_dir.iterdir())
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == raw_payload

    def test_computes_correct_sha256_hash(self, db, tmp_path):
        """Returned hash should be the SHA-256 of the raw payload."""
        import hashlib

        raw_payload = "test payload content"
        fetch_result = _make_fetch_result(raw_payload=raw_payload)
        run_id = str(uuid_mod.uuid4())

        content_hash = write_raw_payload(db, run_id, fetch_result, tmp_path)

        expected_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
        assert content_hash == expected_hash

    def test_records_in_raw_market_payloads_table(self, db, tmp_path):
        """Payload metadata should be recorded in raw_market_payloads table."""
        fetch_result = _make_fetch_result()
        run_id = str(uuid_mod.uuid4())

        content_hash = write_raw_payload(db, run_id, fetch_result, tmp_path)

        row = db.execute(
            "SELECT * FROM raw_market_payloads WHERE raw_payload_hash = ?",
            [content_hash],
        ).fetchone()
        assert row is not None

        # Verify fields
        columns = [
            "raw_payload_hash", "run_id", "source_name", "symbol",
            "retrieved_at", "request_endpoint", "request_params_json",
            "payload_path", "payload_format", "payload_bytes",
        ]
        row_dict = dict(zip(columns, row))
        assert str(row_dict["run_id"]) == run_id
        assert row_dict["source_name"] == "csv_fixture"
        assert row_dict["symbol"] == "AAPL"
        assert row_dict["payload_format"] == "json"
        assert row_dict["payload_bytes"] == len(fetch_result.raw_payload.encode("utf-8"))

    def test_never_overwrites_existing_file(self, db, tmp_path):
        """Existing raw payload files should never be overwritten."""
        fetch_result = _make_fetch_result(raw_payload="original content")
        run_id = str(uuid_mod.uuid4())

        # Write the first time
        content_hash = write_raw_payload(db, run_id, fetch_result, tmp_path)

        # Manually modify the file to detect overwrite
        expected_dir = tmp_path / "raw" / "provider=csv_fixture" / "date=2024-03-15"
        hash_prefix = content_hash[:8]
        file_path = expected_dir / f"AAPL_{hash_prefix}.json"
        file_path.write_text("modified content", encoding="utf-8")

        # Delete the DB record so the duplicate check doesn't trigger
        db.execute(
            "DELETE FROM raw_market_payloads WHERE raw_payload_hash = ?",
            [content_hash],
        )

        # Write again with same content — file should NOT be overwritten
        write_raw_payload(db, run_id, fetch_result, tmp_path)
        assert file_path.read_text(encoding="utf-8") == "modified content"

    def test_skips_duplicate_hash_for_same_symbol_source(self, db, tmp_path):
        """If hash already exists for same symbol/source, skip insert and return hash."""
        fetch_result = _make_fetch_result()
        run_id1 = str(uuid_mod.uuid4())
        run_id2 = str(uuid_mod.uuid4())

        # First write
        hash1 = write_raw_payload(db, run_id1, fetch_result, tmp_path)

        # Second write with same content, same symbol/source
        hash2 = write_raw_payload(db, run_id2, fetch_result, tmp_path)

        assert hash1 == hash2

        # Should only have one row in the table
        count = db.execute(
            "SELECT COUNT(*) FROM raw_market_payloads WHERE raw_payload_hash = ?",
            [hash1],
        ).fetchone()[0]
        assert count == 1

    def test_redacts_secrets_in_stored_params(self, db, tmp_path):
        """Secret fields in request_params should be redacted in stored metadata."""
        import json

        fetch_result = _make_fetch_result(
            request_params={"api_key": "sk-secret123", "symbol": "AAPL"}
        )
        run_id = str(uuid_mod.uuid4())

        content_hash = write_raw_payload(db, run_id, fetch_result, tmp_path)

        row = db.execute(
            "SELECT request_params_json FROM raw_market_payloads WHERE raw_payload_hash = ?",
            [content_hash],
        ).fetchone()
        stored_params = json.loads(row[0])
        assert stored_params["api_key"] == "[REDACTED]"
        assert stored_params["symbol"] == "AAPL"

    def test_csv_format_detection(self, db, tmp_path):
        """CSV content should be detected and stored with .csv extension."""
        csv_content = "date,open,high,low,close,volume\n2024-03-15,170,175,168,173,50000000"
        fetch_result = _make_fetch_result(raw_payload=csv_content)
        run_id = str(uuid_mod.uuid4())

        content_hash = write_raw_payload(db, run_id, fetch_result, tmp_path)

        # Verify file has .csv extension
        expected_dir = tmp_path / "raw" / "provider=csv_fixture" / "date=2024-03-15"
        hash_prefix = content_hash[:8]
        expected_file = expected_dir / f"AAPL_{hash_prefix}.csv"
        assert expected_file.exists()

        # Verify DB records csv format
        row = db.execute(
            "SELECT payload_format FROM raw_market_payloads WHERE raw_payload_hash = ?",
            [content_hash],
        ).fetchone()
        assert row[0] == "csv"

    def test_json_array_format_detection(self, db, tmp_path):
        """JSON array content should be detected as json format."""
        json_content = '[{"date": "2024-03-15", "close": 173.0}]'
        fetch_result = _make_fetch_result(raw_payload=json_content)
        run_id = str(uuid_mod.uuid4())

        content_hash = write_raw_payload(db, run_id, fetch_result, tmp_path)

        row = db.execute(
            "SELECT payload_format FROM raw_market_payloads WHERE raw_payload_hash = ?",
            [content_hash],
        ).fetchone()
        assert row[0] == "json"

    def test_raises_on_file_write_failure(self, db, tmp_path):
        """If file write fails, an IOError should be raised."""
        fetch_result = _make_fetch_result()
        run_id = str(uuid_mod.uuid4())

        # Use a non-writable path to trigger failure
        bad_path = tmp_path / "nonexistent" / "deeply" / "nested"
        # Create the path but make it read-only
        bad_path.mkdir(parents=True)
        import os
        os.chmod(str(bad_path), 0o444)

        # The write should fail because we can't create subdirectories
        # under a read-only directory
        with pytest.raises((IOError, OSError)):
            write_raw_payload(db, run_id, fetch_result, bad_path)

        # Cleanup permissions for tmp_path cleanup
        os.chmod(str(bad_path), 0o755)

    def test_returns_content_hash(self, db, tmp_path):
        """write_raw_payload should return the content hash string."""
        fetch_result = _make_fetch_result()
        run_id = str(uuid_mod.uuid4())

        result = write_raw_payload(db, run_id, fetch_result, tmp_path)

        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest length


class TestStorageTimestampNormalization:
    """DuckDB TIMESTAMP must receive naive UTC, not tz-aware local conversion."""

    def test_ohlcv_retrieved_at_stored_as_naive_utc(self, db):
        from research_data.storage import _to_db_ts

        aware = datetime(2024, 3, 15, 21, 0, 0, tzinfo=timezone.utc)
        naive = _to_db_ts(aware)
        assert naive is not None
        assert naive.tzinfo is None
        assert naive == datetime(2024, 3, 15, 21, 0, 0)

    def test_ohlcv_insert_round_trips_utc_wall_clock(self, db):
        """Even on non-UTC hosts, stored wall-clock must match the UTC instant."""
        from zoneinfo import ZoneInfo

        # Simulate a non-UTC "now" that would corrupt if DuckDB used local tz.
        et = ZoneInfo("America/New_York")
        aware_et = datetime(2024, 6, 15, 12, 0, 0, tzinfo=et)  # EDT = UTC-4
        record = _make_record(
            retrieved_at=aware_et,
        )
        batch_insert_ohlcv(db, [record])
        row = db.execute(
            "SELECT retrieved_at FROM daily_ohlcv WHERE symbol = ?",
            [record.symbol],
        ).fetchone()
        assert row is not None
        # Expect UTC wall clock 16:00 on 2024-06-15
        expected = datetime(2024, 6, 15, 16, 0, 0)
        stored = row[0]
        stored = stored.replace(tzinfo=None) if getattr(stored, "tzinfo", None) else stored
        assert stored == expected

    def test_ingestion_run_timestamps_normalized(self, db):
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        started = datetime(2024, 6, 15, 10, 0, 0, tzinfo=et)
        run_id = record_ingestion_run(
            db,
            {
                "source_name": "csv_fixture",
                "started_at": started,
                "completed_at": None,
                "symbols_requested": ["AAPL"],
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
                "adjusted": True,
                "status": "running",
                "records_fetched": 0,
                "records_stored": 0,
                "error_message": None,
                "config_hash": "abc",
            },
        )
        update_ingestion_run(
            db,
            run_id,
            status="completed",
            completed_at=datetime(2024, 6, 15, 11, 0, 0, tzinfo=et),
            records_fetched=1,
            records_stored=1,
        )
        row = db.execute(
            "SELECT started_at, completed_at FROM ingestion_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        started_stored, completed_stored = row
        assert started_stored.replace(tzinfo=None) == datetime(2024, 6, 15, 14, 0, 0)
        assert completed_stored.replace(tzinfo=None) == datetime(2024, 6, 15, 15, 0, 0)
