"""Property-based tests for Market Calendar (Property 6).

Property 6: Market Calendar Excludes Non-Trading Days
For any date returned by Market_Calendar as an expected trading session,
that date SHALL NOT be a Saturday, Sunday, or recognized exchange holiday,
and all returned sessions SHALL fall within the requested date range.

**Validates: Requirements 6.2, 6.4**
"""

import sys

sys.path.insert(0, "src")

from datetime import date, timedelta

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from research_data.calendar import MarketCalendar, CalendarError


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate dates within 2020-2025 (well within exchange_calendars bounds)
_MIN_DATE = date(2020, 1, 1)
_MAX_DATE = date(2025, 12, 31)

dates_in_range = st.dates(min_value=_MIN_DATE, max_value=_MAX_DATE)


@st.composite
def date_ranges(draw):
    """Generate valid (start, end) date pairs within 2020-2025."""
    d1 = draw(dates_in_range)
    d2 = draw(dates_in_range)
    start = min(d1, d2)
    end = max(d1, d2)
    # Limit range to at most 365 days to keep tests fast
    if (end - start).days > 365:
        end = start + timedelta(days=365)
    return start, end


# Known NYSE holidays (fixed-date holidays; some are observed on adjacent days)
_KNOWN_HOLIDAYS = {
    # New Year's Day
    date(2020, 1, 1),
    date(2021, 1, 1),
    date(2022, 1, 1),  # Observed Jan 1 is Saturday -> not a holiday on Friday
    date(2023, 1, 2),  # Observed Monday
    date(2024, 1, 1),
    date(2025, 1, 1),
    # Independence Day (July 4)
    date(2020, 7, 3),  # Observed Friday (July 4 is Saturday)
    date(2021, 7, 5),  # Observed Monday (July 4 is Sunday)
    date(2022, 7, 4),
    date(2023, 7, 4),
    date(2024, 7, 4),
    date(2025, 7, 4),
    # Christmas Day (Dec 25)
    date(2020, 12, 25),
    date(2021, 12, 24),  # Observed Friday (Dec 25 is Saturday)
    date(2023, 12, 25),
    date(2024, 12, 25),
    date(2025, 12, 25),
}


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestProperty6MarketCalendarExcludesNonTradingDays:
    """Property 6: Market Calendar Excludes Non-Trading Days.

    **Validates: Requirements 6.2, 6.4**
    """

    @given(data=date_ranges())
    @settings(max_examples=100)
    def test_no_weekends_in_trading_sessions(self, data: tuple[date, date]):
        """Requirement 6.2: No Saturday or Sunday in returned sessions."""
        start, end = data
        calendar = MarketCalendar()

        sessions = calendar.get_trading_sessions("NYSE", start, end)

        for session_date in sessions:
            assert session_date.weekday() not in (5, 6), (
                f"Trading session {session_date} is a "
                f"{'Saturday' if session_date.weekday() == 5 else 'Sunday'}"
            )

    @given(data=date_ranges())
    @settings(max_examples=100)
    def test_all_sessions_within_requested_range(self, data: tuple[date, date]):
        """Requirement 6.4: All returned sessions fall within [start, end]."""
        start, end = data
        calendar = MarketCalendar()

        sessions = calendar.get_trading_sessions("NYSE", start, end)

        for session_date in sessions:
            assert start <= session_date <= end, (
                f"Session {session_date} is outside requested range "
                f"[{start}, {end}]"
            )

    @given(data=date_ranges())
    @settings(max_examples=50)
    def test_known_holidays_excluded(self, data: tuple[date, date]):
        """Requirement 6.2: Known exchange holidays are excluded from sessions."""
        start, end = data
        calendar = MarketCalendar()

        sessions = calendar.get_trading_sessions("NYSE", start, end)
        session_set = set(sessions)

        # Check that any known holidays within the range are NOT in sessions
        for holiday in _KNOWN_HOLIDAYS:
            if start <= holiday <= end:
                assert holiday not in session_set, (
                    f"Known holiday {holiday} was returned as a trading session"
                )

    @given(data=date_ranges())
    @settings(max_examples=50)
    def test_nasdaq_no_weekends(self, data: tuple[date, date]):
        """Requirement 6.2: NASDAQ sessions also exclude weekends."""
        start, end = data
        calendar = MarketCalendar()

        sessions = calendar.get_trading_sessions("NASDAQ", start, end)

        for session_date in sessions:
            assert session_date.weekday() not in (5, 6), (
                f"NASDAQ session {session_date} is a "
                f"{'Saturday' if session_date.weekday() == 5 else 'Sunday'}"
            )

    @given(data=date_ranges())
    @settings(max_examples=50)
    def test_sessions_are_sorted(self, data: tuple[date, date]):
        """Sessions should be returned in chronological order."""
        start, end = data
        calendar = MarketCalendar()

        sessions = calendar.get_trading_sessions("NYSE", start, end)

        for i in range(1, len(sessions)):
            assert sessions[i] > sessions[i - 1], (
                f"Sessions not sorted: {sessions[i-1]} >= {sessions[i]}"
            )
