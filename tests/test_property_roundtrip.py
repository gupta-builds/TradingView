"""Property-based tests for OHLCV round-trip integrity (Property 2).

Property 2: OHLCV Round-Trip Integrity
For any valid OHLCVRecord that passes validation, storing it in DuckDB and reading
it back SHALL produce a record with identical field values for all price, volume,
date, provenance, and quality fields.

**Validates: Requirements 4.1, 10.1, 10.4**
"""

import sys

sys.path.insert(0, "src")

from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from research_data.models import OHLCVRecord, PriceAdjustment, QualityStatus
from research_data.storage import batch_insert_ohlcv, init_db


# ---------------------------------------------------------------------------
# Hypothesis strategies for valid OHLCVRecords
# ---------------------------------------------------------------------------

# Valid uppercase symbols (1-10 uppercase ASCII letters)
valid_symbols = st.from_regex(r"[A-Z]{1,5}", fullmatch=True)

# Valid asset types
valid_asset_types = st.sampled_from(["equity", "etf"])

# Valid exchanges (optional)
valid_exchanges = st.one_of(st.none(), st.sampled_from(["NYSE", "NASDAQ", "ARCA"]))

# Past trading dates (between 2020-01-01 and today)
_TODAY = datetime.now(timezone.utc).date()
valid_trading_dates = st.dates(
    min_value=date(2020, 1, 1),
    max_value=_TODAY,
)

# Positive prices with reasonable range
valid_prices = st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)

# Non-negative volume
valid_volumes = st.integers(min_value=0, max_value=10_000_000_000)

# Optional positive adjusted_close
valid_adjusted_close = st.one_of(
    st.none(),
    st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
)

# Optional split_factor (positive when present)
valid_split_factor = st.one_of(
    st.none(),
    st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
)

# Optional dividend_cash (non-negative when present)
valid_dividend_cash = st.one_of(
    st.none(),
    st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)

# Valid price adjustments
valid_price_adjustments = st.sampled_from(list(PriceAdjustment))

# Valid quality statuses
valid_quality_statuses = st.sampled_from(list(QualityStatus))

# Valid sources
valid_sources = st.sampled_from(["polygon", "tiingo", "csv_fixture", "alpha_vantage"])

# Valid raw_payload_hash (non-empty hex-like strings)
valid_hashes = st.from_regex(r"[a-f0-9]{16,64}", fullmatch=True)

# Valid retrieved_at timestamps (past, with UTC timezone)
valid_retrieved_at = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2025, 6, 1),
    timezones=st.just(timezone.utc),
)

# Valid data_as_of dates (past)
valid_data_as_of = st.dates(
    min_value=date(2020, 1, 1),
    max_value=_TODAY,
)

# Currency
valid_currencies = st.sampled_from(["USD", "EUR", "GBP"])

# Optional source_record_id
valid_source_record_ids = st.one_of(st.none(), st.from_regex(r"[a-zA-Z0-9_-]{5,20}", fullmatch=True))


@st.composite
def valid_ohlcv_records(draw):
    """Generate a valid OHLCVRecord with consistent OHLC relationships.

    Ensures high >= open, close, low and low <= open, close.
    """
    # Generate four prices and arrange them to satisfy OHLC constraints
    p1 = draw(valid_prices)
    p2 = draw(valid_prices)
    p3 = draw(valid_prices)
    p4 = draw(valid_prices)

    prices = sorted([p1, p2, p3, p4])
    low = prices[0]
    high = prices[3]
    # open and close are between low and high
    open_price = prices[1]
    close_price = prices[2]

    return OHLCVRecord(
        symbol=draw(valid_symbols),
        asset_type=draw(valid_asset_types),
        exchange=draw(valid_exchanges),
        trading_date=draw(valid_trading_dates),
        open=open_price,
        high=high,
        low=low,
        close=close_price,
        adjusted_close=draw(valid_adjusted_close),
        volume=draw(valid_volumes),
        split_factor=draw(valid_split_factor),
        dividend_cash=draw(valid_dividend_cash),
        price_adjustment=draw(valid_price_adjustments),
        currency=draw(valid_currencies),
        source=draw(valid_sources),
        source_record_id=draw(valid_source_record_ids),
        retrieved_at=draw(valid_retrieved_at),
        data_as_of=draw(valid_data_as_of),
        raw_payload_hash=draw(valid_hashes),
        quality_status=draw(valid_quality_statuses),
    )


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


class TestProperty2OHLCVRoundTripIntegrity:
    """Property 2: OHLCV Round-Trip Integrity.

    For any valid OHLCVRecord that passes validation, storing it in DuckDB
    and reading it back SHALL produce a record with identical field values
    for all price, volume, date, provenance, and quality fields.

    **Validates: Requirements 4.1, 10.1, 10.4**
    """

    @given(record=valid_ohlcv_records())
    @settings(max_examples=100, deadline=None)
    def test_roundtrip_preserves_all_fields(self, record: OHLCVRecord):
        """Store a valid OHLCVRecord in DuckDB and verify all fields survive the round trip."""
        # Create a fresh in-memory DuckDB for each test case
        conn = duckdb.connect(":memory:")
        try:
            # Set timezone to UTC so TIMESTAMP round-trips correctly with UTC datetimes
            conn.execute("SET TimeZone='UTC'")
            init_db(conn)

            # Store the record
            inserted = batch_insert_ohlcv(conn, [record])
            assert inserted == 1

            # Read back from daily_ohlcv
            rows = conn.execute(
                """
                SELECT symbol, asset_type, exchange, trading_date,
                       open, high, low, close, adjusted_close, volume,
                       split_factor, dividend_cash, price_adjustment, currency,
                       source, source_record_id, retrieved_at, data_as_of,
                       raw_payload_hash, quality_status
                FROM daily_ohlcv
                WHERE symbol = ? AND trading_date = ? AND source = ? AND price_adjustment = ?
                """,
                [
                    record.symbol,
                    record.trading_date,
                    record.source,
                    record.price_adjustment.value,
                ],
            ).fetchall()

            assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
            row = rows[0]

            # Verify all fields match
            assert row[0] == record.symbol, f"symbol mismatch: {row[0]} != {record.symbol}"
            assert row[1] == record.asset_type, f"asset_type mismatch: {row[1]} != {record.asset_type}"
            assert row[2] == record.exchange, f"exchange mismatch: {row[2]} != {record.exchange}"
            assert row[3] == record.trading_date, f"trading_date mismatch: {row[3]} != {record.trading_date}"

            # Price fields - use approximate comparison for floating point
            assert row[4] == pytest.approx(record.open, rel=1e-10), f"open mismatch: {row[4]} != {record.open}"
            assert row[5] == pytest.approx(record.high, rel=1e-10), f"high mismatch: {row[5]} != {record.high}"
            assert row[6] == pytest.approx(record.low, rel=1e-10), f"low mismatch: {row[6]} != {record.low}"
            assert row[7] == pytest.approx(record.close, rel=1e-10), f"close mismatch: {row[7]} != {record.close}"

            # adjusted_close (nullable)
            if record.adjusted_close is None:
                assert row[8] is None, f"adjusted_close should be None, got {row[8]}"
            else:
                assert row[8] == pytest.approx(record.adjusted_close, rel=1e-10), (
                    f"adjusted_close mismatch: {row[8]} != {record.adjusted_close}"
                )

            # volume
            assert row[9] == record.volume, f"volume mismatch: {row[9]} != {record.volume}"

            # split_factor (nullable)
            if record.split_factor is None:
                assert row[10] is None, f"split_factor should be None, got {row[10]}"
            else:
                assert row[10] == pytest.approx(record.split_factor, rel=1e-10), (
                    f"split_factor mismatch: {row[10]} != {record.split_factor}"
                )

            # dividend_cash (nullable)
            if record.dividend_cash is None:
                assert row[11] is None, f"dividend_cash should be None, got {row[11]}"
            else:
                assert row[11] == pytest.approx(record.dividend_cash, rel=1e-10), (
                    f"dividend_cash mismatch: {row[11]} != {record.dividend_cash}"
                )

            # price_adjustment (stored as enum value string)
            assert row[12] == record.price_adjustment.value, (
                f"price_adjustment mismatch: {row[12]} != {record.price_adjustment.value}"
            )

            # currency
            assert row[13] == record.currency, f"currency mismatch: {row[13]} != {record.currency}"

            # source
            assert row[14] == record.source, f"source mismatch: {row[14]} != {record.source}"

            # source_record_id (nullable)
            assert row[15] == record.source_record_id, (
                f"source_record_id mismatch: {row[15]} != {record.source_record_id}"
            )

            # retrieved_at (timestamp)
            # DuckDB TIMESTAMP type stores without timezone info. With TimeZone='UTC',
            # the naive datetime returned is in UTC, matching our input.
            stored_retrieved_at = row[16]
            # Compare as naive UTC datetimes (strip tzinfo from the expected value)
            expected_naive = record.retrieved_at.astimezone(timezone.utc).replace(tzinfo=None)
            stored_naive = stored_retrieved_at if stored_retrieved_at.tzinfo is None else stored_retrieved_at.replace(tzinfo=None)
            assert stored_naive == expected_naive, (
                f"retrieved_at mismatch: {stored_naive} != {expected_naive}"
            )

            # data_as_of
            assert row[17] == record.data_as_of, f"data_as_of mismatch: {row[17]} != {record.data_as_of}"

            # raw_payload_hash
            assert row[18] == record.raw_payload_hash, (
                f"raw_payload_hash mismatch: {row[18]} != {record.raw_payload_hash}"
            )

            # quality_status (stored as enum value string)
            assert row[19] == record.quality_status.value, (
                f"quality_status mismatch: {row[19]} != {record.quality_status.value}"
            )
        finally:
            conn.close()
