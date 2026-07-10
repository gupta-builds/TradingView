"""SEC EDGAR companyfacts client.

Free, keyless, but identity-required: every request carries the User-Agent
from SEC_USER_AGENT (format "AppName your.email@example.com") per SEC
fair-access policy, with a polite minimum interval between requests.

Parsing is pure (offline-testable) over the companyfacts JSON shape:
us-gaap/dei concepts → the minimal field set the quality factor needs.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from datetime import date, datetime, timezone

from research_data.fundamentals.models import (
    FundamentalsFetchResult,
    FundamentalsSnapshot,
)

SEC_USER_AGENT_ENV_VAR = "SEC_USER_AGENT"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:0>10}.json"

#: SEC fair-access: stay well under 10 requests/second.
MIN_REQUEST_INTERVAL_SECONDS = 0.15

#: Canonical letters-only symbols → SEC ticker punctuation.
SEC_TICKER_OVERRIDES = {"BRKB": "BRK-B"}

# us-gaap concept fallbacks, first hit wins.
_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    "total_debt": ("LongTermDebt", "LongTermDebtNoncurrent"),
    "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
    "total_equity": ("StockholdersEquity",),
}


class SECEdgarError(Exception):
    """Raised when the SEC client cannot fetch or parse companyfacts."""


def parse_companyfacts(
    symbol: str,
    companyfacts_json: str,
    retrieved_at: datetime,
    max_periods: int = 12,
    source: str = "sec_edgar",
) -> list[FundamentalsSnapshot]:
    """Extract per-period snapshots from a companyfacts payload.

    Facts are grouped by (fiscal period end, form type): 10-K FY entries make
    annual snapshots, 10-Q entries quarterly ones. Duration concepts (revenue,
    cash flow) use their period ``end``; instant concepts (debt, cash, equity)
    attach to the same end date. Fields the filer did not tag stay None.
    """
    try:
        data = json.loads(companyfacts_json)
    except json.JSONDecodeError as e:
        raise SECEdgarError(f"Invalid companyfacts JSON: {e}") from e

    payload_hash = hashlib.sha256(companyfacts_json.encode("utf-8")).hexdigest()
    gaap = data.get("facts", {}).get("us-gaap", {})
    dei = data.get("facts", {}).get("dei", {})

    periods: dict[tuple[str, str], dict[str, float]] = {}

    def collect(concept_data: dict, field_name: str) -> None:
        units = concept_data.get("units", {})
        entries = units.get("USD") or units.get("shares") or []
        for entry in entries:
            end = entry.get("end")
            form = str(entry.get("form", ""))
            value = entry.get("val")
            if not end or value is None:
                continue
            if form not in ("10-K", "10-Q"):
                continue
            fp = str(entry.get("fp", ""))
            period_type = "annual" if form == "10-K" and fp == "FY" else "quarter"
            # For duration concepts, an annual 10-K entry spans the full year;
            # keep quarterly and annual periods separate.
            key = (end, period_type)
            periods.setdefault(key, {})[field_name] = float(value)

    for field_name, concept_names in _CONCEPTS.items():
        for concept in concept_names:
            if concept in gaap:
                collect(gaap[concept], field_name)
                break

    shares_concept = dei.get("EntityCommonStockSharesOutstanding")
    if shares_concept:
        collect(shares_concept, "shares_outstanding")

    snapshots: list[FundamentalsSnapshot] = []
    for (end, period_type), fields in sorted(periods.items())[-max_periods:]:
        capex = fields.get("capex")
        snapshots.append(
            FundamentalsSnapshot(
                symbol=symbol,
                source=source,
                period_type=period_type,  # type: ignore[arg-type]
                fiscal_period_end=date.fromisoformat(end),
                retrieved_at=retrieved_at,
                raw_payload_hash=payload_hash,
                revenue=fields.get("revenue"),
                operating_income=fields.get("operating_income"),
                operating_cash_flow=fields.get("operating_cash_flow"),
                capex=abs(capex) if capex is not None else None,
                total_debt=fields.get("total_debt"),
                cash_and_equivalents=fields.get("cash_and_equivalents"),
                total_equity=fields.get("total_equity"),
                shares_outstanding=fields.get("shares_outstanding"),
            )
        )
    return snapshots


class SECEdgarClient:
    """Thin live client. Requires SEC_USER_AGENT in the environment."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds
        self._last_request_time = 0.0
        self._ticker_to_cik: dict[str, int] | None = None

    def _user_agent(self) -> str:
        user_agent = os.environ.get(SEC_USER_AGENT_ENV_VAR, "").strip()
        if not user_agent:
            raise SECEdgarError(
                f"{SEC_USER_AGENT_ENV_VAR} is not set. SEC fair-access policy "
                "requires an identifying User-Agent "
                "(format: 'AppName your.email@example.com')."
            )
        return user_agent

    def _get(self, url: str) -> str:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self._user_agent(), "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read().decode("utf-8")
        except OSError as e:
            raise SECEdgarError(f"SEC request failed for {url}: {e}") from e
        finally:
            self._last_request_time = time.monotonic()
        return body

    def get_cik(self, symbol: str) -> int:
        """Resolve a canonical symbol to its SEC CIK via company_tickers.json."""
        sec_ticker = SEC_TICKER_OVERRIDES.get(symbol, symbol)
        if self._ticker_to_cik is None:
            raw = self._get(COMPANY_TICKERS_URL)
            try:
                listing = json.loads(raw)
            except json.JSONDecodeError as e:
                raise SECEdgarError(f"Invalid company_tickers.json: {e}") from e
            self._ticker_to_cik = {
                str(entry["ticker"]).upper(): int(entry["cik_str"])
                for entry in listing.values()
            }
        cik = self._ticker_to_cik.get(sec_ticker.upper())
        if cik is None:
            raise SECEdgarError(f"No CIK found for symbol {symbol} ({sec_ticker})")
        return cik

    def fetch_companyfacts(self, symbol: str) -> FundamentalsFetchResult:
        """Fetch and parse companyfacts for one symbol."""
        retrieved_at = datetime.now(timezone.utc)
        cik = self.get_cik(symbol)
        url = COMPANYFACTS_URL.format(cik=cik)
        raw = self._get(url)
        snapshots = parse_companyfacts(symbol, raw, retrieved_at)
        warnings = []
        if not snapshots:
            warnings.append(
                f"companyfacts had no usable 10-K/10-Q periods for {symbol}; "
                "surfacing empty result (no fabrication)."
            )
        return FundamentalsFetchResult(
            symbol=symbol,
            source="sec_edgar",
            retrieved_at=retrieved_at,
            request_urls=[COMPANY_TICKERS_URL, url],
            raw_payloads={"companyfacts": raw},
            snapshots=snapshots,
            warnings=warnings,
        )
