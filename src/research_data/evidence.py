"""Evidence packet builder for downstream AI consumption.

Builds DataEvidencePacket instances from stored OHLCV records and quality
reports with full provenance. Does not call any LLM APIs.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from research_data.models import (
    DataEvidencePacket,
    DataQualityReport,
    EvidenceRef,
    OHLCVRecord,
    PriceAdjustment,
    QualityStatus,
)


class EvidenceConstructionError(Exception):
    """Raised when an evidence packet cannot be built due to missing provenance."""


def build_evidence_packet(
    symbol: str,
    records: list[OHLCVRecord],
    quality_report: DataQualityReport,
    benchmark_symbol: str,
    benchmark_available: bool,
    as_of: date | None = None,
) -> DataEvidencePacket:
    """Build a DataEvidencePacket from stored records and a quality report.

    Args:
        symbol: Ticker symbol for the packet.
        records: OHLCV records contributing to the packet (must have provenance).
        quality_report: Latest quality report for the symbol.
        benchmark_symbol: Configured ETF baseline symbol.
        benchmark_available: Whether benchmark data is available.
        as_of: Packet as-of date; defaults to UTC today.

    Returns:
        A fully populated DataEvidencePacket.

    Raises:
        EvidenceConstructionError: When required provenance fields are missing
            or no evidence_refs can be constructed.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc).date()

    if not records and quality_report.quality_status != QualityStatus.MISSING:
        raise EvidenceConstructionError(
            f"Cannot build evidence packet for {symbol}: no records provided"
        )

    # Determine source and price_adjustment from records or report
    if records:
        sources = {r.source for r in records}
        if len(sources) != 1:
            # Multi-source packets still allowed; use primary from report
            source = quality_report.source_name
        else:
            source = next(iter(sources))

        adjustments = {r.price_adjustment for r in records}
        price_adjustment = (
            next(iter(adjustments))
            if len(adjustments) == 1
            else PriceAdjustment.UNKNOWN
        )

        sorted_records = sorted(records, key=lambda r: r.trading_date)
        data_window = (sorted_records[0].trading_date, sorted_records[-1].trading_date)
        latest_price_date = sorted_records[-1].trading_date
    else:
        source = quality_report.source_name
        price_adjustment = PriceAdjustment.UNKNOWN
        data_window = (
            quality_report.requested_start_date,
            quality_report.requested_end_date,
        )
        latest_price_date = quality_report.last_available_date

    if not source:
        raise EvidenceConstructionError(
            f"Cannot build evidence packet for {symbol}: missing source"
        )

    evidence_refs = _build_evidence_refs(records, quality_report)
    if not evidence_refs:
        raise EvidenceConstructionError(
            f"Cannot build evidence packet for {symbol}: "
            "at least one evidence_ref is required"
        )

    confidence_cap = _apply_confidence_cap(
        quality_report.quality_status, quality_report.confidence_cap
    )

    return DataEvidencePacket(
        symbol=symbol,
        as_of=as_of,
        source=source,
        data_window=data_window,
        latest_price_date=latest_price_date,
        price_adjustment=price_adjustment,
        rows_available=len(records),
        missing_sessions=list(quality_report.missing_sessions),
        quality_status=quality_report.quality_status,
        confidence_cap=confidence_cap,
        benchmark_symbol=benchmark_symbol,
        benchmark_available=benchmark_available,
        evidence_refs=evidence_refs,
    )


def _apply_confidence_cap(status: QualityStatus, reported_cap: float) -> float:
    """Enforce confidence_cap constraints for STALE / INSUFFICIENT_DATA.

    Requirements 12.3: confidence_cap <= 0.5 when STALE or INSUFFICIENT_DATA.
    """
    if status in (QualityStatus.STALE, QualityStatus.INSUFFICIENT_DATA):
        return min(reported_cap, 0.5)
    return reported_cap


def _build_evidence_refs(
    records: list[OHLCVRecord],
    quality_report: DataQualityReport,
) -> list[EvidenceRef]:
    """Build at least one EvidenceRef per contributing data source.

    Prefer one ref per unique (source, raw_payload_hash) from records.
    When records are empty (MISSING), reference the quality report itself.
    """
    refs: list[EvidenceRef] = []
    seen_keys: set[str] = set()

    for record in records:
        if not record.raw_payload_hash or not record.source:
            raise EvidenceConstructionError(
                f"Record for {record.symbol} on {record.trading_date} "
                "is missing required provenance (source or raw_payload_hash)"
            )
        if record.retrieved_at is None:
            raise EvidenceConstructionError(
                f"Record for {record.symbol} on {record.trading_date} "
                "is missing retrieved_at"
            )

        key = (
            f"{record.symbol}|{record.trading_date.isoformat()}|"
            f"{record.source}|{record.price_adjustment.value}"
        )
        # One ref per source is enough; keep first record per source
        source_key = record.source
        if source_key in seen_keys:
            continue
        seen_keys.add(source_key)

        refs.append(
            EvidenceRef(
                table="daily_ohlcv",
                key=key,
                source=record.source,
                retrieved_at=record.retrieved_at,
                data_as_of=record.data_as_of,
            )
        )

    if not refs:
        # MISSING / empty: cite the quality report as provenance
        refs.append(
            EvidenceRef(
                table="data_quality_reports",
                key=quality_report.report_id,
                source=quality_report.source_name,
                retrieved_at=quality_report.generated_at,
                data_as_of=quality_report.requested_end_date,
            )
        )

    return refs
