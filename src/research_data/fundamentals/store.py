"""DuckDB persistence for fundamentals snapshots + factor-input assembly."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from research_data.factors.quality_fcf import FundamentalInputs
from research_data.fundamentals.models import FundamentalsSnapshot

_CREATE_SNAPSHOTS = """\
CREATE TABLE IF NOT EXISTS fundamentals_snapshots (
    snapshot_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    period_type VARCHAR NOT NULL,
    fiscal_period_end DATE NOT NULL,
    retrieved_at TIMESTAMP NOT NULL,
    raw_payload_hash VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    revenue DOUBLE,
    operating_income DOUBLE,
    operating_cash_flow DOUBLE,
    capex DOUBLE,
    total_debt DOUBLE,
    cash_and_equivalents DOUBLE,
    total_equity DOUBLE,
    shares_outstanding DOUBLE,
    PRIMARY KEY (symbol, source, period_type, fiscal_period_end)
);
"""


def _to_db_ts(value: datetime | None) -> datetime | None:
    """Naive-UTC normalization (DuckDB TIMESTAMP converts aware → local)."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class FundamentalsStore:
    """Upsert + read API over fundamentals_snapshots."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def init_schema(self) -> None:
        self._conn.execute(_CREATE_SNAPSHOTS)

    def upsert_snapshots(self, snapshots: list[FundamentalsSnapshot]) -> int:
        for snapshot in snapshots:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO fundamentals_snapshots (
                    snapshot_id, symbol, source, period_type, fiscal_period_end,
                    retrieved_at, raw_payload_hash, currency,
                    revenue, operating_income, operating_cash_flow, capex,
                    total_debt, cash_and_equivalents, total_equity, shares_outstanding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    snapshot.snapshot_id,
                    snapshot.symbol,
                    snapshot.source,
                    snapshot.period_type,
                    snapshot.fiscal_period_end,
                    _to_db_ts(snapshot.retrieved_at),
                    snapshot.raw_payload_hash,
                    snapshot.currency,
                    snapshot.revenue,
                    snapshot.operating_income,
                    snapshot.operating_cash_flow,
                    snapshot.capex,
                    snapshot.total_debt,
                    snapshot.cash_and_equivalents,
                    snapshot.total_equity,
                    snapshot.shares_outstanding,
                ],
            )
        return len(snapshots)

    def get_snapshots(
        self,
        symbol: str,
        source: str | None = None,
        period_type: str | None = None,
    ) -> list[FundamentalsSnapshot]:
        conditions = ["symbol = ?"]
        params: list = [symbol]
        if source is not None:
            conditions.append("source = ?")
            params.append(source)
        if period_type is not None:
            conditions.append("period_type = ?")
            params.append(period_type)
        rows = self._conn.execute(
            f"""
            SELECT snapshot_id, symbol, source, period_type, fiscal_period_end,
                   retrieved_at, raw_payload_hash, currency,
                   revenue, operating_income, operating_cash_flow, capex,
                   total_debt, cash_and_equivalents, total_equity, shares_outstanding
            FROM fundamentals_snapshots
            WHERE {' AND '.join(conditions)}
            ORDER BY fiscal_period_end ASC
            """,
            params,
        ).fetchall()
        return [_row_to_snapshot(r) for r in rows]


def _row_to_snapshot(row: tuple) -> FundamentalsSnapshot:
    retrieved_at = row[5]
    if retrieved_at is not None and retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    return FundamentalsSnapshot(
        snapshot_id=row[0],
        symbol=row[1],
        source=row[2],
        period_type=row[3],
        fiscal_period_end=row[4],
        retrieved_at=retrieved_at,
        raw_payload_hash=row[6],
        currency=row[7],
        revenue=row[8],
        operating_income=row[9],
        operating_cash_flow=row[10],
        capex=row[11],
        total_debt=row[12],
        cash_and_equivalents=row[13],
        total_equity=row[14],
        shares_outstanding=row[15],
    )


def to_factor_inputs(
    symbol: str,
    snapshots: list[FundamentalsSnapshot],
    margin_periods: int = 8,
) -> FundamentalInputs | None:
    """Assemble FactorEngine inputs from stored snapshots.

    Point-in-time fields come from the latest snapshot that carries each field
    (statement coverage varies by source); the operating-margin history comes
    from the trailing quarterly snapshots. Returns None when there are no
    snapshots at all — the factor layer then reports INSUFFICIENT_DATA.
    """
    if not snapshots:
        return None
    ordered = sorted(snapshots, key=lambda s: s.fiscal_period_end)
    latest = ordered[-1]

    def latest_field(name: str) -> float | None:
        for snapshot in reversed(ordered):
            value = getattr(snapshot, name)
            if value is not None:
                return value
        return None

    quarterly = [s for s in ordered if s.period_type == "quarter"]
    margins = [
        m
        for m in (s.operating_margin for s in quarterly[-margin_periods:])
        if m is not None
    ]

    return FundamentalInputs(
        symbol=symbol,
        as_of=latest.fiscal_period_end,
        source=latest.source,
        revenue=latest_field("revenue"),
        operating_cash_flow=latest_field("operating_cash_flow"),
        capex=latest_field("capex"),
        total_debt=latest_field("total_debt"),
        cash_and_equivalents=latest_field("cash_and_equivalents"),
        total_equity=latest_field("total_equity"),
        shares_outstanding=latest_field("shares_outstanding"),
        operating_margins=margins,
    )
