"""Property-based tests for OHLCV validation (Property 1).

Property 1: OHLCV Validation Rejects Invalid Records
For any OHLCVRecord with non-positive prices, high < open/close, low > open/close,
negative volume, non-positive adjusted_close, future dates, lowercase/invalid symbols,
or empty raw_payload_hash, the Validator SHALL reject the record.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8**
"""

import sys

sys.path.insert(0, "src")

from datetime import date, datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from research_data.models import OHLCVRecord, PriceAdjustment, QualityStatus


# ---------------------------------------------------------------------------
# Shared helpers and strategies
# ---------------------------------------------------------------------------

# A valid base record dict that passes all validation rules.
_TODAY = datetime.now(timezone.utc).date()

_VALID_BASE = {
    "symbol": "AAPL",
    "asset_type": "equity",
    "exchange": "NASDAQ",
    "trading_date": date(2024, 6, 15),
    "open": 150.0,
    "high": 155.0,
    "low": 148.0,
    "close": 153.0,
    "volume": 1000000,
    "price_adjustment": PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
    "source": "polygon",
    "retrieved_at": datetime(2024, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
    "data_as_of": date(2024, 6, 15),
    "raw_payload_hash": "abc123def456",
}


def _make_record(**overrides) -> dict:
    """Return a valid record dict with overrides applied."""
    d = dict(_VALID_BASE)
    d.update(overrides)
    return d


# Strategy for non-positive floats (zero or negative)
non_positive_floats = st.floats(max_value=0.0, allow_nan=False, allow_infinity=False)

# Strategy for negative integers
negative_integers = st.integers(max_value=-1)

# Strategy for future dates (1 to 3650 days in the future)
future_dates = st.integers(min_value=1, max_value=3650).map(
    lambda days: _TODAY + timedelta(days=days)
)

# Strategy for invalid symbols: lowercase, mixed case, numbers, too long, empty
invalid_symbols = st.one_of(
    # Lowercase letters
    st.from_regex(r"[a-z]{1,10}", fullmatch=True),
    # Mixed case
    st.from_regex(r"[A-Za-z]{2,10}", fullmatch=True).filter(
        lambda s: s != s.upper()
    ),
    # Contains digits
    st.from_regex(r"[A-Z0-9]{2,10}", fullmatch=True).filter(
        lambda s: any(c.isdigit() for c in s)
    ),
    # Too long (11+ uppercase letters)
    st.from_regex(r"[A-Z]{11,15}", fullmatch=True),
    # Empty string
    st.just(""),
    # Contains special characters
    st.from_regex(r"[A-Z!@#$%]{2,5}", fullmatch=True).filter(
        lambda s: any(not c.isalpha() for c in s)
    ),
)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestProperty1OHLCVValidationRejectsInvalid:
    """Property 1: OHLCV Validation Rejects Invalid Records.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8**
    """

    @given(price=non_positive_floats)
    @settings(max_examples=100)
    def test_rejects_non_positive_open(self, price: float):
        """Requirement 5.1: open must be strictly greater than zero."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(open=price))

    @given(price=non_positive_floats)
    @settings(max_examples=100)
    def test_rejects_non_positive_high(self, price: float):
        """Requirement 5.1: high must be strictly greater than zero."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(high=price))

    @given(price=non_positive_floats)
    @settings(max_examples=100)
    def test_rejects_non_positive_low(self, price: float):
        """Requirement 5.1: low must be strictly greater than zero."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(low=price))

    @given(price=non_positive_floats)
    @settings(max_examples=100)
    def test_rejects_non_positive_close(self, price: float):
        """Requirement 5.1: close must be strictly greater than zero."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(close=price))

    @given(
        open_price=st.floats(min_value=100.0, max_value=200.0, allow_nan=False),
        high_offset=st.floats(min_value=0.01, max_value=50.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_rejects_high_less_than_open(self, open_price: float, high_offset: float):
        """Requirement 5.2: high must be >= open."""
        high = open_price - high_offset  # high < open
        assume(high > 0)  # still a positive price
        low = min(high, open_price) - 1.0
        assume(low > 0)
        close = low  # ensure low <= close
        with pytest.raises(ValidationError):
            OHLCVRecord(
                **_make_record(open=open_price, high=high, low=low, close=close)
            )

    @given(
        close_price=st.floats(min_value=100.0, max_value=200.0, allow_nan=False),
        high_offset=st.floats(min_value=0.01, max_value=50.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_rejects_high_less_than_close(
        self, close_price: float, high_offset: float
    ):
        """Requirement 5.2: high must be >= close."""
        high = close_price - high_offset  # high < close
        assume(high > 0)
        # Set open <= high so that high >= open passes, isolating the high < close check
        open_price = high
        low = min(open_price, high) - 1.0
        assume(low > 0)
        with pytest.raises(ValidationError):
            OHLCVRecord(
                **_make_record(
                    open=open_price, high=high, low=low, close=close_price
                )
            )

    @given(
        open_price=st.floats(min_value=50.0, max_value=150.0, allow_nan=False),
        low_offset=st.floats(min_value=0.01, max_value=30.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_rejects_low_greater_than_open(
        self, open_price: float, low_offset: float
    ):
        """Requirement 5.3: low must be <= open."""
        low = open_price + low_offset  # low > open
        high = low + 10.0  # ensure high >= low, high >= open
        close = low  # ensure low <= close
        with pytest.raises(ValidationError):
            OHLCVRecord(
                **_make_record(open=open_price, high=high, low=low, close=close)
            )

    @given(
        close_price=st.floats(min_value=50.0, max_value=150.0, allow_nan=False),
        low_offset=st.floats(min_value=0.01, max_value=30.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_rejects_low_greater_than_close(
        self, close_price: float, low_offset: float
    ):
        """Requirement 5.3: low must be <= close."""
        low = close_price + low_offset  # low > close
        high = low + 10.0  # ensure high >= everything
        open_price = low  # ensure low <= open
        with pytest.raises(ValidationError):
            OHLCVRecord(
                **_make_record(
                    open=open_price, high=high, low=low, close=close_price
                )
            )

    @given(volume=negative_integers)
    @settings(max_examples=100)
    def test_rejects_negative_volume(self, volume: int):
        """Requirement 5.4: volume must be non-negative."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(volume=volume))

    @given(
        adj_close=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_rejects_non_positive_adjusted_close(self, adj_close: float):
        """Requirement 5.5: adjusted_close, when present, must be > 0."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(adjusted_close=adj_close))

    @given(future_date=future_dates)
    @settings(max_examples=50)
    def test_rejects_future_trading_date(self, future_date: date):
        """Requirement 5.6: trading_date cannot be in the future."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(trading_date=future_date))

    @given(future_date=future_dates)
    @settings(max_examples=50)
    def test_rejects_future_data_as_of(self, future_date: date):
        """Requirement 5.6: data_as_of cannot be in the future."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(data_as_of=future_date))

    @given(symbol=invalid_symbols)
    @settings(max_examples=100)
    def test_rejects_invalid_symbols(self, symbol: str):
        """Requirement 5.7: symbol must be 1-10 uppercase ASCII letters only."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(symbol=symbol))

    @given(
        hash_val=st.one_of(
            st.just(""),
            st.just("   "),
            st.just("\t"),
            st.just("\n"),
            st.just("  \t\n  "),
            st.text(
                alphabet=st.sampled_from(" \t\n\r"),
                min_size=1,
                max_size=10,
            ),
        )
    )
    @settings(max_examples=50)
    def test_rejects_empty_raw_payload_hash(self, hash_val: str):
        """Requirement 5.8 (partial): raw_payload_hash must be non-empty."""
        with pytest.raises(ValidationError):
            OHLCVRecord(**_make_record(raw_payload_hash=hash_val))
