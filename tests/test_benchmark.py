"""Property and unit tests for benchmark reporter.

Properties 14, 20 and Task 10.4 — Requirements 11.1–11.6, 9.5
"""

from __future__ import annotations

import re
import sys
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, "src")

from research_data.benchmark import (
    BenchmarkError,
    BenchmarkReport,
    compute_benchmark,
    map_quality_label,
)
from research_data.models import QualityStatus

from helpers import make_series

_EXEC_RE = re.compile(r"\b(BUY NOW|SELL NOW|BUY|SELL|HOLD)\b", re.IGNORECASE)


class TestProperty20BenchmarkRefusesInsufficient:
    @given(
        status=st.sampled_from(
            [QualityStatus.INSUFFICIENT_DATA, QualityStatus.MISSING, QualityStatus.STALE]
        ),
        n=st.integers(min_value=0, max_value=60),
    )
    @settings(max_examples=40, deadline=None)
    def test_refuses_bad_quality(self, status, n):
        records = make_series("AAPL", n) if n else []
        try:
            compute_benchmark(
                symbol="AAPL",
                records=records,
                quality_status=status,
                missing_session_count=0,
                benchmark_symbol="VOO",
            )
            raised = False
        except BenchmarkError as e:
            raised = True
            assert e.quality_status == status
        assert raised


class TestProperty14NoExecutionLanguage:
    @given(
        n=st.integers(min_value=50, max_value=80),
        status=st.sampled_from([QualityStatus.USABLE, QualityStatus.PARTIAL]),
    )
    @settings(max_examples=30, deadline=None)
    def test_benchmark_output_has_no_execution_language(self, n, status):
        records = make_series("AAPL", n, base_price=100.0)
        bm = make_series("VOO", n, base_price=400.0)
        report = compute_benchmark(
            symbol="AAPL",
            records=records,
            quality_status=status,
            missing_session_count=2,
            benchmark_symbol="VOO",
            benchmark_records=bm,
        )
        text = report.format_text()
        assert _EXEC_RE.search(text) is None
        for value in report.to_dict().values():
            if isinstance(value, str):
                assert _EXEC_RE.search(value) is None


class TestBenchmarkUnit:
    def test_metrics_with_known_series(self):
        # 50 sessions, price doubles → total return = 1.0
        records = make_series("AAPL", 50, base_price=100.0)
        # Override closes to exact geometric path
        for i, r in enumerate(records):
            px = 100.0 + i  # linear
            records[i] = r.model_copy(
                update={"close": px, "adjusted_close": px, "open": px, "high": px + 1, "low": px - 1}
            )
        bm = make_series("VOO", 50, base_price=400.0)
        report = compute_benchmark(
            "AAPL", records, QualityStatus.USABLE, 0, "VOO", bm
        )
        assert isinstance(report, BenchmarkReport)
        assert report.sessions_used == 50
        assert report.latest_data_date == records[-1].trading_date
        assert report.total_return == records[-1].close / records[0].close - 1.0
        assert report.maximum_drawdown <= 0.0
        assert report.quality_label == "usable"

    def test_refuse_fewer_than_50_sessions(self):
        records = make_series("AAPL", 49)
        try:
            compute_benchmark("AAPL", records, QualityStatus.USABLE, 0, "VOO")
            assert False, "expected BenchmarkError"
        except BenchmarkError as e:
            assert "50" in e.reason

    def test_insufficient_overlap_sets_excess_none(self):
        records = make_series("AAPL", 50, start=date(2024, 1, 1))
        bm = make_series("VOO", 50, start=date(2023, 1, 1))  # no overlap
        report = compute_benchmark(
            "AAPL", records, QualityStatus.PARTIAL, 0, "VOO", bm
        )
        assert report.benchmark_excess_return is None
        assert report.overlapping_sessions < 50

    def test_quality_label_mapping(self):
        assert map_quality_label(QualityStatus.USABLE) == "usable"
        assert map_quality_label(QualityStatus.STALE) == "stale"
        assert map_quality_label(QualityStatus.MISSING) == "insufficient_data"
        assert map_quality_label(QualityStatus.INSUFFICIENT_DATA) == "insufficient_data"
        assert map_quality_label(QualityStatus.PARTIAL) == "needs_review"
        assert map_quality_label(QualityStatus.CONTRADICTORY) == "needs_review"
