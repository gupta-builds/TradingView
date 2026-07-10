"""Market calendar for determining expected trading sessions.

Uses the exchange_calendars package to determine trading sessions for
NYSE and NASDAQ exchanges, accounting for weekends and exchange holidays.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import exchange_calendars as xcals


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CalendarError(Exception):
    """Raised when a calendar operation fails due to unsupported date range or invalid exchange."""

    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mapping from our exchange names to exchange_calendars codes
_EXCHANGE_MAP: dict[str, str] = {
    "NYSE": "XNYS",
    "NASDAQ": "XNAS",
    "XNYS": "XNYS",
    "XNAS": "XNAS",
}

# US Eastern timezone for market close logic
_ET = ZoneInfo("America/New_York")

# Regular market close time (16:00 ET)
_MARKET_CLOSE = time(16, 0)


# ---------------------------------------------------------------------------
# MarketCalendar
# ---------------------------------------------------------------------------


class MarketCalendar:
    """Determines expected trading sessions for US equity exchanges.

    Supports NYSE and NASDAQ exchanges using the exchange_calendars package.
    Provides methods to query trading sessions, compute the latest expected
    session, and identify missing sessions in a date range.
    """

    def __init__(self) -> None:
        """Initialize calendar instances for supported exchanges."""
        self._calendars: dict[str, xcals.ExchangeCalendar] = {}

    def _get_calendar(self, exchange: str) -> xcals.ExchangeCalendar:
        """Get or create a calendar instance for the given exchange.

        Args:
            exchange: Exchange name (NYSE, NASDAQ, XNYS, XNAS).

        Returns:
            An ExchangeCalendar instance.

        Raises:
            CalendarError: If the exchange is not supported.
        """
        exchange_upper = exchange.upper()
        if exchange_upper not in _EXCHANGE_MAP:
            supported = sorted(set(_EXCHANGE_MAP.keys()))
            raise CalendarError(
                f"Unsupported exchange: {exchange!r}. "
                f"Supported exchanges: {supported}"
            )

        xcals_code = _EXCHANGE_MAP[exchange_upper]
        if xcals_code not in self._calendars:
            self._calendars[xcals_code] = xcals.get_calendar(xcals_code)
        return self._calendars[xcals_code]

    def _validate_date_range(
        self, calendar: xcals.ExchangeCalendar, start: date, end: date
    ) -> None:
        """Validate that the requested date range is within the calendar's bounds.

        Raises:
            CalendarError: If the range is outside the calendar's supported range.
        """
        cal_first = calendar.first_session.date()
        cal_last = calendar.last_session.date()

        if start < cal_first or end > cal_last:
            raise CalendarError(
                f"Requested date range ({start} to {end}) is outside the "
                f"calendar's supported range ({cal_first} to {cal_last}). "
                f"Cannot guarantee complete session data for this range."
            )

    def get_trading_sessions(
        self, exchange: str, start: date, end: date
    ) -> list[date]:
        """Return expected trading sessions in the given date range.

        Args:
            exchange: Exchange name (NYSE, NASDAQ, XNYS, XNAS).
            start: Start date (inclusive).
            end: End date (inclusive).

        Returns:
            List of dates that are trading sessions within [start, end].

        Raises:
            CalendarError: If the exchange is unsupported or date range is
                outside the calendar's supported range.
        """
        if start > end:
            return []

        calendar = self._get_calendar(exchange)
        self._validate_date_range(calendar, start, end)

        import pandas as pd

        sessions = calendar.sessions_in_range(
            pd.Timestamp(start), pd.Timestamp(end)
        )
        return [s.date() for s in sessions]

    def get_latest_expected_session(
        self, exchange: str | None = None
    ) -> date:
        """Return the latest expected trading session as of now.

        Logic:
        - If current time is after 16:00 ET on a trading day, today is the
          latest expected session.
        - If current time is before 16:00 ET on a trading day, the latest
          expected session is the previous trading day.
        - If today is not a trading day, the latest expected session is the
          most recent past trading day.

        Args:
            exchange: Exchange name. Defaults to NYSE if not specified.

        Returns:
            The latest expected trading session date.

        Raises:
            CalendarError: If the exchange is unsupported.
        """
        if exchange is None:
            exchange = "NYSE"

        calendar = self._get_calendar(exchange)
        now_et = datetime.now(_ET)
        today = now_et.date()

        import pandas as pd

        today_ts = pd.Timestamp(today)

        # Check if today is a trading day
        if calendar.is_session(today_ts):
            # If after market close, today is the latest expected session
            if now_et.time() >= _MARKET_CLOSE:
                return today
            else:
                # Before close: latest expected is the previous trading day
                prev_session = calendar.previous_session(today_ts)
                return prev_session.date()
        else:
            # Today is not a trading day: find the most recent past trading day
            prev_session = calendar.date_to_session(today_ts, direction="previous")
            return prev_session.date()

    def get_missing_sessions(
        self,
        exchange: str,
        start: date,
        end: date,
        actual_dates: list[date],
    ) -> list[date]:
        """Return trading sessions in the range that are not in actual_dates.

        Args:
            exchange: Exchange name (NYSE, NASDAQ, XNYS, XNAS).
            start: Start date (inclusive).
            end: End date (inclusive).
            actual_dates: List of dates that are actually present in the data.

        Returns:
            List of expected trading sessions that are missing from actual_dates.

        Raises:
            CalendarError: If the exchange is unsupported or date range is
                outside the calendar's supported range.
        """
        expected = self.get_trading_sessions(exchange, start, end)
        actual_set = set(actual_dates)
        return [d for d in expected if d not in actual_set]

    def is_trading_day(self, exchange: str, d: date) -> bool:
        """Check if a given date is a trading day for the exchange.

        Args:
            exchange: Exchange name (NYSE, NASDAQ, XNYS, XNAS).
            d: The date to check.

        Returns:
            True if the date is a trading session, False otherwise.

        Raises:
            CalendarError: If the exchange is unsupported or the date is
                outside the calendar's supported range.
        """
        calendar = self._get_calendar(exchange)

        import pandas as pd

        ts = pd.Timestamp(d)

        # Check if date is within calendar bounds
        cal_first = calendar.first_session.date()
        cal_last = calendar.last_session.date()
        if d < cal_first or d > cal_last:
            raise CalendarError(
                f"Date {d} is outside the calendar's supported range "
                f"({cal_first} to {cal_last})."
            )

        return calendar.is_session(ts)

    def to_trading_date(self, dt: date | datetime, exchange: str | None) -> date:
        """Convert a date/datetime to the exchange-local trading date.

        For naive dates, returns the date unchanged. For datetimes, converts
        to America/New_York before taking the calendar date so bars timestamped
        in UTC map to the correct US equity session date.

        Args:
            dt: A date or datetime value from a provider payload.
            exchange: Exchange name (unused for daily bars; reserved for later).

        Returns:
            The trading date in the exchange timezone.
        """
        _ = exchange  # reserved for multi-exchange timezone mapping
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(_ET).date()
        return dt

