"""Unit tests for the normalization module (Task 6.5).

Covers:
- normalize_fetch_result converts valid records correctly (provenance fields populated)
- map_adjustment_policy maps known policies correctly
- map_adjustment_policy returns UNKNOWN for unrecognized policies
- Normalizer skips records that fail validation and increments rejected_count
- Normalizer sets defaults: split_factor=1.0, dividend_cash=0.0 when None
- Normalizer preserves adjusted_close separately from close

Requirements: 4.1–4.6
"""

import sys

sys.path.insert(0, "src")

from datetime import date, datetime, timezone

import pytest

from research_data.config import ProviderConfig
from research_data.models import (
    OHLCVRecord,
    PriceAdjustment,
    ProviderFetchResult,
    QualityStatus,
)
from research_data.normalization import (
    NormalizationResult,
    PassthroughCalendar,
    map_adjustment_policy,
    normalize_fetch_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider_config(**overrides) -> ProviderConfig:
    """Create a ProviderConfig with sensible defaults."""
    base = {
        "source_name": "csv_fixture",
        "source_url": "file://tests/fixtures",
        "license_note": "Local fixture data",
        "requires_api_key": False,
        "rate_limit": 100,
        "adjustment_policy": "split_dividend_adjusted",
    }
    base.update(overrides)
    return ProviderConfig(**base)


def _make_valid_record(**overrides) -> OHLCVRecord:
    """Create a valid OHLCVRecord with optional overrides."""
    base = {
        "symbol": "SPY",
        "asset_type": "etf",
        "exchange": "NYSE",
        "trading_date": date(2024, 3, 15),
        "open": 510.0,
        "high": 515.0,
        "low": 508.0,
        "close": 513.0,
        "adjusted_close": 512.5,
        "volume": 80000000,
        "split_factor": 1.0,
        "dividend_cash": 0.0,
        "price_adjustment": PriceAdjustment.RAW,
        "currency": "USD",
        "source": "original_source",
        "retrieved_at": datetime(2024, 3, 15, 20, 0, 0, tzinfo=timezone.utc),
        "data_as_of": date(2024, 3, 15),
        "raw_payload_hash": "original_hash_abc123",
    }
    base.update(overrides)
    return OHLCVRecord(**base)


def _make_fetch_result(records: list[OHLCVRecord], **overrides) -> ProviderFetchResult:
    """Create a ProviderFetchResult wrapping the given records."""
    base = {
        "symbol": "SPY",
        "provider": "csv_fixture",
        "request_url": "file://tests/fixtures/SPY.csv",
        "request_params": {},
        "retrieved_at": datetime(2024, 3, 16, 10, 0, 0, tzinfo=timezone.utc),
        "raw_payload": '{"data": "..."}',
        "content_hash": "sha256_fetch_result_hash_001",
        "records": records,
        "provider_warnings": [],
        "rate_limit_state": {},
    }
    base.update(overrides)
    return ProviderFetchResult(**base)


# ===========================================================================
# 1. normalize_fetch_result converts valid records correctly
# ===========================================================================


class TestNormalizeFetchResultValid:
    """Test that normalize_fetch_result converts valid records with correct provenance."""

    def test_single_valid_record_normalized(self):
        """A single valid record should be normalized with provenance fields populated."""
        record = _make_valid_record()
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        assert isinstance(result, NormalizationResult)
        assert len(result.valid_records) == 1
        assert result.rejected_count == 0
        assert result.warnings == []

    def test_provenance_fields_populated_from_fetch_result(self):
        """Provenance fields should come from the fetch result, not the original record."""
        record = _make_valid_record(source="old_source")
        fetch_result = _make_fetch_result(
            [record],
            retrieved_at=datetime(2024, 3, 16, 12, 0, 0, tzinfo=timezone.utc),
            content_hash="sha256_new_hash_xyz",
        )
        config = _make_provider_config(source_name="polygon")

        result = normalize_fetch_result(fetch_result, config)

        normalized = result.valid_records[0]
        assert normalized.source == "polygon"
        assert normalized.retrieved_at == datetime(2024, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
        assert normalized.raw_payload_hash == "sha256_new_hash_xyz"

    def test_multiple_valid_records_all_normalized(self):
        """Multiple valid records should all be normalized."""
        records = [
            _make_valid_record(trading_date=date(2024, 3, 13)),
            _make_valid_record(trading_date=date(2024, 3, 14)),
            _make_valid_record(trading_date=date(2024, 3, 15)),
        ]
        fetch_result = _make_fetch_result(records)
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        assert len(result.valid_records) == 3
        assert result.rejected_count == 0

    def test_price_adjustment_set_from_provider_config(self):
        """price_adjustment should be derived from provider's adjustment_policy."""
        record = _make_valid_record()
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config(adjustment_policy="raw")

        result = normalize_fetch_result(fetch_result, config)

        assert result.valid_records[0].price_adjustment == PriceAdjustment.RAW

    def test_data_as_of_defaults_to_trading_date(self):
        """When data_as_of is the trading_date, it should be preserved."""
        record = _make_valid_record(
            trading_date=date(2024, 3, 15),
            data_as_of=date(2024, 3, 15),
        )
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        assert result.valid_records[0].data_as_of == date(2024, 3, 15)


# ===========================================================================
# 2. map_adjustment_policy maps known policies correctly
# ===========================================================================


class TestMapAdjustmentPolicyKnown:
    """Test that map_adjustment_policy maps recognized policies correctly."""

    def test_raw_policy(self):
        assert map_adjustment_policy("raw") == PriceAdjustment.RAW

    def test_unadjusted_policy(self):
        assert map_adjustment_policy("unadjusted") == PriceAdjustment.RAW

    def test_split_adjusted_policy(self):
        assert map_adjustment_policy("split_adjusted") == PriceAdjustment.SPLIT_ADJUSTED

    def test_split_policy(self):
        assert map_adjustment_policy("split") == PriceAdjustment.SPLIT_ADJUSTED

    def test_split_dividend_adjusted_policy(self):
        assert map_adjustment_policy("split_dividend_adjusted") == PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED

    def test_fully_adjusted_policy(self):
        assert map_adjustment_policy("fully_adjusted") == PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED

    def test_adjusted_policy(self):
        assert map_adjustment_policy("adjusted") == PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED

    def test_case_insensitive(self):
        """Policy mapping should be case-insensitive."""
        assert map_adjustment_policy("RAW") == PriceAdjustment.RAW
        assert map_adjustment_policy("Split_Adjusted") == PriceAdjustment.SPLIT_ADJUSTED
        assert map_adjustment_policy("FULLY_ADJUSTED") == PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace should be stripped."""
        assert map_adjustment_policy("  raw  ") == PriceAdjustment.RAW
        assert map_adjustment_policy(" split ") == PriceAdjustment.SPLIT_ADJUSTED


# ===========================================================================
# 3. map_adjustment_policy returns UNKNOWN for unrecognized policies
# ===========================================================================


class TestMapAdjustmentPolicyUnknown:
    """Test that map_adjustment_policy returns UNKNOWN for unrecognized values."""

    def test_empty_string(self):
        assert map_adjustment_policy("") == PriceAdjustment.UNKNOWN

    def test_random_string(self):
        assert map_adjustment_policy("something_else") == PriceAdjustment.UNKNOWN

    def test_partial_match(self):
        assert map_adjustment_policy("raw_data") == PriceAdjustment.UNKNOWN

    def test_numeric_string(self):
        assert map_adjustment_policy("123") == PriceAdjustment.UNKNOWN

    def test_none_like_string(self):
        assert map_adjustment_policy("none") == PriceAdjustment.UNKNOWN


# ===========================================================================
# 4. Normalizer skips records that fail validation and increments rejected_count
# ===========================================================================


class TestNormalizerSkipsInvalidRecords:
    """Test that records failing validation are skipped with rejected_count incremented."""

    def test_negative_price_record_rejected(self):
        """A record with negative price should be rejected during normalization."""
        # Create a record that will fail validation when re-constructed
        # We need to bypass initial validation to create an "invalid" record
        # that the normalizer will try to re-validate
        valid_record = _make_valid_record(open=510.0)
        fetch_result = _make_fetch_result([valid_record])
        config = _make_provider_config()

        # Monkey-patch the record's open to negative after construction
        # to simulate a provider returning bad data
        # Instead, we'll use a record that passes initial validation but
        # fails when re-constructed with a future trading_date
        from datetime import timedelta

        future_date = date.today() + timedelta(days=30)
        # Create a record with a future date that will fail validation
        future_record = OHLCVRecord(
            symbol="SPY",
            asset_type="etf",
            exchange="NYSE",
            trading_date=date(2024, 3, 15),  # valid initially
            open=510.0,
            high=515.0,
            low=508.0,
            close=513.0,
            volume=80000000,
            price_adjustment=PriceAdjustment.RAW,
            source="test",
            retrieved_at=datetime(2024, 3, 15, 20, 0, 0, tzinfo=timezone.utc),
            data_as_of=date(2024, 3, 15),
            raw_payload_hash="hash123",
        )

        # Use a custom calendar that returns a future date to trigger validation failure
        class FutureDateCalendar:
            def to_trading_date(self, dt, exchange):
                return future_date

        fetch_result = _make_fetch_result([future_record])
        result = normalize_fetch_result(fetch_result, config, calendar=FutureDateCalendar())

        assert result.rejected_count == 1
        assert len(result.valid_records) == 0
        assert len(result.warnings) == 1

    def test_mix_of_valid_and_invalid_records(self):
        """Valid records should pass while invalid ones are rejected."""
        valid_record = _make_valid_record(trading_date=date(2024, 3, 14))
        another_valid = _make_valid_record(trading_date=date(2024, 3, 15))

        fetch_result = _make_fetch_result([valid_record, another_valid])
        config = _make_provider_config()

        # Use a calendar that makes only the first record fail
        class SelectiveFailCalendar:
            def __init__(self):
                self._call_count = 0

            def to_trading_date(self, dt, exchange):
                self._call_count += 1
                if self._call_count == 1:
                    # Return a future date for the first record
                    from datetime import timedelta
                    return date.today() + timedelta(days=30)
                return dt

        result = normalize_fetch_result(fetch_result, config, calendar=SelectiveFailCalendar())

        assert result.rejected_count == 1
        assert len(result.valid_records) == 1

    def test_rejected_count_matches_number_of_failures(self):
        """rejected_count should equal the number of failed records."""
        records = [_make_valid_record(trading_date=date(2024, 3, d)) for d in range(11, 16)]
        fetch_result = _make_fetch_result(records)
        config = _make_provider_config()

        # Calendar that fails all records
        class AllFailCalendar:
            def to_trading_date(self, dt, exchange):
                from datetime import timedelta
                return date.today() + timedelta(days=30)

        result = normalize_fetch_result(fetch_result, config, calendar=AllFailCalendar())

        assert result.rejected_count == 5
        assert len(result.valid_records) == 0
        assert len(result.warnings) == 5


# ===========================================================================
# 5. Normalizer sets defaults: split_factor=1.0, dividend_cash=0.0 when None
# ===========================================================================


class TestNormalizerDefaults:
    """Test that normalizer sets default values for split_factor and dividend_cash."""

    def test_split_factor_defaults_to_one(self):
        """When split_factor is None, normalizer should set it to 1.0."""
        record = _make_valid_record(split_factor=None)
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        assert len(result.valid_records) == 1
        assert result.valid_records[0].split_factor == 1.0

    def test_dividend_cash_defaults_to_zero(self):
        """When dividend_cash is None, normalizer should set it to 0.0."""
        record = _make_valid_record(dividend_cash=None)
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        assert len(result.valid_records) == 1
        assert result.valid_records[0].dividend_cash == 0.0

    def test_both_defaults_applied_together(self):
        """Both split_factor and dividend_cash should default when both are None."""
        record = _make_valid_record(split_factor=None, dividend_cash=None)
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        normalized = result.valid_records[0]
        assert normalized.split_factor == 1.0
        assert normalized.dividend_cash == 0.0

    def test_explicit_values_preserved(self):
        """When split_factor and dividend_cash are explicitly set, they should be preserved."""
        record = _make_valid_record(split_factor=2.0, dividend_cash=1.50)
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        normalized = result.valid_records[0]
        assert normalized.split_factor == 2.0
        assert normalized.dividend_cash == 1.50


# ===========================================================================
# 6. Normalizer preserves adjusted_close separately from close
# ===========================================================================


class TestNormalizerAdjustedClose:
    """Test that adjusted_close is preserved separately from close."""

    def test_adjusted_close_preserved_when_different_from_close(self):
        """adjusted_close should be stored separately even when different from close."""
        record = _make_valid_record(close=513.0, adjusted_close=510.0)
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        normalized = result.valid_records[0]
        assert normalized.close == 513.0
        assert normalized.adjusted_close == 510.0
        assert normalized.close != normalized.adjusted_close

    def test_adjusted_close_none_when_not_supplied(self):
        """When provider doesn't supply adjusted_close, it should remain None."""
        record = _make_valid_record(adjusted_close=None)
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        normalized = result.valid_records[0]
        assert normalized.adjusted_close is None

    def test_adjusted_close_same_as_close_preserved(self):
        """Even when adjusted_close equals close, both should be stored."""
        record = _make_valid_record(close=513.0, adjusted_close=513.0)
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        normalized = result.valid_records[0]
        assert normalized.close == 513.0
        assert normalized.adjusted_close == 513.0

    def test_close_not_overwritten_by_adjusted_close(self):
        """The close field should never be overwritten by adjusted_close."""
        record = _make_valid_record(
            open=510.0, high=515.0, low=495.0, close=500.0, adjusted_close=495.0
        )
        fetch_result = _make_fetch_result([record])
        config = _make_provider_config()

        result = normalize_fetch_result(fetch_result, config)

        normalized = result.valid_records[0]
        assert normalized.close == 500.0
        assert normalized.adjusted_close == 495.0


# ===========================================================================
# 7. PassthroughCalendar behavior
# ===========================================================================


class TestPassthroughCalendar:
    """Test the PassthroughCalendar default implementation."""

    def test_date_passes_through(self):
        cal = PassthroughCalendar()
        d = date(2024, 3, 15)
        assert cal.to_trading_date(d, "NYSE") == d

    def test_datetime_converted_to_date(self):
        cal = PassthroughCalendar()
        dt = datetime(2024, 3, 15, 14, 30, 0, tzinfo=timezone.utc)
        assert cal.to_trading_date(dt, "NYSE") == date(2024, 3, 15)

    def test_exchange_none_accepted(self):
        cal = PassthroughCalendar()
        d = date(2024, 6, 1)
        assert cal.to_trading_date(d, None) == d
