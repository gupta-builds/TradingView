"""Polygon.io daily OHLCV provider.

Fetches end-of-day aggregates from the Polygon stocks API with rate limiting
and retry/backoff. Never fabricates data on empty responses.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

from research_data.config import ProviderConfig
from research_data.models import (
    OHLCVRecord,
    PriceAdjustment,
    ProviderCapabilities,
    ProviderFetchResult,
    QualityStatus,
)


_DEFAULT_BASE_URL = "https://api.polygon.io"
_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 2.0


class PolygonProvider:
    """PriceProvider implementation for Polygon Basic EOD aggregates.

    Rate limit: 5 calls/minute on the free tier (configurable via ProviderConfig).
    Retries: up to 3 attempts with exponential backoff starting at 2 seconds
    for network errors and HTTP 5xx responses.
    """

    def __init__(
        self,
        config: ProviderConfig,
        capabilities: ProviderCapabilities,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        sleeper: Any = None,
        urlopen: Any = None,
    ) -> None:
        self.capabilities = capabilities
        self._config = config
        self._api_key = api_key or os.environ.get(config.api_key_env_var or "POLYGON_API_KEY", "")
        self._base_url = (base_url or config.source_url or _DEFAULT_BASE_URL).rstrip("/")
        self._rate_limit = config.rate_limit_per_minute or config.rate_limit or 5
        self._min_interval = 60.0 / self._rate_limit if self._rate_limit > 0 else 0.0
        self._last_call_at: float | None = None
        self._sleeper = sleeper or time.sleep
        self._urlopen = urlopen or urllib.request.urlopen
        self._calls_made = 0

    def fetch_daily_ohlcv(
        self,
        symbol: str,
        start: date,
        end: date,
        adjusted: bool,
    ) -> ProviderFetchResult:
        """Fetch daily OHLCV aggregates for a symbol from Polygon.

        Returns zero records (no fabrication) when the API returns an empty
        results list or a 404-style empty payload.
        """
        retrieved_at = datetime.now(timezone.utc)
        path = (
            f"/v2/aggs/ticker/{urllib.parse.quote(symbol)}/range/1/day/"
            f"{start.isoformat()}/{end.isoformat()}"
        )
        params = {
            "adjusted": "true" if adjusted else "false",
            "sort": "asc",
            "limit": "50000",
            "apiKey": self._api_key,
        }
        query = urllib.parse.urlencode(params)
        request_url = f"{self._base_url}{path}?{query}"
        # Redacted URL for storage (no api key)
        redacted_url = f"{self._base_url}{path}?{urllib.parse.urlencode({k: v for k, v in params.items() if k != 'apiKey'})}"

        rate_limit_state = self._apply_rate_limit()
        raw_payload, http_status = self._request_with_retries(request_url)

        content_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
        records, warnings = self._parse_payload(
            symbol=symbol,
            raw_payload=raw_payload,
            adjusted=adjusted,
            retrieved_at=retrieved_at,
            content_hash=content_hash,
        )

        if http_status == 200 and not records:
            warnings.append("Empty provider response: zero records returned")

        return ProviderFetchResult(
            symbol=symbol,
            provider=self._config.source_name,
            request_url=redacted_url,
            request_params={
                "symbol": symbol,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "adjusted": adjusted,
            },
            retrieved_at=retrieved_at,
            raw_payload=raw_payload,
            content_hash=content_hash,
            records=records,
            provider_warnings=warnings,
            rate_limit_state=rate_limit_state,
        )

    def _apply_rate_limit(self) -> dict[str, Any]:
        """Sleep if needed to respect calls-per-minute limit."""
        now = time.monotonic()
        waited = 0.0
        if self._last_call_at is not None and self._min_interval > 0:
            elapsed = now - self._last_call_at
            if elapsed < self._min_interval:
                waited = self._min_interval - elapsed
                self._sleeper(waited)
        self._last_call_at = time.monotonic()
        self._calls_made += 1
        remaining = max(0, self._rate_limit - (self._calls_made % max(self._rate_limit, 1)))
        return {
            "calls_made": self._calls_made,
            "rate_limit_per_minute": self._rate_limit,
            "waited_seconds": waited,
            "remaining_estimate": remaining,
        }

    def _request_with_retries(self, url: str) -> tuple[str, int]:
        """HTTP GET with exponential backoff on network / 5xx errors."""
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(url, method="GET")
                with self._urlopen(req, timeout=30) as resp:
                    status = getattr(resp, "status", 200)
                    body = resp.read()
                    if isinstance(body, bytes):
                        text = body.decode("utf-8")
                    else:
                        text = str(body)
                    if status >= 500:
                        raise urllib.error.HTTPError(
                            url, status, f"HTTP {status}", hdrs=None, fp=None
                        )
                    return text, int(status)
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code < 500 or attempt >= _MAX_RETRIES:
                    if e.code == 404:
                        return json.dumps({"results": [], "status": "NOT_FOUND"}), 404
                    raise
                self._sleeper(_BACKOFF_BASE_SECONDS * (2**attempt))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = e
                if attempt >= _MAX_RETRIES:
                    raise
                self._sleeper(_BACKOFF_BASE_SECONDS * (2**attempt))
        raise RuntimeError(f"Polygon request failed after retries: {last_error}")

    def _parse_payload(
        self,
        symbol: str,
        raw_payload: str,
        adjusted: bool,
        retrieved_at: datetime,
        content_hash: str,
    ) -> tuple[list[OHLCVRecord], list[str]]:
        """Parse Polygon aggregates JSON into OHLCVRecord list.

        Invalid bars are skipped with a warning (no fabrication).
        """
        warnings: list[str] = []
        try:
            data = json.loads(raw_payload) if raw_payload.strip() else {}
        except json.JSONDecodeError:
            warnings.append("Malformed JSON payload")
            return [], warnings

        results = data.get("results") or []
        if not results:
            return [], warnings

        price_adjustment = (
            PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED
            if adjusted
            else PriceAdjustment.RAW
        )
        records: list[OHLCVRecord] = []
        for bar in results:
            try:
                trading_date = datetime.fromtimestamp(
                    bar["t"] / 1000.0, tz=timezone.utc
                ).date()
                record = OHLCVRecord(
                    symbol=symbol.upper(),
                    asset_type="etf" if symbol.upper() in {"VOO", "VTI", "SPY", "QQQ"} else "equity",
                    exchange=None,
                    trading_date=trading_date,
                    open=float(bar["o"]),
                    high=float(bar["h"]),
                    low=float(bar["l"]),
                    close=float(bar["c"]),
                    adjusted_close=float(bar["c"]) if adjusted else None,
                    volume=int(bar.get("v", 0)),
                    split_factor=1.0,
                    dividend_cash=0.0,
                    price_adjustment=price_adjustment,
                    currency="USD",
                    source=self._config.source_name,
                    source_record_id=str(bar.get("t")),
                    retrieved_at=retrieved_at,
                    data_as_of=trading_date,
                    raw_payload_hash=content_hash,
                    quality_status=QualityStatus.USABLE,
                )
                records.append(record)
            except (KeyError, TypeError, ValueError) as e:
                warnings.append(f"Skipped invalid bar: {e}")
        return records, warnings
