"""Financial Modeling Prep fundamentals client.

Pure parsing (offline-testable) + a thin live client. The API key is read
from the environment at call time, appended to the request URL for the call
only, and never stored: ``request_urls`` in results are key-free.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from research_data.fundamentals.models import (
    FundamentalsFetchResult,
    FundamentalsSnapshot,
)

FMP_BASE_URL = "https://financialmodelingprep.com/stable"
API_KEY_ENV_VAR = "FMP_API_KEY"
# Path segment → query-style stable endpoints (post Aug 2025; /api/v3 is legacy-only).
_STATEMENTS = ("income-statement", "balance-sheet-statement", "cash-flow-statement")
# Canonical universe → FMP ticker punctuation.
FMP_TICKER_OVERRIDES = {"BRKB": "BRK.B"}


class FMPError(Exception):
    """Raised when the FMP client cannot fetch or parse fundamentals."""


def parse_fmp_statements(
    symbol: str,
    income_json: str,
    balance_json: str,
    cashflow_json: str,
    retrieved_at: datetime,
    source: str = "fmp",
) -> list[FundamentalsSnapshot]:
    """Merge FMP income/balance/cash-flow statements into snapshots by period.

    Only fields present in the payloads are set; anything absent stays None.
    Periods missing from any statement produce a snapshot with the fields
    that exist — never estimated ones.
    """
    payload_hash = hashlib.sha256(
        (income_json + balance_json + cashflow_json).encode("utf-8")
    ).hexdigest()

    def load(raw: str, label: str) -> list[dict]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise FMPError(f"Invalid JSON in FMP {label} payload: {e}") from e
        if not isinstance(data, list):
            raise FMPError(f"Unexpected FMP {label} payload shape: expected a list")
        return data

    by_period: dict[tuple[str, str], dict[str, dict]] = {}
    for label, raw in (
        ("income", income_json),
        ("balance", balance_json),
        ("cashflow", cashflow_json),
    ):
        for entry in load(raw, label):
            key = (str(entry.get("date", "")), str(entry.get("period", "")))
            if not key[0]:
                continue
            by_period.setdefault(key, {})[label] = entry

    snapshots: list[FundamentalsSnapshot] = []
    for (period_end, period_label), parts in sorted(by_period.items()):
        income = parts.get("income", {})
        balance = parts.get("balance", {})
        cashflow = parts.get("cashflow", {})
        period_type = "annual" if period_label.upper() == "FY" else "quarter"
        capex = _num(cashflow.get("capitalExpenditure"))
        snapshots.append(
            FundamentalsSnapshot(
                symbol=symbol,
                source=source,
                period_type=period_type,
                fiscal_period_end=date.fromisoformat(period_end),
                retrieved_at=retrieved_at,
                raw_payload_hash=payload_hash,
                currency=str(income.get("reportedCurrency") or "USD"),
                revenue=_num(income.get("revenue")),
                operating_income=_num(income.get("operatingIncome")),
                operating_cash_flow=_num(cashflow.get("operatingCashFlow")),
                capex=abs(capex) if capex is not None else None,
                total_debt=_num(balance.get("totalDebt")),
                cash_and_equivalents=_num(balance.get("cashAndCashEquivalents")),
                total_equity=_num(balance.get("totalStockholdersEquity")),
                shares_outstanding=_num(income.get("weightedAverageShsOut")),
            )
        )
    return snapshots


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class FMPFundamentalsClient:
    """Thin live client. Requires FMP_API_KEY in the environment."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    def fetch_statements(
        self, symbol: str, period: str = "quarter", limit: int = 8
    ) -> FundamentalsFetchResult:
        """Fetch income/balance/cash-flow statements and parse to snapshots."""
        api_key = os.environ.get(API_KEY_ENV_VAR)
        if not api_key:
            raise FMPError(
                f"{API_KEY_ENV_VAR} is not set; cannot fetch FMP fundamentals. "
                "Offline paths must use fixtures instead."
            )
        retrieved_at = datetime.now(timezone.utc)
        raw: dict[str, str] = {}
        clean_urls: list[str] = []
        warnings: list[str] = []
        api_symbol = FMP_TICKER_OVERRIDES.get(symbol.upper(), symbol.upper())
        for statement in _STATEMENTS:
            params = {
                "symbol": api_symbol,
                "period": period,
                "limit": str(limit),
            }
            clean_url = (
                f"{FMP_BASE_URL}/{statement}"
                f"?{urllib.parse.urlencode(params)}"
            )
            clean_urls.append(clean_url)  # stored metadata: no credentials
            live_params = {**params, "apikey": api_key}
            request_url = (
                f"{FMP_BASE_URL}/{statement}"
                f"?{urllib.parse.urlencode(live_params)}"
            )
            request = urllib.request.Request(
                request_url, headers={"Accept": "application/json"}
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    raw[statement] = response.read().decode("utf-8")
            except OSError as e:
                raise FMPError(f"FMP request failed for {clean_url}: {e}") from e

        snapshots = parse_fmp_statements(
            symbol.upper(),
            raw["income-statement"],
            raw["balance-sheet-statement"],
            raw["cash-flow-statement"],
            retrieved_at,
        )
        if not snapshots:
            warnings.append(
                f"FMP returned no statement periods for {symbol}; "
                "surfacing empty result (no fabrication)."
            )
        return FundamentalsFetchResult(
            symbol=symbol,
            source="fmp",
            retrieved_at=retrieved_at,
            request_urls=clean_urls,
            raw_payloads=raw,
            snapshots=snapshots,
            warnings=warnings,
        )
