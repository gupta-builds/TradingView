"""Unit tests for DataQualityAuditor (Task 7.4).

Requirements: 7.1–7.10
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, "src")

from research_data.models import (
    OHLCVRecord,
    PriceAdjustment,
    QualityStatus,
)
from research_data.quality import DataQualityAuditor


def _cal(
    *,
    expected: list[date] | None = None,
    missing: list[date] | None = None,
    latest: date = date(2024, 6, 3),
) -> MagicMock:
    c = MagicMock()
    c.get_trading_sessions.return_value = expected or []
    c.get_missing_sessions.return_value = missing or []
    c.get_latest_expected_session.return_value = latest
    return c


def _rec(
    d: date,
    *,
    high: float = 110.0,
    low: float = 90.0,
    open_: float = 100.0,
    close: float = 105.0,
    adj: PriceAdjustment = PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
    construct: bool = False,
) -> OHLCVRecord:
    kwargs = dict(
        symbol="AAPL",
        asset_type="equity",
        exchange="NASDAQ",
        trading_date=d,
        open=open_,
        high=high,
        low=low,
        close=close,
        adjusted_close=close,
        volume=1_000_000,
        split_factor=1.0,
        dividend_cash=0.0,
        price_adjustment=adj,
        currency="USD",
        source="polygon",
        retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        data_as_of=d,
        raw_payload_hash="unit_hash",
        quality_status=QualityStatus.USABLE,
    )
    if construct:
        return OHLCVRecord.model_construct(**kwargs)
    return OHLCVRecord(**kwargs)


def _dates(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


class TestDataQualityAuditorUnit:
    def test_missing_when_zero_rows(self):
        auditor = DataQualityAuditor(calendar=_cal())
        report = auditor.audit_symbol(
            "AAPL", [], "NASDAQ", date(2024, 1, 1), date(2024, 6, 1),
            "run1", "polygon",
        )
        assert report.quality_status == QualityStatus.MISSING
        assert report.confidence_cap == 0.0
        assert report.valid_sessions == 0

    def test_stale_when_latest_bar_old(self):
        dates = _dates(10)
        records = [_rec(d) for d in dates]
        auditor = DataQualityAuditor(
            calendar=_cal(expected=dates, latest=dates[-1] + timedelta(days=7))
        )
        report = auditor.audit_symbol(
            "AAPL", records, "NASDAQ", dates[0], dates[-1], "run1", "polygon",
        )
        assert report.quality_status == QualityStatus.STALE
        assert report.confidence_cap <= 0.5
        assert "stale_data" in report.issues_json

    def test_contradictory_for_impossible_ohlc(self):
        d = date(2024, 3, 1)
        records = [
            _rec(d, high=80.0, low=100.0, open_=90.0, close=90.0, construct=True)
        ]
        auditor = DataQualityAuditor(calendar=_cal(expected=[d], latest=d))
        report = auditor.audit_symbol(
            "AAPL", records, "NASDAQ", d, d, "run1", "polygon",
        )
        assert report.quality_status == QualityStatus.CONTRADICTORY
        assert report.confidence_cap <= 0.3
        assert "contradictory_ohlc" in report.issues_json

    def test_insufficient_data_for_short_history(self):
        dates = _dates(20)
        records = [_rec(d) for d in dates]
        auditor = DataQualityAuditor(calendar=_cal(expected=dates, latest=dates[-1]))
        report = auditor.audit_symbol(
            "AAPL", records, "NASDAQ", dates[0], dates[-1], "run1", "polygon",
            indicator_window=200,
        )
        assert report.quality_status == QualityStatus.INSUFFICIENT_DATA
        assert report.confidence_cap <= 0.4

    def test_partial_for_moderate_history(self):
        dates = _dates(60)
        records = [_rec(d) for d in dates]
        auditor = DataQualityAuditor(calendar=_cal(expected=dates, latest=dates[-1]))
        report = auditor.audit_symbol(
            "AAPL", records, "NASDAQ", dates[0], dates[-1], "run1", "polygon",
            indicator_window=200,
        )
        assert report.quality_status == QualityStatus.PARTIAL
        assert report.confidence_cap <= 0.7

    def test_usable_for_complete_data(self):
        dates = _dates(200)
        records = [_rec(d) for d in dates]
        auditor = DataQualityAuditor(calendar=_cal(expected=dates, latest=dates[-1]))
        report = auditor.audit_symbol(
            "AAPL", records, "NASDAQ", dates[0], dates[-1], "run1", "polygon",
            indicator_window=200,
        )
        assert report.quality_status == QualityStatus.USABLE
        assert report.confidence_cap == 1.0

    def test_precedence_contradictory_over_stale(self):
        dates = _dates(5)
        records = [
            _rec(d, high=50.0, low=100.0, open_=75.0, close=75.0, construct=True)
            for d in dates
        ]
        auditor = DataQualityAuditor(
            calendar=_cal(expected=dates, latest=dates[-1] + timedelta(days=30))
        )
        report = auditor.audit_symbol(
            "AAPL", records, "NASDAQ", dates[0], dates[-1], "run1", "polygon",
        )
        assert report.quality_status == QualityStatus.CONTRADICTORY

    def test_precedence_stale_over_insufficient(self):
        dates = _dates(10)
        records = [_rec(d) for d in dates]
        auditor = DataQualityAuditor(
            calendar=_cal(expected=dates, latest=dates[-1] + timedelta(days=14))
        )
        report = auditor.audit_symbol(
            "AAPL", records, "NASDAQ", dates[0], dates[-1], "run1", "polygon",
            indicator_window=200,
        )
        assert report.quality_status == QualityStatus.STALE

    def test_cross_provider_disagreement(self):
        d = date(2024, 3, 15)
        primary = [_rec(d, close=100.0, high=110.0, low=90.0, open_=100.0)]
        secondary = [
            _rec(d, close=110.0, high=120.0, low=100.0, open_=110.0).model_copy(
                update={"source": "tiingo"}
            )
        ]
        auditor = DataQualityAuditor(calendar=_cal(latest=d))
        disagreements = auditor.detect_cross_provider_disagreement(primary, secondary)
        assert len(disagreements) >= 1
        assert any(item["field"] == "close" for item in disagreements)

    def test_duplicate_and_unknown_adjustment_recorded(self):
        d = date(2024, 4, 1)
        records = [_rec(d), _rec(d, adj=PriceAdjustment.UNKNOWN)]
        auditor = DataQualityAuditor(calendar=_cal(expected=[d], latest=d))
        report = auditor.audit_symbol(
            "AAPL", records, "NASDAQ", d, d, "run1", "polygon",
            indicator_window=1,
        )
        assert "duplicate_dates" in report.issues_json
        assert "unknown_price_adjustment" in report.issues_json
