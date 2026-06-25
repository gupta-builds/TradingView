"""Quick validation tests for models.py to verify task 1.2 implementation."""

import sys
sys.path.insert(0, "src")

from datetime import date, datetime, timezone, timedelta
import pytest
from pydantic import ValidationError

from research_data.models import (
    QualityStatus,
    PriceAdjustment,
    OHLCVRecord,
    ProviderCapabilities,
    ProviderFetchResult,
    DataQualityReport,
    DataEvidencePacket,
    EvidenceRef,
    InsufficientDataError,
)


def _valid_record(**overrides) -> dict:
    """Return a valid OHLCVRecord dict with optional overrides."""
    base = {
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
    base.update(overrides)
    return base


class TestEnumerations:
    def test_quality_status_values(self):
        assert QualityStatus.USABLE.value == "usable"
        assert QualityStatus.PARTIAL.value == "partial"
        assert QualityStatus.STALE.value == "stale"
        assert QualityStatus.MISSING.value == "missing"
        assert QualityStatus.CONTRADICTORY.value == "contradictory"
        assert QualityStatus.INSUFFICIENT_DATA.value == "insufficient_data"

    def test_price_adjustment_values(self):
        assert PriceAdjustment.RAW.value == "raw"
        assert PriceAdjustment.SPLIT_ADJUSTED.value == "split_adjusted"
        assert PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED.value == "split_dividend_adjusted"
        assert PriceAdjustment.UNKNOWN.value == "unknown"

    def test_enum_is_str(self):
        assert isinstance(QualityStatus.USABLE, str)
        assert isinstance(PriceAdjustment.RAW, str)


class TestOHLCVRecordValid:
    def test_valid_record_construction(self):
        record = OHLCVRecord(**_valid_record())
        assert record.symbol == "AAPL"
        assert record.open == 150.0
        assert record.quality_status == QualityStatus.USABLE

    def test_valid_record_with_adjusted_close(self):
        record = OHLCVRecord(**_valid_record(adjusted_close=152.5))
        assert record.adjusted_close == 152.5

    def test_valid_record_with_zero_volume(self):
        record = OHLCVRecord(**_valid_record(volume=0))
        assert record.volume == 0


class TestOHLCVRecordValidation:
    def test_reject_non_positive_open(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(open=0.0, high=155.0, low=0.0, close=0.0))

    def test_reject_negative_open(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(open=-1.0))

    def test_reject_non_positive_close(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(close=0.0))

    def test_reject_high_less_than_open(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(open=150.0, high=149.0, low=148.0, close=148.5))

    def test_reject_high_less_than_close(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(open=150.0, high=151.0, low=148.0, close=152.0))

    def test_reject_low_greater_than_open(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(open=150.0, high=155.0, low=151.0, close=153.0))

    def test_reject_low_greater_than_close(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(open=150.0, high=155.0, low=152.0, close=151.0))

    def test_reject_negative_volume(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(volume=-1))

    def test_reject_non_positive_adjusted_close(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(adjusted_close=0.0))

    def test_reject_negative_adjusted_close(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(adjusted_close=-5.0))

    def test_reject_future_trading_date(self):
        future = date.today() + timedelta(days=10)
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(trading_date=future))

    def test_reject_future_data_as_of(self):
        future = date.today() + timedelta(days=10)
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(data_as_of=future))

    def test_reject_lowercase_symbol(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(symbol="aapl"))

    def test_reject_mixed_case_symbol(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(symbol="Aapl"))

    def test_reject_symbol_with_numbers(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(symbol="AAPL1"))

    def test_reject_symbol_too_long(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(symbol="ABCDEFGHIJK"))

    def test_reject_empty_symbol(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(symbol=""))

    def test_reject_empty_raw_payload_hash(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(raw_payload_hash=""))

    def test_reject_whitespace_raw_payload_hash(self):
        with pytest.raises(ValidationError):
            OHLCVRecord(**_valid_record(raw_payload_hash="   "))


class TestInsufficientDataError:
    def test_construction(self):
        err = InsufficientDataError("AAPL", 30, 50)
        assert err.symbol == "AAPL"
        assert err.rows_available == 30
        assert err.rows_requested == 50
        assert "AAPL" in str(err)
        assert "30" in str(err)
        assert "50" in str(err)

    def test_is_exception(self):
        assert issubclass(InsufficientDataError, Exception)


class TestProviderCapabilities:
    def test_construction(self):
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
        )
        assert caps.source_name == "polygon"
        assert caps.experimental is False


class TestProviderFetchResult:
    def test_construction(self):
        result = ProviderFetchResult(
            symbol="AAPL",
            provider="polygon",
            request_url="https://api.polygon.io/v2/aggs",
            retrieved_at=datetime(2024, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
            raw_payload='{"results": []}',
            content_hash="sha256abc",
        )
        assert result.symbol == "AAPL"
        assert result.records == []
        assert result.provider_warnings == []


class TestDataQualityReport:
    def test_construction(self):
        report = DataQualityReport(
            report_id="rpt-001",
            run_id="run-001",
            symbol="AAPL",
            source_name="polygon",
            generated_at=datetime(2024, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 6, 15),
            expected_sessions=120,
            valid_sessions=118,
            rejected_records=2,
            quality_status=QualityStatus.USABLE,
            confidence_cap=1.0,
        )
        assert report.quality_status == QualityStatus.USABLE
        assert report.confidence_cap == 1.0


class TestEvidenceModels:
    def test_evidence_ref_construction(self):
        ref = EvidenceRef(
            table="daily_ohlcv",
            key="AAPL|2024-06-15|polygon|split_dividend_adjusted",
            source="polygon",
            retrieved_at=datetime(2024, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
            data_as_of=date(2024, 6, 15),
        )
        assert ref.table == "daily_ohlcv"

    def test_evidence_packet_construction(self):
        packet = DataEvidencePacket(
            symbol="AAPL",
            as_of=date(2024, 6, 15),
            source="polygon",
            data_window=(date(2024, 1, 1), date(2024, 6, 15)),
            latest_price_date=date(2024, 6, 14),
            price_adjustment=PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
            rows_available=118,
            quality_status=QualityStatus.USABLE,
            confidence_cap=1.0,
            benchmark_symbol="VOO",
            benchmark_available=True,
            evidence_refs=[
                EvidenceRef(
                    table="daily_ohlcv",
                    key="AAPL|2024-06-15|polygon|split_dividend_adjusted",
                    source="polygon",
                    retrieved_at=datetime(2024, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
                    data_as_of=date(2024, 6, 15),
                )
            ],
        )
        assert packet.symbol == "AAPL"
        assert len(packet.evidence_refs) == 1

    def test_evidence_packet_json_serialization(self):
        packet = DataEvidencePacket(
            symbol="AAPL",
            as_of=date(2024, 6, 15),
            source="polygon",
            data_window=(date(2024, 1, 1), date(2024, 6, 15)),
            price_adjustment=PriceAdjustment.RAW,
            rows_available=50,
            quality_status=QualityStatus.PARTIAL,
            confidence_cap=0.7,
            benchmark_symbol="VOO",
            benchmark_available=True,
        )
        json_str = packet.model_dump_json()
        assert "AAPL" in json_str
        # Round-trip
        restored = DataEvidencePacket.model_validate_json(json_str)
        assert restored.symbol == packet.symbol
        assert restored.confidence_cap == packet.confidence_cap
