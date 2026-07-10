"""Shared helpers for research_data tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb

from research_data.models import OHLCVRecord, PriceAdjustment, QualityStatus
from research_data.storage import init_db


def make_ohlcv(
    symbol: str = "AAPL",
    trading_date: date = date(2024, 3, 15),
    source: str = "csv_fixture",
    price_adjustment: PriceAdjustment = PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
    quality_status: QualityStatus = QualityStatus.USABLE,
    close: float = 100.0,
    **overrides,
) -> OHLCVRecord:
    kwargs = {
        "symbol": symbol,
        "asset_type": "etf" if symbol in {"VOO", "VTI", "SPY", "QQQ"} else "equity",
        "exchange": "NYSE",
        "trading_date": trading_date,
        "open": close - 1.0,
        "high": close + 2.0,
        "low": close - 2.0,
        "close": close,
        "adjusted_close": close,
        "volume": 1_000_000,
        "split_factor": 1.0,
        "dividend_cash": 0.0,
        "price_adjustment": price_adjustment,
        "currency": "USD",
        "source": source,
        "source_record_id": None,
        "retrieved_at": datetime(2024, 3, 15, 21, 0, 0, tzinfo=timezone.utc),
        "data_as_of": trading_date,
        "raw_payload_hash": f"hash_{symbol}_{trading_date.isoformat()}",
        "quality_status": quality_status,
    }
    kwargs.update(overrides)
    return OHLCVRecord(**kwargs)


def make_series(
    symbol: str,
    n: int,
    start: date = date(2024, 1, 2),
    source: str = "csv_fixture",
    quality_status: QualityStatus = QualityStatus.USABLE,
    base_price: float = 100.0,
) -> list[OHLCVRecord]:
    records = []
    for i in range(n):
        records.append(
            make_ohlcv(
                symbol=symbol,
                trading_date=start + timedelta(days=i),
                source=source,
                quality_status=quality_status,
                close=base_price * (1.0 + 0.001 * i),
            )
        )
    return records


def fresh_db() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    init_db(conn)
    return conn
