"""Comprehensive unit tests for research_data models (Task 1.4).

Covers:
- Valid OHLCVRecord construction with all fields
- Each validation rule independently (Requirements 5.1-5.7)
- Enum serialization/deserialization
- ProviderCapabilities and ProviderFetchResult construction
- DataQualityReport construction
- DataEvidencePacket construction and JSON round-trip
- InsufficientDataError construction and attributes
"""

import sys

sys.path.insert(0, "src")

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from research_data.models import (
    DataEvidencePacket,
    DataQualityReport,
    EvidenceRef,
    InsufficientDataError,
    OHLCVRecord,
    PriceAdjustment,
    ProviderCapabilities,
    ProviderFetchResult,
    QualityStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_record_kwargs(**overrides) -> dict:
    """Return kwargs for a valid OHLCVRecord with optional overrides."""
    base = {
        "symbol": "MSFT",
        "asset_type": "equity",
        "exchange": "NASDAQ",
        "trading_date": date(2024, 3, 15),
        "open": 420.0,
        "high": 425.0,
        "low": 418.0,
        "close": 423.0,
        "adjusted_close": 422.5,
        "volume": 5000000,
        "split_factor": 1.0,
        "dividend_cash": 0.0,
        "price_adjustment": PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
        "currency": "USD",
        "source": "polygon",
        "source_record_id": "poly-123",
        "retrieved_at": datetime(2024, 3, 15, 21, 0, 0, tzinfo=timezone.utc),
        "data_as_of": date(2024, 3, 15),
        "raw_payload_hash": "sha256_abcdef1234567890",
        "quality_status": QualityStatus.USABLE,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. Valid OHLCVRecord construction
# ===========================================================================


class TestOHLCVRecordValidConstruction:
    """Test that valid OHLCVRecord construction succeeds with all fields."""

    def test_full_record_all_fields(self):
        record = OHLCVRecord(**_valid_record_kwargs())
        assert record.symbol == "MSFT"
        assert record.asset_type == "equity"
        assert record.exchange == "NASDAQ"
        assert record.trading_date == date(2024, 3, 15)
        assert record.open == 420.0
        assert record.high == 425.0
        assert record.low == 418.0
        assert record.close == 423.0
        assert record.adjusted_close == 422.5
        assert record.volume == 5000000
        assert record.split_factor == 1.0
        assert record.dividend_cash == 0.0
        assert record.price_adjustment == PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED
        assert record.currency == "USD"
        assert record.source == "polygon"
        assert record.source_record_id == "poly-123"
        assert record.retrieved_at == datetime(2024, 3, 15, 21, 0, 0, tzinfo=timezone.utc)
        assert record.data_as_of == date(2024, 3, 15)
        assert record.raw_payload_hash == "sha256_abcdef1234567890"
        assert record.quality_status == QualityStatus.USABLE

    def test_minimal_record_optional_fields_none(self):
        record = OHLCVRecord(**_valid_record_kwargs(
            adjusted_close=None,
            split_factor=None,
            dividend_cash=None,
            exchange=None,
            source_record_id=None,
        ))
        assert record.adjusted_close is None
        assert record.split_factor is None
        assert record.dividend_cash is None
        assert record.exchange is None
        assert record.source_record_id is None

    def test_etf_asset_type(self):
        record = OHLCVRecord(**_valid_record_kwargs(symbol="VOO", asset_type="etf"))
        assert record.asset_type == "etf"

    def test_zero_volume_accepted(self):
        record = OHLCVRecord(**_valid_record_kwargs(volume=0))
        assert record.volume == 0

    def test_high_equals_open_close_low(self):
        """All prices equal is valid (flat day)."""
        record = OHLCVRecord(**_valid_record_kwargs(
            open=100.0, high=100.0, low=100.0, close=100.0
        ))
        assert record.open == record.high == record.low == record.close == 100.0


# ===========================================================================
# 2. Each validation rule rejects invalid data independently
# ===========================================================================


class TestValidationNonPositivePrices:
    """Requirement 5.1: open, high, low, close must be > 0."""

    def test_zero_open_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            OHLCVRecord(**_valid_record_kwargs(open=0.0))

    def test_negative_open_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            OHLCVRecord(**_valid_record_kwargs(open=-10.0))

    def test_zero_high_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            OHLCVRecord(**_valid_record_kwargs(high=0.0))

    def test_negative_high_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            OHLCVRecord(**_valid_record_kwargs(high=-5.0))

    def test_zero_low_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            OHLCVRecord(**_valid_record_kwargs(low=0.0))

    def test_negative_low_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            OHLCVRecord(**_valid_record_kwargs(low=-1.0))

    def test_zero_close_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            OHLCVRecord(**_valid_record_kwargs(close=0.0))

    def test_negative_close_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            OHLCVRecord(**_valid_record_kwargs(close=-50.0))


class TestValidationHighRelationships:
    """Requirement 5.2: high must be >= open, close, low."""

    def test_high_less_than_open_rejected(self):
        with pytest.raises(ValidationError, match="high.*open"):
            OHLCVRecord(**_valid_record_kwargs(
                open=150.0, high=149.0, low=148.0, close=148.5
            ))

    def test_high_less_than_close_rejected(self):
        with pytest.raises(ValidationError, match="high.*close"):
            OHLCVRecord(**_valid_record_kwargs(
                open=150.0, high=151.0, low=148.0, close=152.0
            ))


class TestValidationLowRelationships:
    """Requirement 5.3: low must be <= open, close."""

    def test_low_greater_than_open_rejected(self):
        with pytest.raises(ValidationError, match="low.*open"):
            OHLCVRecord(**_valid_record_kwargs(
                open=150.0, high=155.0, low=151.0, close=153.0
            ))

    def test_low_greater_than_close_rejected(self):
        with pytest.raises(ValidationError, match="low.*close"):
            OHLCVRecord(**_valid_record_kwargs(
                open=153.0, high=155.0, low=152.0, close=151.0
            ))


class TestValidationVolume:
    """Requirement 5.4: volume must be >= 0."""

    def test_negative_volume_rejected(self):
        with pytest.raises(ValidationError, match="[Vv]olume"):
            OHLCVRecord(**_valid_record_kwargs(volume=-1))

    def test_large_negative_volume_rejected(self):
        with pytest.raises(ValidationError, match="[Vv]olume"):
            OHLCVRecord(**_valid_record_kwargs(volume=-999999))


class TestValidationAdjustedClose:
    """Requirement 5.5: adjusted_close, if present, must be > 0."""

    def test_zero_adjusted_close_rejected(self):
        with pytest.raises(ValidationError, match="[Aa]djusted"):
            OHLCVRecord(**_valid_record_kwargs(adjusted_close=0.0))

    def test_negative_adjusted_close_rejected(self):
        with pytest.raises(ValidationError, match="[Aa]djusted"):
            OHLCVRecord(**_valid_record_kwargs(adjusted_close=-10.0))

    def test_none_adjusted_close_accepted(self):
        record = OHLCVRecord(**_valid_record_kwargs(adjusted_close=None))
        assert record.adjusted_close is None


class TestValidationFutureDates:
    """Requirement 5.6: trading_date and data_as_of cannot be in the future."""

    def test_future_trading_date_rejected(self):
        future = date.today() + timedelta(days=30)
        with pytest.raises(ValidationError, match="future"):
            OHLCVRecord(**_valid_record_kwargs(trading_date=future))

    def test_future_data_as_of_rejected(self):
        future = date.today() + timedelta(days=30)
        with pytest.raises(ValidationError, match="future"):
            OHLCVRecord(**_valid_record_kwargs(data_as_of=future))

    def test_today_trading_date_accepted(self):
        # The validator's clock is UTC; local date.today() reads as "future"
        # for a few hours after local midnight on UTC+ machines.
        today = datetime.now(timezone.utc).date()
        record = OHLCVRecord(**_valid_record_kwargs(
            trading_date=today, data_as_of=today
        ))
        assert record.trading_date == today


class TestValidationSymbol:
    """Requirement 5.7: symbol must be uppercase ASCII, max 10 chars."""

    def test_lowercase_symbol_rejected(self):
        with pytest.raises(ValidationError, match="[Ss]ymbol"):
            OHLCVRecord(**_valid_record_kwargs(symbol="aapl"))

    def test_mixed_case_symbol_rejected(self):
        with pytest.raises(ValidationError, match="[Ss]ymbol"):
            OHLCVRecord(**_valid_record_kwargs(symbol="Aapl"))

    def test_symbol_with_digits_rejected(self):
        with pytest.raises(ValidationError, match="[Ss]ymbol"):
            OHLCVRecord(**_valid_record_kwargs(symbol="AAPL1"))

    def test_symbol_with_special_chars_rejected(self):
        with pytest.raises(ValidationError, match="[Ss]ymbol"):
            OHLCVRecord(**_valid_record_kwargs(symbol="AA-PL"))

    def test_symbol_too_long_rejected(self):
        with pytest.raises(ValidationError, match="[Ss]ymbol"):
            OHLCVRecord(**_valid_record_kwargs(symbol="ABCDEFGHIJK"))  # 11 chars

    def test_empty_symbol_rejected(self):
        with pytest.raises(ValidationError, match="[Ss]ymbol"):
            OHLCVRecord(**_valid_record_kwargs(symbol=""))

    def test_ten_char_symbol_accepted(self):
        record = OHLCVRecord(**_valid_record_kwargs(symbol="ABCDEFGHIJ"))  # 10 chars
        assert record.symbol == "ABCDEFGHIJ"

    def test_single_char_symbol_accepted(self):
        record = OHLCVRecord(**_valid_record_kwargs(symbol="A"))
        assert record.symbol == "A"


class TestValidationRawPayloadHash:
    """raw_payload_hash must be non-empty."""

    def test_empty_raw_payload_hash_rejected(self):
        with pytest.raises(ValidationError, match="raw_payload_hash"):
            OHLCVRecord(**_valid_record_kwargs(raw_payload_hash=""))

    def test_whitespace_only_raw_payload_hash_rejected(self):
        with pytest.raises(ValidationError, match="raw_payload_hash"):
            OHLCVRecord(**_valid_record_kwargs(raw_payload_hash="   "))


# ===========================================================================
# 3. Enum serialization/deserialization
# ===========================================================================


class TestEnumSerialization:
    """Test enum serialization (to string) and deserialization (from string)."""

    # --- QualityStatus ---

    def test_quality_status_to_string(self):
        """Enum .value gives the serialized string form."""
        assert QualityStatus.USABLE.value == "usable"
        assert QualityStatus.PARTIAL.value == "partial"
        assert QualityStatus.STALE.value == "stale"
        assert QualityStatus.MISSING.value == "missing"
        assert QualityStatus.CONTRADICTORY.value == "contradictory"
        assert QualityStatus.INSUFFICIENT_DATA.value == "insufficient_data"

    def test_quality_status_from_string(self):
        assert QualityStatus("usable") == QualityStatus.USABLE
        assert QualityStatus("partial") == QualityStatus.PARTIAL
        assert QualityStatus("stale") == QualityStatus.STALE
        assert QualityStatus("missing") == QualityStatus.MISSING
        assert QualityStatus("contradictory") == QualityStatus.CONTRADICTORY
        assert QualityStatus("insufficient_data") == QualityStatus.INSUFFICIENT_DATA

    def test_quality_status_is_str_subclass(self):
        """QualityStatus inherits from str, so it can be compared to its value."""
        for status in QualityStatus:
            assert isinstance(status, str)
            assert status == status.value

    def test_quality_status_invalid_value_raises(self):
        with pytest.raises(ValueError):
            QualityStatus("invalid_status")

    # --- PriceAdjustment ---

    def test_price_adjustment_to_string(self):
        """Enum .value gives the serialized string form."""
        assert PriceAdjustment.RAW.value == "raw"
        assert PriceAdjustment.SPLIT_ADJUSTED.value == "split_adjusted"
        assert PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED.value == "split_dividend_adjusted"
        assert PriceAdjustment.UNKNOWN.value == "unknown"

    def test_price_adjustment_from_string(self):
        assert PriceAdjustment("raw") == PriceAdjustment.RAW
        assert PriceAdjustment("split_adjusted") == PriceAdjustment.SPLIT_ADJUSTED
        assert PriceAdjustment("split_dividend_adjusted") == PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED
        assert PriceAdjustment("unknown") == PriceAdjustment.UNKNOWN

    def test_price_adjustment_is_str_subclass(self):
        """PriceAdjustment inherits from str, so it can be compared to its value."""
        for adj in PriceAdjustment:
            assert isinstance(adj, str)
            assert adj == adj.value

    def test_price_adjustment_invalid_value_raises(self):
        with pytest.raises(ValueError):
            PriceAdjustment("not_a_real_adjustment")

    # --- Enum in Pydantic model serialization ---

    def test_enum_in_model_json_serialization(self):
        record = OHLCVRecord(**_valid_record_kwargs())
        data = record.model_dump()
        assert data["price_adjustment"] == "split_dividend_adjusted"
        assert data["quality_status"] == "usable"

    def test_enum_in_model_json_deserialization(self):
        """Pydantic should accept string values for enum fields."""
        kwargs = _valid_record_kwargs()
        kwargs["price_adjustment"] = "raw"
        kwargs["quality_status"] = "stale"
        record = OHLCVRecord(**kwargs)
        assert record.price_adjustment == PriceAdjustment.RAW
        assert record.quality_status == QualityStatus.STALE


# ===========================================================================
# 4. ProviderCapabilities construction
# ===========================================================================


class TestProviderCapabilities:
    """Test ProviderCapabilities model construction and defaults."""

    def test_full_construction(self):
        caps = ProviderCapabilities(
            source_name="polygon",
            asset_classes=["equity", "etf"],
            supports_daily_ohlcv=True,
            supports_adjusted_prices=True,
            supports_corporate_actions=True,
            min_history_years_free=2.0,
            rate_limit_per_minute=5,
            requires_api_key=True,
            license_note="Polygon Basic free tier",
            experimental=False,
        )
        assert caps.source_name == "polygon"
        assert caps.asset_classes == ["equity", "etf"]
        assert caps.supports_daily_ohlcv is True
        assert caps.supports_adjusted_prices is True
        assert caps.supports_corporate_actions is True
        assert caps.min_history_years_free == 2.0
        assert caps.rate_limit_per_minute == 5
        assert caps.requires_api_key is True
        assert caps.license_note == "Polygon Basic free tier"
        assert caps.experimental is False

    def test_optional_fields_default_none(self):
        caps = ProviderCapabilities(
            source_name="csv_fixture",
            asset_classes=["equity"],
            supports_daily_ohlcv=True,
            supports_adjusted_prices=False,
            supports_corporate_actions=False,
            requires_api_key=False,
            license_note="Local fixture data",
        )
        assert caps.min_history_years_free is None
        assert caps.rate_limit_per_minute is None
        assert caps.experimental is False

    def test_experimental_flag(self):
        caps = ProviderCapabilities(
            source_name="yfinance",
            asset_classes=["equity", "etf"],
            supports_daily_ohlcv=True,
            supports_adjusted_prices=True,
            supports_corporate_actions=False,
            requires_api_key=False,
            license_note="Unofficial, no SLA",
            experimental=True,
        )
        assert caps.experimental is True


# ===========================================================================
# 5. ProviderFetchResult construction
# ===========================================================================


class TestProviderFetchResult:
    """Test ProviderFetchResult model construction and defaults."""

    def test_full_construction_with_records(self):
        record = OHLCVRecord(**_valid_record_kwargs())
        result = ProviderFetchResult(
            symbol="MSFT",
            provider="polygon",
            request_url="https://api.polygon.io/v2/aggs/ticker/MSFT/range/1/day/2024-01-01/2024-03-15",
            request_params={"adjusted": "true", "limit": "5000"},
            retrieved_at=datetime(2024, 3, 15, 21, 0, 0, tzinfo=timezone.utc),
            raw_payload='{"results": [...]}',
            content_hash="sha256_abc123",
            records=[record],
            provider_warnings=["Rate limit approaching"],
            rate_limit_state={"remaining": 3, "reset_at": "2024-03-15T21:01:00Z"},
        )
        assert result.symbol == "MSFT"
        assert result.provider == "polygon"
        assert len(result.records) == 1
        assert result.provider_warnings == ["Rate limit approaching"]
        assert result.rate_limit_state["remaining"] == 3

    def test_empty_result_defaults(self):
        result = ProviderFetchResult(
            symbol="AAPL",
            provider="polygon",
            request_url="https://api.polygon.io/v2/aggs",
            retrieved_at=datetime(2024, 3, 15, 21, 0, 0, tzinfo=timezone.utc),
            raw_payload="{}",
            content_hash="sha256_empty",
        )
        assert result.records == []
        assert result.provider_warnings == []
        assert result.rate_limit_state == {}
        assert result.request_params == {}


# ===========================================================================
# 6. DataQualityReport construction
# ===========================================================================


class TestDataQualityReport:
    """Test DataQualityReport model construction."""

    def test_full_construction(self):
        report = DataQualityReport(
            report_id="rpt-uuid-001",
            run_id="run-uuid-001",
            symbol="SPY",
            source_name="polygon",
            generated_at=datetime(2024, 3, 15, 22, 0, 0, tzinfo=timezone.utc),
            requested_start_date=date(2023, 3, 15),
            requested_end_date=date(2024, 3, 15),
            first_available_date=date(2023, 3, 16),
            last_available_date=date(2024, 3, 14),
            expected_sessions=252,
            valid_sessions=250,
            missing_sessions=[date(2024, 1, 2), date(2024, 2, 19)],
            rejected_records=3,
            quality_status=QualityStatus.USABLE,
            confidence_cap=1.0,
            issues_json={"duplicate_dates": [], "non_monotonic": False},
        )
        assert report.report_id == "rpt-uuid-001"
        assert report.symbol == "SPY"
        assert report.expected_sessions == 252
        assert report.valid_sessions == 250
        assert len(report.missing_sessions) == 2
        assert report.rejected_records == 3
        assert report.quality_status == QualityStatus.USABLE
        assert report.confidence_cap == 1.0

    def test_missing_status_zero_confidence(self):
        report = DataQualityReport(
            report_id="rpt-002",
            run_id="run-002",
            symbol="NVDA",
            source_name="polygon",
            generated_at=datetime(2024, 3, 15, 22, 0, 0, tzinfo=timezone.utc),
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 3, 15),
            expected_sessions=50,
            valid_sessions=0,
            rejected_records=0,
            quality_status=QualityStatus.MISSING,
            confidence_cap=0.0,
        )
        assert report.quality_status == QualityStatus.MISSING
        assert report.confidence_cap == 0.0

    def test_confidence_cap_bounds(self):
        """confidence_cap must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            DataQualityReport(
                report_id="rpt-003",
                run_id="run-003",
                symbol="AAPL",
                source_name="polygon",
                generated_at=datetime(2024, 3, 15, 22, 0, 0, tzinfo=timezone.utc),
                requested_start_date=date(2024, 1, 1),
                requested_end_date=date(2024, 3, 15),
                expected_sessions=50,
                valid_sessions=50,
                rejected_records=0,
                quality_status=QualityStatus.USABLE,
                confidence_cap=1.5,  # Invalid: > 1.0
            )


# ===========================================================================
# 7. DataEvidencePacket construction and JSON round-trip
# ===========================================================================


class TestDataEvidencePacket:
    """Test DataEvidencePacket construction and JSON serialization."""

    def _make_packet(self, **overrides) -> DataEvidencePacket:
        base = {
            "symbol": "GOOGL",
            "as_of": date(2024, 3, 15),
            "source": "polygon",
            "data_window": (date(2023, 3, 15), date(2024, 3, 15)),
            "latest_price_date": date(2024, 3, 14),
            "price_adjustment": PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
            "rows_available": 252,
            "missing_sessions": [date(2024, 1, 15)],
            "quality_status": QualityStatus.USABLE,
            "confidence_cap": 1.0,
            "benchmark_symbol": "VOO",
            "benchmark_available": True,
            "evidence_refs": [
                EvidenceRef(
                    table="daily_ohlcv",
                    key="GOOGL|2024-03-14|polygon|split_dividend_adjusted",
                    source="polygon",
                    retrieved_at=datetime(2024, 3, 15, 20, 0, 0, tzinfo=timezone.utc),
                    data_as_of=date(2024, 3, 14),
                )
            ],
        }
        base.update(overrides)
        return DataEvidencePacket(**base)

    def test_full_construction(self):
        packet = self._make_packet()
        assert packet.symbol == "GOOGL"
        assert packet.as_of == date(2024, 3, 15)
        assert packet.source == "polygon"
        assert packet.data_window == (date(2023, 3, 15), date(2024, 3, 15))
        assert packet.latest_price_date == date(2024, 3, 14)
        assert packet.rows_available == 252
        assert len(packet.missing_sessions) == 1
        assert packet.quality_status == QualityStatus.USABLE
        assert packet.confidence_cap == 1.0
        assert packet.benchmark_symbol == "VOO"
        assert packet.benchmark_available is True
        assert len(packet.evidence_refs) == 1

    def test_json_round_trip(self):
        """Serialize to JSON and deserialize back, verify equivalence."""
        packet = self._make_packet()
        json_str = packet.model_dump_json()

        restored = DataEvidencePacket.model_validate_json(json_str)

        assert restored.symbol == packet.symbol
        assert restored.as_of == packet.as_of
        assert restored.source == packet.source
        assert restored.data_window == packet.data_window
        assert restored.latest_price_date == packet.latest_price_date
        assert restored.price_adjustment == packet.price_adjustment
        assert restored.rows_available == packet.rows_available
        assert restored.missing_sessions == packet.missing_sessions
        assert restored.quality_status == packet.quality_status
        assert restored.confidence_cap == packet.confidence_cap
        assert restored.benchmark_symbol == packet.benchmark_symbol
        assert restored.benchmark_available == packet.benchmark_available
        assert len(restored.evidence_refs) == len(packet.evidence_refs)
        assert restored.evidence_refs[0].table == packet.evidence_refs[0].table
        assert restored.evidence_refs[0].key == packet.evidence_refs[0].key

    def test_json_round_trip_with_empty_refs(self):
        packet = self._make_packet(evidence_refs=[], missing_sessions=[])
        json_str = packet.model_dump_json()
        restored = DataEvidencePacket.model_validate_json(json_str)
        assert restored.evidence_refs == []
        assert restored.missing_sessions == []

    def test_confidence_cap_bounds(self):
        """confidence_cap must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            self._make_packet(confidence_cap=1.1)

        with pytest.raises(ValidationError):
            self._make_packet(confidence_cap=-0.1)

    def test_stale_quality_status(self):
        packet = self._make_packet(
            quality_status=QualityStatus.STALE,
            confidence_cap=0.5,
        )
        assert packet.quality_status == QualityStatus.STALE
        assert packet.confidence_cap == 0.5


# ===========================================================================
# 8. InsufficientDataError construction and attributes
# ===========================================================================


class TestInsufficientDataError:
    """Test InsufficientDataError exception class."""

    def test_construction_and_attributes(self):
        err = InsufficientDataError(symbol="NVDA", rows_available=25, rows_requested=50)
        assert err.symbol == "NVDA"
        assert err.rows_available == 25
        assert err.rows_requested == 50

    def test_message_contains_details(self):
        err = InsufficientDataError(symbol="AMZN", rows_available=10, rows_requested=200)
        msg = str(err)
        assert "AMZN" in msg
        assert "10" in msg
        assert "200" in msg

    def test_is_exception_subclass(self):
        assert issubclass(InsufficientDataError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(InsufficientDataError) as exc_info:
            raise InsufficientDataError("META", 5, 50)
        assert exc_info.value.symbol == "META"
        assert exc_info.value.rows_available == 5
        assert exc_info.value.rows_requested == 50
