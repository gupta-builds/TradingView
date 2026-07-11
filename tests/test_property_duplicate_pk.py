"""Property-based tests for duplicate primary key handling (Property 12).

Property 12: Duplicate Primary Key Rejection
For any attempt to insert a record into daily_ohlcv with a
(symbol, trading_date, source, price_adjustment) tuple that already exists,
the Storage SHALL overwrite the existing record (INSERT OR REPLACE upsert behavior),
resulting in exactly one row with the values from the second insert.

**Validates: Requirements 8.2**
"""

import sys

sys.path.insert(0, "src")

from datetime import date, datetime, timezone

import duckdb
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from research_data.models import OHLCVRecord, PriceAdjustment, QualityStatus
from research_data.storage import batch_insert_ohlcv, init_db


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid symbols (1-10 uppercase ASCII letters)
valid_symbols = st.from_regex(r"[A-Z]{1,5}", fullmatch=True)

# Valid sources
valid_sources = st.sampled_from(["polygon", "tiingo", "alpha_vantage", "fmp", "csv_fixture"])

# Valid price adjustments
valid_price_adjustments = st.sampled_from(list(PriceAdjustment))

# Valid trading dates (historical, not in the future)
valid_trading_dates = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2024, 12, 31),
)

# Positive prices for OHLCV
positive_prices = st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False)

# Non-negative volumes
valid_volumes = st.integers(min_value=0, max_value=10_000_000)

# Valid raw payload hashes
valid_hashes = st.text(
    alphabet=st.sampled_from("0123456789abcdef"),
    min_size=8,
    max_size=64,
)


@st.composite
def ohlcv_prices(draw):
    """Generate valid OHLC prices satisfying high >= open/close >= low."""
    low = draw(st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    high = draw(st.floats(min_value=low, max_value=low + 500.0, allow_nan=False, allow_infinity=False))
    open_price = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
    close_price = draw(st.floats(min_value=low, max_value=high, allow_nan=False, allow_infinity=False))
    return low, high, open_price, close_price


@st.composite
def valid_ohlcv_record(draw, symbol=None, trading_date=None, source=None, price_adjustment=None):
    """Generate a valid OHLCVRecord with optional fixed PK fields."""
    sym = symbol or draw(valid_symbols)
    td = trading_date or draw(valid_trading_dates)
    src = source or draw(valid_sources)
    pa = price_adjustment or draw(valid_price_adjustments)

    low, high, open_price, close_price = draw(ohlcv_prices())
    volume = draw(valid_volumes)
    raw_hash = draw(valid_hashes)

    return OHLCVRecord(
        symbol=sym,
        asset_type="equity",
        exchange="NYSE",
        trading_date=td,
        open=open_price,
        high=high,
        low=low,
        close=close_price,
        volume=volume,
        price_adjustment=pa,
        currency="USD",
        source=src,
        retrieved_at=datetime(2024, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
        data_as_of=date(2024, 6, 15),
        raw_payload_hash=raw_hash,
        quality_status=QualityStatus.USABLE,
    )


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestProperty12DuplicatePrimaryKeyHandling:
    """Property 12: Duplicate Primary Key Rejection.

    When two records share the same composite primary key
    (symbol, trading_date, source, price_adjustment), inserting both
    results in exactly one row with the values from the second insert.

    **Validates: Requirements 8.2**
    """

    @given(
        symbol=valid_symbols,
        trading_date=valid_trading_dates,
        source=valid_sources,
        price_adjustment=valid_price_adjustments,
        prices1=ohlcv_prices(),
        prices2=ohlcv_prices(),
        volume1=valid_volumes,
        volume2=valid_volumes,
        hash1=valid_hashes,
        hash2=valid_hashes,
    )
    @settings(max_examples=100, deadline=None)
    def test_upsert_overwrites_duplicate_pk(
        self,
        symbol: str,
        trading_date: date,
        source: str,
        price_adjustment: PriceAdjustment,
        prices1: tuple,
        prices2: tuple,
        volume1: int,
        volume2: int,
        hash1: str,
        hash2: str,
    ):
        """Inserting two records with the same PK results in one row with second record's values."""
        low1, high1, open1, close1 = prices1
        low2, high2, open2, close2 = prices2

        # Ensure the two records differ in at least one non-PK field
        assume(
            close1 != close2
            or volume1 != volume2
            or hash1 != hash2
        )

        record1 = OHLCVRecord(
            symbol=symbol,
            asset_type="equity",
            exchange="NYSE",
            trading_date=trading_date,
            open=open1,
            high=high1,
            low=low1,
            close=close1,
            volume=volume1,
            price_adjustment=price_adjustment,
            currency="USD",
            source=source,
            retrieved_at=datetime(2024, 6, 15, 18, 0, 0, tzinfo=timezone.utc),
            data_as_of=date(2024, 6, 15),
            raw_payload_hash=hash1,
            quality_status=QualityStatus.USABLE,
        )

        record2 = OHLCVRecord(
            symbol=symbol,
            asset_type="equity",
            exchange="NYSE",
            trading_date=trading_date,
            open=open2,
            high=high2,
            low=low2,
            close=close2,
            volume=volume2,
            price_adjustment=price_adjustment,
            currency="USD",
            source=source,
            retrieved_at=datetime(2024, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
            data_as_of=date(2024, 6, 15),
            raw_payload_hash=hash2,
            quality_status=QualityStatus.USABLE,
        )

        # Use a fresh in-memory DuckDB for each test case
        conn = duckdb.connect(":memory:")
        init_db(conn)

        # Insert first record
        batch_insert_ohlcv(conn, [record1])

        # Insert second record with same PK
        batch_insert_ohlcv(conn, [record2])

        # Verify exactly one row exists for this PK
        result = conn.execute(
            """
            SELECT close, volume, raw_payload_hash
            FROM daily_ohlcv
            WHERE symbol = ?
              AND trading_date = ?
              AND source = ?
              AND price_adjustment = ?
            """,
            [symbol, trading_date, source, price_adjustment.value],
        ).fetchall()

        assert len(result) == 1, (
            f"Expected exactly 1 row for PK ({symbol}, {trading_date}, {source}, "
            f"{price_adjustment.value}), got {len(result)}"
        )

        # Verify the row has values from the second insert
        row_close, row_volume, row_hash = result[0]
        assert row_close == close2, (
            f"Expected close={close2} from second insert, got {row_close}"
        )
        assert row_volume == volume2, (
            f"Expected volume={volume2} from second insert, got {row_volume}"
        )
        assert row_hash == hash2, (
            f"Expected raw_payload_hash={hash2!r} from second insert, got {row_hash!r}"
        )

        conn.close()
