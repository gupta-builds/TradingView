"""Property test for quality status classification (Property 5).

Property 5: Quality Status Classification Correctness
For any symbol and ingestion result, the Data_Quality_Auditor SHALL assign
exactly one QualityStatus consistent with precedence:
MISSING > CONTRADICTORY > STALE > INSUFFICIENT_DATA > PARTIAL > USABLE.

**Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, "src")

from research_data.models import (
    OHLCVRecord,
    PriceAdjustment,
    QualityStatus,
)
from research_data.quality import DataQualityAuditor


def _fake_calendar(
    *,
    expected_sessions: list[date] | None = None,
    missing_sessions: list[date] | None = None,
    latest_expected: date | None = None,
) -> MagicMock:
    cal = MagicMock()
    sessions = expected_sessions or []
    cal.get_trading_sessions.return_value = sessions
    cal.get_missing_sessions.return_value = missing_sessions or []
    cal.get_latest_expected_session.return_value = (
        latest_expected or (sessions[-1] if sessions else date(2024, 6, 1))
    )
    return cal


def _make_record(
    trading_date: date,
    *,
    high: float = 110.0,
    low: float = 90.0,
    open_: float = 100.0,
    close: float = 105.0,
    price_adjustment: PriceAdjustment = PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
    construct: bool = False,
) -> OHLCVRecord:
    kwargs: dict[str, Any] = {
        "symbol": "TEST",
        "asset_type": "equity",
        "exchange": "NYSE",
        "trading_date": trading_date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "adjusted_close": close,
        "volume": 1_000_000,
        "split_factor": 1.0,
        "dividend_cash": 0.0,
        "price_adjustment": price_adjustment,
        "currency": "USD",
        "source": "csv_fixture",
        "source_record_id": None,
        "retrieved_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "data_as_of": trading_date,
        "raw_payload_hash": "abc123hash",
        "quality_status": QualityStatus.USABLE,
    }
    if construct:
        return OHLCVRecord.model_construct(**kwargs)
    return OHLCVRecord(**kwargs)


@st.composite
def session_counts(draw):
    """Generate (n_sessions, indicator_window) pairs covering all status bands."""
    kind = draw(st.sampled_from(["missing", "insufficient", "partial", "usable"]))
    if kind == "missing":
        return 0, 200
    if kind == "insufficient":
        n = draw(st.integers(min_value=1, max_value=49))
        return n, 200
    if kind == "partial":
        n = draw(st.integers(min_value=50, max_value=199))
        return n, 200
    n = draw(st.integers(min_value=200, max_value=220))
    return n, 200


class TestProperty5QualityStatusClassification:
    """Property 5: Quality Status Classification Correctness."""

    @given(n_and_window=session_counts())
    @settings(max_examples=80, deadline=None)
    def test_session_count_classification(self, n_and_window):
        """Session-count bands map to INSUFFICIENT / PARTIAL / USABLE / MISSING."""
        n, window = n_and_window
        base = date(2024, 1, 2)
        records = [
            _make_record(base + timedelta(days=i))
            for i in range(n)
        ]
        # Keep last_available == latest_expected so STALE does not fire
        last = records[-1].trading_date if records else base
        cal = _fake_calendar(
            expected_sessions=[r.trading_date for r in records] or [base],
            latest_expected=last,
        )
        auditor = DataQualityAuditor(calendar=cal)
        report = auditor.audit_symbol(
            symbol="TEST",
            records=records,
            exchange="NYSE",
            start_date=base,
            end_date=last,
            run_id="run-prop5",
            source_name="csv_fixture",
            indicator_window=window,
        )

        if n == 0:
            assert report.quality_status == QualityStatus.MISSING
            assert report.confidence_cap == 0.0
        elif n < 50 and n < window:
            assert report.quality_status == QualityStatus.INSUFFICIENT_DATA
            assert report.confidence_cap <= 0.4
        elif n >= 50 and n < window:
            assert report.quality_status == QualityStatus.PARTIAL
            assert report.confidence_cap <= 0.7
        else:
            assert report.quality_status == QualityStatus.USABLE
            assert report.confidence_cap == 1.0

    @given(n=st.integers(min_value=1, max_value=30))
    @settings(max_examples=40, deadline=None)
    def test_stale_when_last_bar_before_latest_expected(self, n):
        """STALE when latest bar predates latest expected session."""
        base = date(2024, 1, 2)
        records = [_make_record(base + timedelta(days=i)) for i in range(n)]
        last = records[-1].trading_date
        cal = _fake_calendar(
            expected_sessions=[r.trading_date for r in records],
            latest_expected=last + timedelta(days=5),
        )
        auditor = DataQualityAuditor(calendar=cal)
        report = auditor.audit_symbol(
            symbol="TEST",
            records=records,
            exchange="NYSE",
            start_date=base,
            end_date=last,
            run_id="run-stale",
            source_name="csv_fixture",
            indicator_window=200,
        )
        # Precedence: not MISSING (n>0), not CONTRADICTORY → STALE before INSUFFICIENT
        assert report.quality_status == QualityStatus.STALE
        assert report.confidence_cap <= 0.5

    @given(n=st.integers(min_value=1, max_value=20))
    @settings(max_examples=30, deadline=None)
    def test_contradictory_precedes_stale_and_insufficient(self, n):
        """CONTRADICTORY outranks STALE and INSUFFICIENT_DATA."""
        base = date(2024, 1, 2)
        records = [
            _make_record(
                base + timedelta(days=i),
                high=80.0,
                low=100.0,
                open_=90.0,
                close=90.0,
                construct=True,
            )
            for i in range(n)
        ]
        last = records[-1].trading_date
        cal = _fake_calendar(
            expected_sessions=[r.trading_date for r in records],
            latest_expected=last + timedelta(days=10),  # would be STALE
        )
        auditor = DataQualityAuditor(calendar=cal)
        report = auditor.audit_symbol(
            symbol="TEST",
            records=records,
            exchange="NYSE",
            start_date=base,
            end_date=last,
            run_id="run-contra",
            source_name="csv_fixture",
            indicator_window=200,
        )
        assert report.quality_status == QualityStatus.CONTRADICTORY
        assert report.confidence_cap <= 0.3
