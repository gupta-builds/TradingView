"""Property tests for Read API ordering, usability filter, and source filtering.

Properties 7, 8, 9 — Validates Requirements 10.1, 10.2, 10.5
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, "src")

from research_data.models import PriceAdjustment, QualityStatus
from research_data.read_api import PriceReadAPI
from research_data.storage import batch_insert_ohlcv

from helpers import fresh_db, make_ohlcv


SYMBOLS = ["AAPL", "MSFT", "VOO"]
SOURCES = ["csv_fixture", "polygon"]
ADJUSTMENTS = list(PriceAdjustment)
STATUSES = list(QualityStatus)


@st.composite
def multi_symbol_records(draw):
    n = draw(st.integers(min_value=1, max_value=40))
    records = []
    used = set()
    for _ in range(n):
        symbol = draw(st.sampled_from(SYMBOLS))
        day_offset = draw(st.integers(min_value=0, max_value=80))
        trading_date = date(2024, 1, 2) + timedelta(days=day_offset)
        source = draw(st.sampled_from(SOURCES))
        adj = draw(st.sampled_from(ADJUSTMENTS))
        status = draw(st.sampled_from(STATUSES))
        key = (symbol, trading_date, source, adj)
        if key in used:
            continue
        used.add(key)
        records.append(
            make_ohlcv(
                symbol=symbol,
                trading_date=trading_date,
                source=source,
                price_adjustment=adj,
                quality_status=status,
            )
        )
    return records


class TestProperty7ReadApiOrdering:
    @given(records=multi_symbol_records())
    @settings(max_examples=40, deadline=None)
    def test_rows_ordered_by_symbol_then_date(self, records):
        conn = fresh_db()
        batch_insert_ohlcv(conn, records)
        api = PriceReadAPI(conn)
        result = api.get_price_frame(
            SYMBOLS, date(2024, 1, 1), date(2024, 6, 1), require_usable=False
        )
        pairs = [(r.symbol, r.trading_date) for r in result]
        assert pairs == sorted(pairs)


class TestProperty8UsabilityFilter:
    @given(records=multi_symbol_records())
    @settings(max_examples=40, deadline=None)
    def test_require_usable_excludes_unusable(self, records):
        conn = fresh_db()
        batch_insert_ohlcv(conn, records)
        api = PriceReadAPI(conn)
        result = api.get_price_frame(
            SYMBOLS, date(2024, 1, 1), date(2024, 6, 1), require_usable=True
        )
        forbidden = {
            QualityStatus.MISSING,
            QualityStatus.CONTRADICTORY,
            QualityStatus.INSUFFICIENT_DATA,
        }
        for r in result:
            assert r.quality_status not in forbidden


class TestProperty9SourceAdjustmentFilter:
    @given(
        records=multi_symbol_records(),
        source=st.sampled_from(SOURCES),
        adj=st.sampled_from(ADJUSTMENTS),
    )
    @settings(max_examples=40, deadline=None)
    def test_filters_match_exactly(self, records, source, adj):
        conn = fresh_db()
        batch_insert_ohlcv(conn, records)
        api = PriceReadAPI(conn)
        result = api.get_price_frame(
            SYMBOLS,
            date(2024, 1, 1),
            date(2024, 6, 1),
            source=source,
            price_adjustment=adj,
            require_usable=False,
        )
        for r in result:
            assert r.source == source
            assert r.price_adjustment == adj
