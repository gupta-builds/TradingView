"""Deterministic synthetic OHLCV generators for factor/gate/paper tests.

Clearly labeled test data (source="synthetic_fixture") — used only to
exercise math and storage paths offline. Product code never fabricates data;
tests need long, controlled series that real 65-row CSV fixtures cannot give.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, time, timedelta, timezone

from research_data.fundamentals.models import FundamentalsSnapshot
from research_data.models import OHLCVRecord, PriceAdjustment, QualityStatus

SYNTHETIC_SOURCE = "synthetic_fixture"


def trading_days(end: date, sessions: int) -> list[date]:
    """The last ``sessions`` weekdays ending at ``end`` (inclusive if weekday).

    Weekend-skipping approximation of the NYSE calendar — good enough for
    factor-window math in tests.
    """
    days: list[date] = []
    current = end
    while len(days) < sessions:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return list(reversed(days))


def make_price_records(
    symbol: str,
    *,
    end: date,
    sessions: int,
    base_price: float = 100.0,
    daily_drift: float = 0.0004,
    daily_vol: float = 0.01,
    seed: int = 7,
    asset_type: str = "equity",
    exchange: str = "NASDAQ",
    source: str = SYNTHETIC_SOURCE,
) -> list[OHLCVRecord]:
    """Seeded geometric random-walk daily bars, valid under OHLCV validation."""
    rng = random.Random(f"{symbol}:{seed}")
    dates = trading_days(end, sessions)
    retrieved_at = datetime.combine(end, time(23, 0), tzinfo=timezone.utc)
    payload_hash = hashlib.sha256(
        f"{symbol}:{seed}:{sessions}:{source}".encode()
    ).hexdigest()

    records: list[OHLCVRecord] = []
    close = base_price
    for trading_date in dates:
        open_price = close
        close = open_price * math.exp(daily_drift + daily_vol * rng.gauss(0.0, 1.0))
        spread = abs(rng.gauss(0.0, daily_vol / 2))
        high = max(open_price, close) * (1 + spread)
        low = min(open_price, close) * (1 - spread)
        records.append(
            OHLCVRecord(
                symbol=symbol,
                asset_type=asset_type,
                exchange=exchange,
                trading_date=trading_date,
                open=round(open_price, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close, 4),
                adjusted_close=round(close, 4),
                volume=rng.randint(1_000_000, 5_000_000),
                split_factor=1.0,
                dividend_cash=0.0,
                price_adjustment=PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
                currency="USD",
                source=source,
                retrieved_at=retrieved_at,
                data_as_of=trading_date,
                raw_payload_hash=payload_hash,
                quality_status=QualityStatus.USABLE,
            )
        )
    return records


def make_fundamentals_snapshots(
    symbol: str,
    *,
    end: date,
    quarters: int = 24,
    quarterly_revenue: float = 25_000_000_000.0,
    operating_margin: float = 0.25,
    fcf_margin: float = 0.20,
    total_debt: float = 20_000_000_000.0,
    cash_and_equivalents: float = 30_000_000_000.0,
    total_equity: float = 80_000_000_000.0,
    shares_outstanding: float = 1_000_000_000.0,
    omit_cash_flows: bool = False,
    omit_balance_sheet: bool = False,
    omit_operating_income: bool = False,
) -> list[FundamentalsSnapshot]:
    """Deterministic quarterly statement fixtures (source clearly synthetic).

    Constant per-quarter values so cross-sectional quality differences come
    only from the levels a test chooses. ``omit_*`` flags produce symbols with
    missing sub-signals for INSUFFICIENT_DATA-path tests.
    """
    retrieved_at = datetime.combine(end, time(23, 0), tzinfo=timezone.utc)
    payload_hash = hashlib.sha256(f"fundamentals:{symbol}:{quarters}".encode()).hexdigest()
    capex = 0.05 * quarterly_revenue
    snapshots: list[FundamentalsSnapshot] = []
    for k in range(quarters, 0, -1):
        snapshots.append(
            FundamentalsSnapshot(
                symbol=symbol,
                source=SYNTHETIC_SOURCE,
                period_type="quarter",
                fiscal_period_end=end - timedelta(days=91 * k),
                retrieved_at=retrieved_at,
                raw_payload_hash=payload_hash,
                revenue=quarterly_revenue,
                operating_income=(
                    None if omit_operating_income else operating_margin * quarterly_revenue
                ),
                operating_cash_flow=(
                    None if omit_cash_flows else fcf_margin * quarterly_revenue + capex
                ),
                capex=None if omit_cash_flows else capex,
                total_debt=None if omit_balance_sheet else total_debt,
                cash_and_equivalents=None if omit_balance_sheet else cash_and_equivalents,
                total_equity=None if omit_balance_sheet else total_equity,
                shares_outstanding=None if omit_balance_sheet else shares_outstanding,
            )
        )
    return snapshots


def daily_returns(records: list[OHLCVRecord]) -> list[float]:
    """Simple daily returns from a record series (adjusted close)."""
    closes = [r.adjusted_close or r.close for r in records]
    return [curr / prev - 1.0 for prev, curr in zip(closes, closes[1:])]
