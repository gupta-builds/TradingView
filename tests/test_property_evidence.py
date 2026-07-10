"""Property tests for evidence packet completeness and serialization.

Properties 15, 16 — Validates Requirements 12.1–12.4
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, "src")

from research_data.evidence import EvidenceConstructionError, build_evidence_packet
from research_data.models import (
    DataEvidencePacket,
    DataQualityReport,
    EvidenceRef,
    PriceAdjustment,
    QualityStatus,
)

from helpers import make_ohlcv, make_series


@st.composite
def quality_reports(draw, symbol="AAPL", n_sessions=10):
    status = draw(
        st.sampled_from(
            [
                QualityStatus.USABLE,
                QualityStatus.PARTIAL,
                QualityStatus.STALE,
                QualityStatus.INSUFFICIENT_DATA,
                QualityStatus.MISSING,
                QualityStatus.CONTRADICTORY,
            ]
        )
    )
    caps = {
        QualityStatus.MISSING: 0.0,
        QualityStatus.CONTRADICTORY: 0.3,
        QualityStatus.STALE: 0.5,
        QualityStatus.INSUFFICIENT_DATA: 0.4,
        QualityStatus.PARTIAL: 0.7,
        QualityStatus.USABLE: 1.0,
    }
    start = date(2024, 1, 2)
    end = start + timedelta(days=max(n_sessions - 1, 0))
    return DataQualityReport(
        report_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        symbol=symbol,
        source_name="csv_fixture",
        generated_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        requested_start_date=start,
        requested_end_date=end,
        first_available_date=start if n_sessions else None,
        last_available_date=end if n_sessions else None,
        expected_sessions=n_sessions,
        valid_sessions=n_sessions,
        missing_sessions=[],
        rejected_records=0,
        quality_status=status,
        confidence_cap=caps[status],
        issues_json={},
    )


@st.composite
def evidence_packets(draw):
    status = draw(st.sampled_from(list(QualityStatus)))
    cap = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    if status in (QualityStatus.STALE, QualityStatus.INSUFFICIENT_DATA):
        cap = min(cap, 0.5)
    start = date(2024, 1, 2)
    end = date(2024, 3, 15)
    ref = EvidenceRef(
        table="daily_ohlcv",
        key="AAPL|2024-01-02|csv_fixture|split_dividend_adjusted",
        source="csv_fixture",
        retrieved_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        data_as_of=start,
    )
    return DataEvidencePacket(
        symbol="AAPL",
        as_of=end,
        source="csv_fixture",
        data_window=(start, end),
        latest_price_date=end,
        price_adjustment=PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
        rows_available=draw(st.integers(min_value=0, max_value=100)),
        missing_sessions=[],
        quality_status=status,
        confidence_cap=cap,
        benchmark_symbol="VOO",
        benchmark_available=draw(st.booleans()),
        evidence_refs=[ref],
    )


class TestProperty15EvidenceCompleteness:
    @given(report=quality_reports())
    @settings(max_examples=50, deadline=None)
    def test_required_fields_and_confidence_cap(self, report):
        if report.quality_status == QualityStatus.MISSING:
            records = []
        else:
            n = max(report.valid_sessions, 1)
            records = make_series("AAPL", n)

        packet = build_evidence_packet(
            symbol="AAPL",
            records=records,
            quality_report=report,
            benchmark_symbol="VOO",
            benchmark_available=True,
        )
        assert packet.symbol == "AAPL"
        assert packet.as_of is not None
        assert packet.source
        assert packet.data_window is not None
        assert packet.quality_status == report.quality_status
        assert packet.benchmark_symbol == "VOO"
        assert len(packet.evidence_refs) >= 1
        for ref in packet.evidence_refs:
            assert ref.table
            assert ref.key
            assert ref.source
            assert ref.retrieved_at is not None
            assert ref.data_as_of is not None
        if packet.quality_status in (
            QualityStatus.STALE,
            QualityStatus.INSUFFICIENT_DATA,
        ):
            assert packet.confidence_cap <= 0.5
            assert packet.confidence_cap < 1.0

    def test_refuses_missing_provenance(self):
        report = DataQualityReport(
            report_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            symbol="AAPL",
            source_name="csv_fixture",
            generated_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 2, 1),
            expected_sessions=1,
            valid_sessions=1,
            missing_sessions=[],
            rejected_records=0,
            quality_status=QualityStatus.USABLE,
            confidence_cap=1.0,
        )
        bad = make_ohlcv(raw_payload_hash="x")
        bad = bad.model_construct(**{**bad.model_dump(), "raw_payload_hash": ""})
        try:
            build_evidence_packet("AAPL", [bad], report, "VOO", True)
            raised = False
        except EvidenceConstructionError:
            raised = True
        assert raised


class TestProperty16EvidenceSerialization:
    @given(packet=evidence_packets())
    @settings(max_examples=80, deadline=None)
    def test_json_round_trip(self, packet: DataEvidencePacket):
        data = packet.model_dump_json()
        restored = DataEvidencePacket.model_validate_json(data)
        assert restored == packet
