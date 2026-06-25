"""Normalizer: converts provider-specific payloads into canonical OHLCVRecord rows.

The normalizer takes a ProviderFetchResult and provider configuration, then
re-validates each record with corrected provenance fields, default values,
and proper price adjustment mapping.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Protocol

from pydantic import ValidationError

from research_data.config import ProviderConfig
from research_data.models import OHLCVRecord, PriceAdjustment, ProviderFetchResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Market Calendar Protocol (for dependency injection)
# ---------------------------------------------------------------------------


class MarketCalendarProtocol(Protocol):
    """Protocol for market calendar implementations.

    Used to derive trading_date in the exchange's local timezone.
    """

    def to_trading_date(self, dt: date | datetime, exchange: str | None) -> date:
        """Convert a date/datetime to the trading date in the exchange timezone."""
        ...


class PassthroughCalendar:
    """Default calendar that passes dates through unchanged.

    Used when no market calendar is available. The actual calendar
    implementation (task 6.2) will replace this for production use.
    """

    def to_trading_date(self, dt: date | datetime, exchange: str | None) -> date:
        """Return the date as-is (no timezone conversion)."""
        if isinstance(dt, datetime):
            return dt.date()
        return dt


# ---------------------------------------------------------------------------
# Adjustment Policy Mapping
# ---------------------------------------------------------------------------

_ADJUSTMENT_POLICY_MAP: dict[str, PriceAdjustment] = {
    "raw": PriceAdjustment.RAW,
    "unadjusted": PriceAdjustment.RAW,
    "split_adjusted": PriceAdjustment.SPLIT_ADJUSTED,
    "split": PriceAdjustment.SPLIT_ADJUSTED,
    "split_dividend_adjusted": PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
    "fully_adjusted": PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
    "adjusted": PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
}


def map_adjustment_policy(policy: str) -> PriceAdjustment:
    """Map a provider's adjustment_policy string to a PriceAdjustment enum value.

    Args:
        policy: The adjustment_policy string from provider configuration.
                Recognized values (case-insensitive):
                - "raw", "unadjusted" -> PriceAdjustment.RAW
                - "split_adjusted", "split" -> PriceAdjustment.SPLIT_ADJUSTED
                - "split_dividend_adjusted", "fully_adjusted", "adjusted"
                  -> PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED
                - Anything else -> PriceAdjustment.UNKNOWN

    Returns:
        The corresponding PriceAdjustment enum value.
    """
    if not policy:
        return PriceAdjustment.UNKNOWN
    return _ADJUSTMENT_POLICY_MAP.get(policy.lower().strip(), PriceAdjustment.UNKNOWN)


# ---------------------------------------------------------------------------
# Normalization Result
# ---------------------------------------------------------------------------


@dataclass
class NormalizationResult:
    """Result of normalizing a provider fetch result.

    Attributes:
        valid_records: List of successfully normalized OHLCVRecord instances.
        rejected_count: Number of records that failed normalization.
        warnings: List of warning messages about skipped or problematic records.
    """

    valid_records: list[OHLCVRecord] = field(default_factory=list)
    rejected_count: int = 0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core Normalization Function
# ---------------------------------------------------------------------------


def normalize_fetch_result(
    fetch_result: ProviderFetchResult,
    provider_config: ProviderConfig,
    calendar: MarketCalendarProtocol | None = None,
) -> NormalizationResult:
    """Normalize a ProviderFetchResult into canonical OHLCVRecord rows.

    Takes a ProviderFetchResult (containing records from any provider) and
    re-validates each record with:
    - Correct price_adjustment based on provider's adjustment_policy
    - Default split_factor=1.0 and dividend_cash=0.0 when not supplied
    - Provenance fields: source, retrieved_at, data_as_of, raw_payload_hash
    - Trading date derived using exchange timezone (via calendar)
    - adjusted_close preserved separately from close

    Records that fail validation are skipped and counted as rejected.

    Args:
        fetch_result: The raw fetch result from a provider.
        provider_config: Configuration for the provider that produced the result.
        calendar: Optional market calendar for trading date derivation.
                  If None, uses PassthroughCalendar (dates pass through unchanged).

    Returns:
        NormalizationResult with valid records, rejected count, and warnings.
    """
    if calendar is None:
        calendar = PassthroughCalendar()

    price_adjustment = map_adjustment_policy(provider_config.adjustment_policy)
    result = NormalizationResult()

    for idx, record in enumerate(fetch_result.records):
        try:
            normalized = _normalize_record(
                record=record,
                fetch_result=fetch_result,
                provider_config=provider_config,
                price_adjustment=price_adjustment,
                calendar=calendar,
            )
            result.valid_records.append(normalized)
        except (ValidationError, ValueError, TypeError) as e:
            result.rejected_count += 1
            warning_msg = (
                f"Record {idx} for {fetch_result.symbol} skipped: {e}"
            )
            result.warnings.append(warning_msg)
            logger.warning(warning_msg)

    return result


def _normalize_record(
    record: OHLCVRecord,
    fetch_result: ProviderFetchResult,
    provider_config: ProviderConfig,
    price_adjustment: PriceAdjustment,
    calendar: MarketCalendarProtocol,
) -> OHLCVRecord:
    """Normalize a single record by re-constructing it with corrected fields.

    This re-validates the record through Pydantic by constructing a new
    OHLCVRecord instance with:
    - Provenance fields from the fetch result
    - Defaults for split_factor and dividend_cash
    - Correct price_adjustment from provider config
    - Trading date derived via market calendar

    Args:
        record: The original OHLCVRecord from the provider.
        fetch_result: The parent fetch result (for provenance).
        provider_config: Provider configuration.
        price_adjustment: The mapped PriceAdjustment enum value.
        calendar: Market calendar for trading date derivation.

    Returns:
        A new, validated OHLCVRecord instance.

    Raises:
        ValidationError: If the record fails Pydantic validation.
        ValueError: If required fields cannot be derived.
    """
    # Derive trading_date using exchange timezone from calendar
    trading_date = calendar.to_trading_date(
        record.trading_date, record.exchange
    )

    # Determine data_as_of: use the trading_date if not otherwise available
    data_as_of = record.data_as_of if record.data_as_of else trading_date

    # Set defaults: split_factor=1.0, dividend_cash=0.0 when not supplied
    split_factor = record.split_factor if record.split_factor is not None else 1.0
    dividend_cash = record.dividend_cash if record.dividend_cash is not None else 0.0

    # Preserve adjusted_close separately from close (Requirement 4.5)
    # If provider supplies adjusted_close, store it; otherwise set to None
    adjusted_close = record.adjusted_close

    # Construct a new OHLCVRecord with corrected provenance and defaults
    # This triggers full Pydantic validation
    normalized = OHLCVRecord(
        symbol=record.symbol,
        asset_type=record.asset_type,
        exchange=record.exchange,
        trading_date=trading_date,
        open=record.open,
        high=record.high,
        low=record.low,
        close=record.close,
        adjusted_close=adjusted_close,
        volume=record.volume,
        split_factor=split_factor,
        dividend_cash=dividend_cash,
        price_adjustment=price_adjustment,
        currency=record.currency,
        source=provider_config.source_name,
        source_record_id=record.source_record_id,
        retrieved_at=fetch_result.retrieved_at,
        data_as_of=data_as_of,
        raw_payload_hash=fetch_result.content_hash,
        quality_status=record.quality_status,
    )

    return normalized
