"""Read API for downstream module consumption.

Provides typed access to time-ordered price frames with quality metadata,
so that strategy and evidence modules do not query raw tables directly.

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import duckdb

from research_data.models import (
    InsufficientDataError,
    OHLCVRecord,
    PriceAdjustment,
    QualityStatus,
)


# Statuses excluded when require_usable=True
_UNUSABLE_STATUSES = frozenset({
    QualityStatus.MISSING.value,
    QualityStatus.CONTRADICTORY.value,
    QualityStatus.INSUFFICIENT_DATA.value,
})


class PriceReadAPI:
    """Downstream-facing interface for reading time-ordered price frames.

    Returns OHLCV rows ordered by symbol ascending and trading_date ascending,
    with provenance metadata and quality_status on each record.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def get_price_frame(
        self,
        symbols: list[str],
        start: date,
        end: date,
        source: str | None = None,
        price_adjustment: PriceAdjustment | None = None,
        require_usable: bool = True,
        min_rows: int | None = None,
    ) -> list[OHLCVRecord]:
        """Return time-ordered OHLCV rows with provenance and quality metadata.

        Args:
            symbols: List of symbols to query.
            start: Start date (inclusive).
            end: End date (inclusive).
            source: Optional filter by source provider.
            price_adjustment: Optional filter by price adjustment type.
            require_usable: If True, exclude MISSING, CONTRADICTORY,
                and INSUFFICIENT_DATA records.
            min_rows: If specified, raise InsufficientDataError when a symbol
                has fewer rows than this value.

        Returns:
            List of OHLCVRecord instances ordered by (symbol, trading_date).

        Raises:
            InsufficientDataError: When a symbol has fewer rows than min_rows.

        Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
        """
        # Build query with filters
        conditions = [
            "symbol IN (SELECT UNNEST(?))",
            "trading_date >= ?",
            "trading_date <= ?",
        ]
        params: list[Any] = [symbols, start, end]

        if require_usable:
            # Exclude unusable statuses
            conditions.append(
                "quality_status NOT IN (?, ?, ?)"
            )
            params.extend([
                QualityStatus.MISSING.value,
                QualityStatus.CONTRADICTORY.value,
                QualityStatus.INSUFFICIENT_DATA.value,
            ])

        if source is not None:
            conditions.append("source = ?")
            params.append(source)

        if price_adjustment is not None:
            conditions.append("price_adjustment = ?")
            params.append(price_adjustment.value)

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT symbol, asset_type, exchange, trading_date,
                   open, high, low, close, adjusted_close, volume,
                   split_factor, dividend_cash, price_adjustment, currency,
                   source, source_record_id, retrieved_at, data_as_of,
                   raw_payload_hash, quality_status
            FROM daily_ohlcv
            WHERE {where_clause}
            ORDER BY symbol ASC, trading_date ASC
        """

        rows = self._conn.execute(query, params).fetchall()

        # Convert rows to OHLCVRecord instances
        records = [self._row_to_record(row) for row in rows]

        # Check min_rows constraint per symbol
        if min_rows is not None:
            for symbol in symbols:
                symbol_records = [r for r in records if r.symbol == symbol]
                if len(symbol_records) < min_rows:
                    raise InsufficientDataError(
                        symbol=symbol,
                        rows_available=len(symbol_records),
                        rows_requested=min_rows,
                    )

        return records

    def _row_to_record(self, row: tuple) -> OHLCVRecord:
        """Convert a DuckDB row tuple to an OHLCVRecord instance."""
        retrieved_at = row[16]
        # Ensure retrieved_at has timezone info (UTC)
        if retrieved_at is not None and retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)

        return OHLCVRecord(
            symbol=row[0],
            asset_type=row[1],
            exchange=row[2],
            trading_date=row[3],
            open=row[4],
            high=row[5],
            low=row[6],
            close=row[7],
            adjusted_close=row[8],
            volume=row[9],
            split_factor=row[10],
            dividend_cash=row[11],
            price_adjustment=PriceAdjustment(row[12]),
            currency=row[13],
            source=row[14],
            source_record_id=row[15],
            retrieved_at=retrieved_at,
            data_as_of=row[17],
            raw_payload_hash=row[18],
            quality_status=QualityStatus(row[19]),
        )
