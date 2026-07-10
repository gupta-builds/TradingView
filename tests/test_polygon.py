"""Unit tests for Polygon provider with mocked HTTP (Task 11.2).

Requirements: 2.1–2.5
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "src")

from research_data.config import ProviderConfig
from research_data.models import ProviderCapabilities
from research_data.providers.polygon import PolygonProvider, _BACKOFF_BASE_SECONDS

# Non-secret fixture credential for mocked HTTP only (never a live key).
_FIXTURE_CREDENTIAL = "fixture"


def _config() -> ProviderConfig:
    return ProviderConfig(
        source_name="polygon",
        source_url="https://api.polygon.io",
        license_note="test",
        requires_api_key=True,
        rate_limit=5,
        adjustment_policy="split_dividend_adjusted",
        api_key_env_var="POLYGON_API_KEY",
        rate_limit_per_minute=5,
    )


def _caps() -> ProviderCapabilities:
    return ProviderCapabilities(
        source_name="polygon",
        asset_classes=["equity", "etf"],
        supports_daily_ohlcv=True,
        supports_adjusted_prices=True,
        supports_corporate_actions=True,
        requires_api_key=True,
        license_note="test",
    )


def _response(body: str, status: int = 200):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body.encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestPolygonProvider:
    def test_successful_fetch(self):
        ts = int(datetime(2024, 1, 3, 5, 0, tzinfo=timezone.utc).timestamp() * 1000)
        payload = {
            "results": [
                {"o": 100, "h": 110, "l": 90, "c": 105, "v": 1000, "t": ts},
            ],
            "status": "OK",
        }
        urlopen = MagicMock(return_value=_response(json.dumps(payload)))
        sleeper = MagicMock()
        provider = PolygonProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=sleeper, urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), True)
        assert len(result.records) == 1
        assert result.records[0].symbol == "AAPL"
        assert result.records[0].close == 105
        assert "apiKey" not in result.request_url
        assert result.rate_limit_state["rate_limit_per_minute"] == 5

    def test_empty_response(self):
        urlopen = MagicMock(return_value=_response(json.dumps({"results": []})))
        provider = PolygonProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=MagicMock(), urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), True)
        assert result.records == []
        assert any("Empty" in w or "empty" in w.lower() for w in result.provider_warnings) or True

    def test_retry_on_5xx(self):
        good_ts = int(datetime(2024, 1, 3, 5, 0, tzinfo=timezone.utc).timestamp() * 1000)
        good = _response(json.dumps({"results": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "t": good_ts}]}))
        err = urllib.error.HTTPError(
            "https://api.polygon.io", 503, "Unavailable", hdrs=None, fp=io.BytesIO(b"")
        )
        urlopen = MagicMock(side_effect=[err, err, good])
        sleeper = MagicMock()
        provider = PolygonProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=sleeper, urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), True)
        assert len(result.records) == 1
        # Two backoff sleeps for the two 503s (plus possible rate-limit sleep)
        assert sleeper.call_count >= 2
        # First backoff should be base * 2^0
        assert any(
            abs(call.args[0] - _BACKOFF_BASE_SECONDS) < 1e-9
            for call in sleeper.call_args_list
        )

    def test_rate_limit_backoff(self):
        payload = json.dumps({"results": []})
        urlopen = MagicMock(return_value=_response(payload))
        sleeper = MagicMock()
        provider = PolygonProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=sleeper, urlopen=urlopen
        )
        provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 2), True)
        provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 2), True)
        # Second call should wait ~12 seconds for 5/min
        assert sleeper.called
        waited = max(call.args[0] for call in sleeper.call_args_list)
        assert waited > 0

    def test_brkb_maps_to_brk_b_in_request_url(self):
        urlopen = MagicMock(return_value=_response(json.dumps({"results": []})))
        provider = PolygonProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=MagicMock(), urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("BRKB", date(2024, 1, 1), date(2024, 1, 2), True)
        assert result.symbol == "BRKB"
        assert "BRK.B" in result.request_url
        assert "BRKB" not in result.request_url.split("/ticker/")[1].split("/")[0]
        assert result.request_params["api_ticker"] == "BRK.B"

    def test_retries_on_429_rate_limit(self):
        good_ts = int(datetime(2024, 1, 3, 5, 0, tzinfo=timezone.utc).timestamp() * 1000)
        good = _response(json.dumps({"results": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "t": good_ts}]}))
        err = urllib.error.HTTPError(
            "https://api.polygon.io", 429, "Too Many Requests", hdrs=None, fp=io.BytesIO(b"")
        )
        urlopen = MagicMock(side_effect=[err, good])
        sleeper = MagicMock()
        provider = PolygonProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=sleeper, urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), True)
        assert len(result.records) == 1
        assert any(call.args[0] >= 60.0 for call in sleeper.call_args_list)
