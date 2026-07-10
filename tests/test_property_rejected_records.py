"""Property test for rejected records counting (Property 17).

Property 17: Rejected Records Counted in Quality Report
For any ingestion batch containing N records that fail validation, the
resulting quality report SHALL have rejected_records equal to N.

**Validates: Requirements 5.9, 13.4**
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, "src")

from research_data.models import OHLCVRecord, PriceAdjustment, QualityStatus
from research_data.quality import DataQualityAuditor


def _fake_calendar(latest: date) -> MagicMock:
    cal = MagicMock()
    cal.get_trading_sessions.return_value = []
    cal.get_missing_sessions.return_value = []
    cal.get_latest_expected_session.return_value = latest
    return cal


def _record(d: date) -> OHLCVRecord:
    return OHLCVRecord(
        symbol="MSFT",
        asset_type="equity",
        exchange="NASDAQ",
        trading_date=d,
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        adjusted_close=105.0,
        volume=1_000_000,
        split_factor=1.0,
        dividend_cash=0.0,
        price_adjustment=PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
        currency="USD",
        source="csv_fixture",
        retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        data_as_of=d,
        raw_payload_hash="hash17",
        quality_status=QualityStatus.USABLE,
    )


class TestProperty17RejectedRecordsCounted:
    """Property 17: Rejected Records Counted in Quality Report."""

    @given(n_rejected=st.integers(min_value=0, max_value=200))
    @settings(max_examples=100, deadline=None)
    def test_rejected_records_equals_n(self, n_rejected: int):
        """rejected_records on the quality report SHALL equal N."""
        base = date(2024, 3, 1)
        # Include a few valid rows so status is not always MISSING
        records = [_record(base + timedelta(days=i)) for i in range(5)]
        cal = _fake_calendar(latest=records[-1].trading_date)
        auditor = DataQualityAuditor(calendar=cal)
        report = auditor.audit_symbol(
            symbol="MSFT",
            records=records,
            exchange="NASDAQ",
            start_date=base,
            end_date=base + timedelta(days=30),
            run_id="run-17",
            source_name="csv_fixture",
            rejected_records=n_rejected,
            indicator_window=200,
        )
        assert report.rejected_records == n_rejected

    @given(n_rejected=st.integers(min_value=1, max_value=50))
    @settings(max_examples=50, deadline=None)
    def test_rejected_preserved_when_missing(self, n_rejected: int):
        """Even with zero valid rows, rejected_records is preserved."""
        cal = _fake_calendar(latest=date(2024, 6, 1))
        auditor = DataQualityAuditor(calendar=cal)
        report = auditor.audit_symbol(
            symbol="MSFT",
            records=[],
            exchange="NASDAQ",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 1),
            run_id="run-17b",
            source_name="csv_fixture",
            rejected_records=n_rejected,
        )
        assert report.quality_status == QualityStatus.MISSING
        assert report.rejected_records == n_rejected
