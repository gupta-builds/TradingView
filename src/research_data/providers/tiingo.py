"""Tiingo daily OHLCV provider.

Fetches end-of-day prices from the Tiingo EOD API with rate limiting and
retry/backoff. Auth is via the ``Authorization: Token <key>`` header (never
a URL query parameter), so ``request_url`` and stored raw payloads are
key-free by construction. Never fabricates data on empty responses.

Tiingo EOD fields used: ``close`` (raw), ``adjClose`` (split+dividend
adjusted), ``divCash``, ``splitFactor`` — see
https://www.tiingo.com/documentation/end-of-day.
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

_DEFAULT_BASE_URL = "https://api.tiingo.com"
_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 2.0

# Canonical universe symbols → Tiingo ticker punctuation.
TIINGO_TICKER_OVERRIDES = {"BRKB": "BRK-B"}


class TiingoProvider:
    """PriceProvider implementation for Tiingo EOD prices.

    Free tier: ~5y history, 50 requests/hour, ``adjClose`` is split+dividend
    adjusted. Env: ``TIINGO_API_KEY``.

    Rate limit: configurable via ``ProviderConfig`` (registry default 50);
    retries up to 3 attempts with exponential backoff for network errors and
    HTTP 5xx, and a ≥60s wait on HTTP 429.
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
        env_name = config.api_key_env_var or "TIINGO_API_KEY"
        self._api_key = api_key or os.environ.get(env_name, "")
        self._base_url = (base_url or config.source_url or _DEFAULT_BASE_URL).rstrip("/")
        self._rate_limit = config.rate_limit_per_minute or config.rate_limit or 50
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
        """Fetch daily OHLCV prices for a symbol from Tiingo.

        Returns zero records (no fabrication) when the API returns an empty
        list or an error payload.
        """
        canonical = symbol.upper()
        api_ticker = TIINGO_TICKER_OVERRIDES.get(canonical, canonical)
        retrieved_at = datetime.now(timezone.utc)
        path = f"/tiingo/daily/{urllib.parse.quote(api_ticker)}/prices"
        params = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "format": "json",
        }
        query = urllib.parse.urlencode(params)
        # Token travels only in the Authorization header, never the URL.
        request_url = f"{self._base_url}{path}?{query}"

        rate_limit_state = self._apply_rate_limit()
        raw_payload, http_status = self._request_with_retries(request_url)

        content_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
        records, warnings = self._parse_payload(
            symbol=canonical,
            raw_payload=raw_payload,
            adjusted=adjusted,
            retrieved_at=retrieved_at,
            content_hash=content_hash,
        )

        if http_status == 200 and not records:
            warnings.append("Empty provider response: zero records returned")

        return ProviderFetchResult(
            symbol=canonical,
            provider=self._config.source_name,
            request_url=request_url,
            request_params={
                "symbol": canonical,
                "api_ticker": api_ticker,
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
        """HTTP GET (header auth) with exponential backoff on network / 5xx errors."""
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(
                    url,
                    method="GET",
                    headers={
                        "Authorization": f"Token {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
                with self._urlopen(req, timeout=30) as resp:
                    status = getattr(resp, "status", 200)
                    body = resp.read()
                    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
                    if status >= 500:
                        raise urllib.error.HTTPError(
                            url, status, f"HTTP {status}", hdrs=None, fp=None
                        )
                    return text, int(status)
            except urllib.error.HTTPError as e:
                last_error = e
                # Retry rate-limit (429) and server errors; fail closed on other 4xx.
                retryable = e.code == 429 or e.code >= 500
                if not retryable or attempt >= _MAX_RETRIES:
                    if e.code == 404:
                        return json.dumps([]), 404
                    raise
                if e.code == 429:
                    self._sleeper(max(60.0, _BACKOFF_BASE_SECONDS * (2**attempt)))
                else:
                    self._sleeper(_BACKOFF_BASE_SECONDS * (2**attempt))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = e
                if attempt >= _MAX_RETRIES:
                    raise
                self._sleeper(_BACKOFF_BASE_SECONDS * (2**attempt))
        raise RuntimeError(f"Tiingo request failed after retries: {last_error}")

    def _parse_payload(
        self,
        symbol: str,
        raw_payload: str,
        adjusted: bool,
        retrieved_at: datetime,
        content_hash: str,
    ) -> tuple[list[OHLCVRecord], list[str]]:
        """Parse Tiingo EOD JSON into OHLCVRecord list.

        Invalid bars are skipped with a warning (no fabrication).
        """
        warnings: list[str] = []
        try:
            data = json.loads(raw_payload) if raw_payload.strip() else []
        except json.JSONDecodeError:
            warnings.append("Malformed JSON payload")
            return [], warnings

        if isinstance(data, dict):
            # Tiingo error responses are a JSON object, e.g. {"detail": "..."}.
            warnings.append(f"Provider error payload: {data.get('detail', data)}")
            return [], warnings

        results = data or []
        if not results:
            return [], warnings

        price_adjustment = (
            PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED if adjusted else PriceAdjustment.RAW
        )
        records: list[OHLCVRecord] = []
        for bar in results:
            try:
                trading_date = date.fromisoformat(str(bar["date"])[:10])
                adj_close = bar.get("adjClose")
                record = OHLCVRecord(
                    symbol=symbol.upper(),
                    asset_type="etf" if symbol.upper() in {"VOO", "VTI", "SPY", "QQQ"} else "equity",
                    exchange=None,
                    trading_date=trading_date,
                    open=float(bar["open"]),
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    adjusted_close=float(adj_close) if adjusted and adj_close is not None else None,
                    volume=int(bar.get("volume") or 0),
                    split_factor=float(bar.get("splitFactor", 1.0)),
                    dividend_cash=float(bar.get("divCash", 0.0)),
                    price_adjustment=price_adjustment,
                    currency="USD",
                    source=self._config.source_name,
                    source_record_id=str(bar.get("date")),
                    retrieved_at=retrieved_at,
                    data_as_of=trading_date,
                    raw_payload_hash=content_hash,
                    quality_status=QualityStatus.USABLE,
                )
                records.append(record)
            except (KeyError, TypeError, ValueError) as e:
                warnings.append(f"Skipped invalid bar: {e}")
        return records, warnings
