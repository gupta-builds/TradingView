"""Data Quality Auditor for the research data system.

Evaluates symbol-level and record-level quality after ingestion, assigns
QualityStatus per precedence rules, computes confidence_cap, and detects
issues such as contradictory OHLC, stale data, duplicate dates,
non-monotonic dates, UNKNOWN price_adjustment, and cross-provider
disagreement.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from research_data.calendar import MarketCalendar
from research_data.models import (
    DataQualityReport,
    OHLCVRecord,
    PriceAdjustment,
    QualityStatus,
)


# ---------------------------------------------------------------------------
# DataQualityAuditor
# ---------------------------------------------------------------------------


class DataQualityAuditor:
    """Evaluates symbol-level data quality and generates quality reports.

    Uses MarketCalendar to determine expected sessions and applies checks
    in precedence order: MISSING > CONTRADICTORY > STALE > INSUFFICIENT_DATA
    > PARTIAL > USABLE.
    """

    def __init__(self, calendar: MarketCalendar | None = None) -> None:
        """Initialize the auditor with an optional MarketCalendar instance.

        Args:
            calendar: A MarketCalendar instance. If None, a new one is created.
        """
        self._calendar = calendar or MarketCalendar()

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def audit_symbol(
        self,
        symbol: str,
        records: list[OHLCVRecord],
        exchange: str,
        start_date: date,
        end_date: date,
        run_id: str,
        source_name: str,
        rejected_records: int = 0,
        indicator_window: int = 200,
    ) -> DataQualityReport:
        """Generate a quality report for a symbol after ingestion.

        Takes normalized records for a symbol and generates a quality report.
        Uses MarketCalendar to determine expected sessions and assigns
        QualityStatus per precedence rules (Req 7.10).

        Args:
            symbol: The ticker symbol being audited.
            records: List of validated OHLCVRecord instances for this symbol.
            exchange: Exchange name (NYSE, NASDAQ) for calendar lookups.
            start_date: Requested ingestion start date.
            end_date: Requested ingestion end date.
            run_id: UUID of the current ingestion run.
            source_name: Name of the data provider.
            rejected_records: Count of records rejected during normalization.
            indicator_window: Minimum sessions needed for downstream indicators.

        Returns:
            A DataQualityReport with status, confidence_cap, and issues.
        """
        issues: dict[str, Any] = {}
        now = datetime.now(timezone.utc)

        # Determine expected sessions from market calendar
        expected_sessions = self._calendar.get_trading_sessions(
            exchange, start_date, end_date
        )
        expected_count = len(expected_sessions)

        # Extract actual trading dates from records
        actual_dates = [r.trading_date for r in records]
        valid_sessions = len(set(actual_dates))

        # Compute missing sessions
        missing_sessions = self._calendar.get_missing_sessions(
            exchange, start_date, end_date, actual_dates
        )

        # Determine first/last available dates
        first_available: date | None = None
        last_available: date | None = None
        if actual_dates:
            sorted_dates = sorted(actual_dates)
            first_available = sorted_dates[0]
            last_available = sorted_dates[-1]

        # --- Run all checks and collect issues ---

        # Check for contradictory OHLC
        contradictory_issues = self._check_contradictory_ohlc(records)
        if contradictory_issues:
            issues["contradictory_ohlc"] = contradictory_issues

        # Check for duplicate dates
        duplicate_issues = self._check_duplicate_dates(actual_dates)
        if duplicate_issues:
            issues["duplicate_dates"] = duplicate_issues

        # Check for non-monotonic dates
        non_monotonic_issues = self._check_non_monotonic_dates(actual_dates)
        if non_monotonic_issues:
            issues["non_monotonic_dates"] = non_monotonic_issues

        # Check for UNKNOWN price_adjustment
        unknown_adjustment_issues = self._check_unknown_adjustment(records)
        if unknown_adjustment_issues:
            issues["unknown_price_adjustment"] = unknown_adjustment_issues

        # --- Determine QualityStatus per precedence (Req 7.10) ---
        # MISSING > CONTRADICTORY > STALE > INSUFFICIENT_DATA > PARTIAL > USABLE

        quality_status: QualityStatus
        confidence_cap: float

        if valid_sessions == 0:
            # MISSING: zero valid rows (Req 7.2)
            quality_status = QualityStatus.MISSING
            confidence_cap = 0.0
        elif contradictory_issues:
            # CONTRADICTORY: impossible OHLC relationships (Req 7.4)
            quality_status = QualityStatus.CONTRADICTORY
            confidence_cap = 0.3
        elif self._check_stale(last_available, exchange):
            # STALE: latest bar older than latest expected session (Req 7.3)
            quality_status = QualityStatus.STALE
            confidence_cap = 0.5
            issues["stale_data"] = {
                "last_available_date": str(last_available),
                "latest_expected_session": str(
                    self._calendar.get_latest_expected_session(exchange)
                ),
            }
        elif valid_sessions < indicator_window and valid_sessions < 50:
            # INSUFFICIENT_DATA: valid sessions < indicator_window and < 50 (Req 7.5)
            quality_status = QualityStatus.INSUFFICIENT_DATA
            confidence_cap = 0.4
        elif valid_sessions >= 50 and valid_sessions < indicator_window:
            # PARTIAL: valid sessions >= 50 but < indicator_window (Req 7.6)
            quality_status = QualityStatus.PARTIAL
            confidence_cap = 0.7
        else:
            # USABLE: all checks pass (Req 7.7)
            quality_status = QualityStatus.USABLE
            confidence_cap = 1.0

        return DataQualityReport(
            report_id=str(uuid.uuid4()),
            run_id=run_id,
            symbol=symbol,
            source_name=source_name,
            generated_at=now,
            requested_start_date=start_date,
            requested_end_date=end_date,
            first_available_date=first_available,
            last_available_date=last_available,
            expected_sessions=expected_count,
            valid_sessions=valid_sessions,
            missing_sessions=missing_sessions,
            rejected_records=rejected_records,
            quality_status=quality_status,
            confidence_cap=confidence_cap,
            issues_json=issues,
        )

    def detect_cross_provider_disagreement(
        self,
        records_primary: list[OHLCVRecord],
        records_secondary: list[OHLCVRecord],
        threshold: float = 0.01,
    ) -> list[dict[str, Any]]:
        """Compare OHLCV fields between two providers for the same symbol/date.

        Flags when any field differs by more than the threshold (default 1%)
        relative to the primary provider's value.

        Args:
            records_primary: Records from the primary provider.
            records_secondary: Records from the secondary provider.
            threshold: Relative difference threshold (default 0.01 = 1%).

        Returns:
            List of disagreement dicts with date, field, primary_value,
            secondary_value, and relative_difference.
        """
        # Index secondary records by trading_date
        secondary_by_date: dict[date, OHLCVRecord] = {
            r.trading_date: r for r in records_secondary
        }

        disagreements: list[dict[str, Any]] = []

        for primary in records_primary:
            secondary = secondary_by_date.get(primary.trading_date)
            if secondary is None:
                continue

            # Compare OHLCV fields
            fields_to_compare = [
                ("open", primary.open, secondary.open),
                ("high", primary.high, secondary.high),
                ("low", primary.low, secondary.low),
                ("close", primary.close, secondary.close),
                ("volume", float(primary.volume), float(secondary.volume)),
            ]

            for field_name, primary_val, secondary_val in fields_to_compare:
                if primary_val == 0:
                    # Avoid division by zero; skip comparison
                    continue
                relative_diff = abs(primary_val - secondary_val) / abs(primary_val)
                if relative_diff > threshold:
                    disagreements.append(
                        {
                            "trading_date": str(primary.trading_date),
                            "field": field_name,
                            "primary_value": primary_val,
                            "secondary_value": secondary_val,
                            "relative_difference": round(relative_diff, 6),
                        }
                    )

        return disagreements

    # -------------------------------------------------------------------
    # Helper Methods (Private)
    # -------------------------------------------------------------------

    def _check_contradictory_ohlc(
        self, records: list[OHLCVRecord]
    ) -> list[dict[str, Any]]:
        """Detect records with impossible OHLC relationships.

        Checks for:
        - high < low
        - high < open or high < close
        - low > open or low > close

        Note: These should normally be caught by Pydantic validation, but
        this check catches any records that slipped through or were loaded
        from storage without re-validation.

        Returns:
            List of issue dicts describing contradictory records.
        """
        issues: list[dict[str, Any]] = []
        for record in records:
            problems: list[str] = []
            if record.high < record.low:
                problems.append(f"high ({record.high}) < low ({record.low})")
            if record.high < record.open:
                problems.append(f"high ({record.high}) < open ({record.open})")
            if record.high < record.close:
                problems.append(f"high ({record.high}) < close ({record.close})")
            if record.low > record.open:
                problems.append(f"low ({record.low}) > open ({record.open})")
            if record.low > record.close:
                problems.append(f"low ({record.low}) > close ({record.close})")

            if problems:
                issues.append(
                    {
                        "trading_date": str(record.trading_date),
                        "problems": problems,
                    }
                )
        return issues

    def _check_stale(
        self, last_available: date | None, exchange: str
    ) -> bool:
        """Check if the latest bar is older than the latest expected session.

        Args:
            last_available: The most recent trading_date in the data.
            exchange: Exchange name for calendar lookup.

        Returns:
            True if data is stale, False otherwise.
        """
        if last_available is None:
            return False  # No data means MISSING, not STALE

        latest_expected = self._calendar.get_latest_expected_session(exchange)
        return last_available < latest_expected

    def _check_duplicate_dates(
        self, actual_dates: list[date]
    ) -> list[dict[str, Any]]:
        """Detect duplicate trading_dates in the records.

        Returns:
            List of issue dicts with the duplicate date and count.
        """
        date_counts: dict[date, int] = {}
        for d in actual_dates:
            date_counts[d] = date_counts.get(d, 0) + 1

        issues: list[dict[str, Any]] = []
        for d, count in sorted(date_counts.items()):
            if count > 1:
                issues.append({"trading_date": str(d), "count": count})
        return issues

    def _check_non_monotonic_dates(
        self, actual_dates: list[date]
    ) -> list[dict[str, Any]]:
        """Detect non-monotonic (out-of-order) trading_dates.

        Checks that dates appear in non-decreasing order as they appear
        in the records list.

        Returns:
            List of issue dicts with the position and dates that are out of order.
        """
        issues: list[dict[str, Any]] = []
        for i in range(1, len(actual_dates)):
            if actual_dates[i] < actual_dates[i - 1]:
                issues.append(
                    {
                        "position": i,
                        "previous_date": str(actual_dates[i - 1]),
                        "current_date": str(actual_dates[i]),
                    }
                )
        return issues

    def _check_unknown_adjustment(
        self, records: list[OHLCVRecord]
    ) -> list[dict[str, Any]]:
        """Detect records where price_adjustment is UNKNOWN.

        Returns:
            List of issue dicts with the trading_date of affected records.
        """
        issues: list[dict[str, Any]] = []
        for record in records:
            if record.price_adjustment == PriceAdjustment.UNKNOWN:
                issues.append({"trading_date": str(record.trading_date)})
        return issues
