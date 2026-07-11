"""Unit tests for Tiingo provider with mocked HTTP (mirrors test_polygon.py).

Requirements: 2.1-2.5 (provider contract parity)
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from datetime import date
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "src")

from research_data.config import ProviderConfig
from research_data.models import ProviderCapabilities
from research_data.providers.tiingo import TiingoProvider, _BACKOFF_BASE_SECONDS

# Non-secret fixture credential for mocked HTTP only (never a live key).
_FIXTURE_CREDENTIAL = "fixture"


def _config() -> ProviderConfig:
    return ProviderConfig(
        source_name="tiingo",
        source_url="https://api.tiingo.com",
        license_note="test",
        requires_api_key=True,
        rate_limit=50,
        adjustment_policy="split_dividend_adjusted",
        api_key_env_var="TIINGO_API_KEY",
        rate_limit_per_minute=50,
    )


def _caps() -> ProviderCapabilities:
    return ProviderCapabilities(
        source_name="tiingo",
        asset_classes=["equity", "etf"],
        supports_daily_ohlcv=True,
        supports_adjusted_prices=True,
        supports_corporate_actions=False,
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


class TestTiingoProvider:
    def test_successful_fetch(self):
        payload = [
            {
                "date": "2024-01-03T00:00:00+00:00",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "adjClose": 104.5,
                "volume": 1000,
                "divCash": 0.0,
                "splitFactor": 1.0,
            }
        ]
        urlopen = MagicMock(return_value=_response(json.dumps(payload)))
        sleeper = MagicMock()
        provider = TiingoProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=sleeper, urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), True)
        assert len(result.records) == 1
        assert result.records[0].symbol == "AAPL"
        assert result.records[0].close == 105
        assert result.records[0].adjusted_close == 104.5
        assert _FIXTURE_CREDENTIAL not in result.request_url
        assert result.rate_limit_state["rate_limit_per_minute"] == 50

    def test_credential_not_in_request_url(self):
        """The credential must never appear in request_url (it travels via a request header)."""
        urlopen = MagicMock(return_value=_response(json.dumps([])))
        provider = TiingoProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=MagicMock(), urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), True)
        assert _FIXTURE_CREDENTIAL not in result.request_url
        sent_request = urlopen.call_args[0][0]
        header_names = {h.lower() for h in sent_request.headers}
        assert "authorization" in header_names

    def test_empty_response(self):
        urlopen = MagicMock(return_value=_response(json.dumps([])))
        provider = TiingoProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=MagicMock(), urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), True)
        assert result.records == []
        assert any("mpty" in w for w in result.provider_warnings)

    def test_error_payload_object_not_fabricated(self):
        """Tiingo error responses are a JSON object (e.g. {'detail': ...}), not a list."""
        urlopen = MagicMock(return_value=_response(json.dumps({"detail": "Not found"})))
        provider = TiingoProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=MagicMock(), urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("ZZZZ", date(2024, 1, 1), date(2024, 1, 31), True)
        assert result.records == []
        assert any("error payload" in w.lower() for w in result.provider_warnings)

    def test_retry_on_5xx(self):
        good = _response(
            json.dumps(
                [{"date": "2024-01-03", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "adjClose": 1.5, "volume": 10}]
            )
        )
        err = urllib.error.HTTPError(
            "https://api.tiingo.com", 503, "Unavailable", hdrs=None, fp=io.BytesIO(b"")
        )
        urlopen = MagicMock(side_effect=[err, err, good])
        sleeper = MagicMock()
        provider = TiingoProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=sleeper, urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), True)
        assert len(result.records) == 1
        assert sleeper.call_count >= 2
        assert any(
            abs(call.args[0] - _BACKOFF_BASE_SECONDS) < 1e-9 for call in sleeper.call_args_list
        )

    def test_retries_on_429_rate_limit(self):
        good = _response(
            json.dumps(
                [{"date": "2024-01-03", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "adjClose": 1.5, "volume": 10}]
            )
        )
        err = urllib.error.HTTPError(
            "https://api.tiingo.com", 429, "Too Many Requests", hdrs=None, fp=io.BytesIO(b"")
        )
        urlopen = MagicMock(side_effect=[err, good])
        sleeper = MagicMock()
        provider = TiingoProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=sleeper, urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), True)
        assert len(result.records) == 1
        assert any(call.args[0] >= 60.0 for call in sleeper.call_args_list)

    def test_brkb_maps_to_brk_dash_b_in_request_url(self):
        urlopen = MagicMock(return_value=_response(json.dumps([])))
        provider = TiingoProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=MagicMock(), urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("BRKB", date(2024, 1, 1), date(2024, 1, 2), True)
        assert result.symbol == "BRKB"
        assert "BRK-B" in result.request_url
        assert result.request_params["api_ticker"] == "BRK-B"

    def test_unadjusted_request_leaves_adjusted_close_none(self):
        payload = [
            {
                "date": "2024-01-03",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "adjClose": 104.5,
                "volume": 1000,
            }
        ]
        urlopen = MagicMock(return_value=_response(json.dumps(payload)))
        provider = TiingoProvider(
            _config(), _caps(), api_key=_FIXTURE_CREDENTIAL, sleeper=MagicMock(), urlopen=urlopen
        )
        result = provider.fetch_daily_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), False)
        assert result.records[0].adjusted_close is None
        assert result.records[0].price_adjustment.value == "raw"
