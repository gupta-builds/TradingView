"""Unit tests for the market calendar module (Task 6.5).

Covers:
- get_trading_sessions excludes weekends
- get_trading_sessions excludes known holidays (e.g., 2024-01-01, 2024-12-25)
- get_latest_expected_session returns correct date (mocked time)
- is_trading_day returns False for weekends
- CalendarError raised for unsupported date ranges
- get_missing_sessions identifies gaps correctly

Requirements: 6.1–6.5
"""

import sys

sys.path.insert(0, "src")

from datetime import date, datetime, time
from unittest.mock import patch

import pytest

from research_data.calendar import CalendarError, MarketCalendar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def calendar():
    """Create a MarketCalendar instance for tests."""
    return MarketCalendar()


# ===========================================================================
# 1. get_trading_sessions excludes weekends
# ===========================================================================


class TestTradingSessionsExcludesWeekends:
    """Test that get_trading_sessions never returns Saturday or Sunday."""

    def test_week_with_no_holidays(self, calendar):
        """A normal week (Mon-Fri) should return 5 sessions, no weekends."""
        # 2024-03-11 is Monday, 2024-03-17 is Sunday
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 3, 11), date(2024, 3, 17))

        for session in sessions:
            assert session.weekday() < 5, f"{session} is a weekend day"

        # Should have exactly 5 trading days (Mon-Fri)
        assert len(sessions) == 5

    def test_two_weeks_no_holidays(self, calendar):
        """Two full weeks should return 10 sessions."""
        # 2024-03-04 (Mon) to 2024-03-15 (Fri)
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 3, 4), date(2024, 3, 15))

        for session in sessions:
            assert session.weekday() < 5, f"{session} is a weekend day"

        assert len(sessions) == 10

    def test_weekend_only_range_returns_empty(self, calendar):
        """A range covering only Saturday and Sunday should return no sessions."""
        # 2024-03-16 is Saturday, 2024-03-17 is Sunday
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 3, 16), date(2024, 3, 17))
        assert sessions == []

    def test_single_saturday_returns_empty(self, calendar):
        """A single Saturday should return no sessions."""
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 3, 16), date(2024, 3, 16))
        assert sessions == []

    def test_single_sunday_returns_empty(self, calendar):
        """A single Sunday should return no sessions."""
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 3, 17), date(2024, 3, 17))
        assert sessions == []


# ===========================================================================
# 2. get_trading_sessions excludes known holidays
# ===========================================================================


class TestTradingSessionsExcludesHolidays:
    """Test that get_trading_sessions excludes known exchange holidays."""

    def test_new_years_day_excluded(self, calendar):
        """New Year's Day (2024-01-01) should not be a trading session."""
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 1, 1), date(2024, 1, 5))
        session_dates = set(sessions)
        assert date(2024, 1, 1) not in session_dates

    def test_christmas_excluded(self, calendar):
        """Christmas Day (2024-12-25) should not be a trading session."""
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 12, 23), date(2024, 12, 27))
        session_dates = set(sessions)
        assert date(2024, 12, 25) not in session_dates

    def test_mlk_day_excluded(self, calendar):
        """MLK Day (2024-01-15) should not be a trading session."""
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 1, 15), date(2024, 1, 19))
        session_dates = set(sessions)
        assert date(2024, 1, 15) not in session_dates

    def test_independence_day_excluded(self, calendar):
        """Independence Day (2024-07-04) should not be a trading session."""
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 7, 1), date(2024, 7, 5))
        session_dates = set(sessions)
        assert date(2024, 7, 4) not in session_dates

    def test_thanksgiving_excluded(self, calendar):
        """Thanksgiving (2024-11-28) should not be a trading session."""
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 11, 25), date(2024, 11, 29))
        session_dates = set(sessions)
        assert date(2024, 11, 28) not in session_dates

    def test_holiday_week_has_fewer_sessions(self, calendar):
        """A week with a holiday should have fewer than 5 sessions."""
        # Week of July 4, 2024 (Thursday is holiday)
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 7, 1), date(2024, 7, 5))
        assert len(sessions) < 5


# ===========================================================================
# 3. get_latest_expected_session returns correct date (mocked time)
# ===========================================================================


class TestLatestExpectedSession:
    """Test get_latest_expected_session logic around 16:00 ET."""

    def test_after_close_on_trading_day_returns_today(self, calendar):
        """After 16:00 ET on a trading day, latest expected session is today."""
        # 2024-03-15 is a Friday (trading day)
        # Mock time to 17:00 ET
        from zoneinfo import ZoneInfo

        mock_now = datetime(2024, 3, 15, 17, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("research_data.calendar.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now

            result = calendar.get_latest_expected_session("NYSE")
            assert result == date(2024, 3, 15)

    def test_before_close_on_trading_day_returns_previous(self, calendar):
        """Before 16:00 ET on a trading day, latest expected session is previous trading day."""
        # 2024-03-15 is a Friday (trading day)
        # Mock time to 10:00 ET (before close)
        from zoneinfo import ZoneInfo

        mock_now = datetime(2024, 3, 15, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("research_data.calendar.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now

            result = calendar.get_latest_expected_session("NYSE")
            # Previous trading day to Friday 2024-03-15 is Thursday 2024-03-14
            assert result == date(2024, 3, 14)

    def test_on_weekend_returns_previous_friday(self, calendar):
        """On a weekend, latest expected session is the previous Friday."""
        # 2024-03-16 is Saturday
        from zoneinfo import ZoneInfo

        mock_now = datetime(2024, 3, 16, 12, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("research_data.calendar.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now

            result = calendar.get_latest_expected_session("NYSE")
            # Previous trading day to Saturday is Friday 2024-03-15
            assert result == date(2024, 3, 15)

    def test_on_holiday_returns_previous_trading_day(self, calendar):
        """On a holiday, latest expected session is the previous trading day."""
        # 2024-01-01 is New Year's Day (Monday holiday)
        from zoneinfo import ZoneInfo

        mock_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("research_data.calendar.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now

            result = calendar.get_latest_expected_session("NYSE")
            # Previous trading day to 2024-01-01 is 2023-12-29 (Friday)
            assert result == date(2023, 12, 29)

    def test_defaults_to_nyse(self, calendar):
        """When no exchange specified, should default to NYSE."""
        # Just verify it doesn't raise an error
        result = calendar.get_latest_expected_session()
        assert isinstance(result, date)

    def test_exactly_at_close_returns_today(self, calendar):
        """At exactly 16:00 ET on a trading day, today is the latest expected session."""
        # 2024-03-15 is a Friday (trading day)
        from zoneinfo import ZoneInfo

        mock_now = datetime(2024, 3, 15, 16, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("research_data.calendar.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now

            result = calendar.get_latest_expected_session("NYSE")
            assert result == date(2024, 3, 15)


# ===========================================================================
# 4. is_trading_day returns False for weekends
# ===========================================================================


class TestIsTradingDay:
    """Test is_trading_day correctly identifies non-trading days."""

    def test_saturday_is_not_trading_day(self, calendar):
        """Saturday should not be a trading day."""
        assert calendar.is_trading_day("NYSE", date(2024, 3, 16)) is False

    def test_sunday_is_not_trading_day(self, calendar):
        """Sunday should not be a trading day."""
        assert calendar.is_trading_day("NYSE", date(2024, 3, 17)) is False

    def test_monday_is_trading_day(self, calendar):
        """A regular Monday should be a trading day."""
        # 2024-03-18 is Monday (not a holiday)
        assert calendar.is_trading_day("NYSE", date(2024, 3, 18)) is True

    def test_friday_is_trading_day(self, calendar):
        """A regular Friday should be a trading day."""
        # 2024-03-15 is Friday (not a holiday)
        assert calendar.is_trading_day("NYSE", date(2024, 3, 15)) is True

    def test_holiday_is_not_trading_day(self, calendar):
        """A known holiday should not be a trading day."""
        # 2024-07-04 is Independence Day (Thursday)
        assert calendar.is_trading_day("NYSE", date(2024, 7, 4)) is False

    def test_nasdaq_weekends_not_trading(self, calendar):
        """NASDAQ also doesn't trade on weekends."""
        assert calendar.is_trading_day("NASDAQ", date(2024, 3, 16)) is False
        assert calendar.is_trading_day("NASDAQ", date(2024, 3, 17)) is False


# ===========================================================================
# 5. CalendarError raised for unsupported date ranges
# ===========================================================================


class TestCalendarErrorUnsupportedRange:
    """Test that CalendarError is raised for unsupported date ranges."""

    def test_very_old_date_raises_error(self, calendar):
        """A date before the calendar's supported range should raise CalendarError."""
        with pytest.raises(CalendarError, match="outside.*supported range"):
            calendar.get_trading_sessions("NYSE", date(1800, 1, 1), date(1800, 12, 31))

    def test_far_future_date_raises_error(self, calendar):
        """A date far in the future beyond calendar range should raise CalendarError."""
        with pytest.raises(CalendarError, match="outside.*supported range"):
            calendar.get_trading_sessions("NYSE", date(2200, 1, 1), date(2200, 12, 31))

    def test_unsupported_exchange_raises_error(self, calendar):
        """An unsupported exchange should raise CalendarError."""
        with pytest.raises(CalendarError, match="[Uu]nsupported"):
            calendar.get_trading_sessions("TOKYO", date(2024, 1, 1), date(2024, 1, 31))

    def test_is_trading_day_unsupported_range(self, calendar):
        """is_trading_day should raise CalendarError for dates outside supported range."""
        with pytest.raises(CalendarError, match="outside.*supported range"):
            calendar.is_trading_day("NYSE", date(1800, 6, 15))

    def test_start_after_end_returns_empty(self, calendar):
        """When start > end, should return empty list (not an error)."""
        sessions = calendar.get_trading_sessions("NYSE", date(2024, 3, 15), date(2024, 3, 10))
        assert sessions == []


# ===========================================================================
# 6. get_missing_sessions identifies gaps correctly
# ===========================================================================


class TestGetMissingSessions:
    """Test that get_missing_sessions correctly identifies gaps in data."""

    def test_no_gaps_returns_empty(self, calendar):
        """When all expected sessions are present, missing should be empty."""
        # Get expected sessions for a week
        start = date(2024, 3, 11)  # Monday
        end = date(2024, 3, 15)  # Friday
        expected = calendar.get_trading_sessions("NYSE", start, end)

        # All sessions present
        missing = calendar.get_missing_sessions("NYSE", start, end, expected)
        assert missing == []

    def test_all_missing_returns_all_expected(self, calendar):
        """When no actual dates provided, all expected sessions are missing."""
        start = date(2024, 3, 11)  # Monday
        end = date(2024, 3, 15)  # Friday

        missing = calendar.get_missing_sessions("NYSE", start, end, [])
        expected = calendar.get_trading_sessions("NYSE", start, end)
        assert missing == expected
        assert len(missing) == 5

    def test_partial_gap_identified(self, calendar):
        """When some sessions are missing, they should be identified."""
        start = date(2024, 3, 11)  # Monday
        end = date(2024, 3, 15)  # Friday

        # Only have Monday and Friday data
        actual = [date(2024, 3, 11), date(2024, 3, 15)]
        missing = calendar.get_missing_sessions("NYSE", start, end, actual)

        # Should be missing Tue, Wed, Thu
        assert date(2024, 3, 12) in missing
        assert date(2024, 3, 13) in missing
        assert date(2024, 3, 14) in missing
        assert len(missing) == 3

    def test_extra_dates_in_actual_ignored(self, calendar):
        """Extra dates in actual_dates that aren't expected sessions are ignored."""
        start = date(2024, 3, 11)  # Monday
        end = date(2024, 3, 15)  # Friday

        expected = calendar.get_trading_sessions("NYSE", start, end)
        # Include a weekend date in actual (shouldn't affect result)
        actual = expected + [date(2024, 3, 16)]  # Saturday

        missing = calendar.get_missing_sessions("NYSE", start, end, actual)
        assert missing == []

    def test_missing_sessions_excludes_holidays(self, calendar):
        """Holidays should not appear in missing sessions."""
        # Week of July 4, 2024
        start = date(2024, 7, 1)  # Monday
        end = date(2024, 7, 5)  # Friday

        # Provide data for all trading days except July 4 (which is a holiday)
        actual = [date(2024, 7, 1), date(2024, 7, 2), date(2024, 7, 3), date(2024, 7, 5)]
        missing = calendar.get_missing_sessions("NYSE", start, end, actual)

        # July 4 is a holiday, so it shouldn't be in missing
        assert date(2024, 7, 4) not in missing
        assert missing == []

    def test_supports_five_years_history(self, calendar):
        """Calendar should support at least 5 years of historical sessions."""
        # 5 years back from 2024
        start = date(2019, 1, 2)
        end = date(2024, 1, 2)

        sessions = calendar.get_trading_sessions("NYSE", start, end)
        # Should have roughly 252 sessions per year * 5 = ~1260
        assert len(sessions) > 1200
        assert len(sessions) < 1300

        # All should be weekdays
        for session in sessions:
            assert session.weekday() < 5
