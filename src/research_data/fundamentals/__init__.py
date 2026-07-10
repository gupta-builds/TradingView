"""Minimal fundamentals path: FMP + SEC EDGAR → provenance-stamped snapshots.

Just enough for the quality/valuation factors: revenue, operating income,
operating cash flow, capex (→ FCF), debt, cash, equity, shares outstanding.
Parsing is pure and offline-testable; live clients are thin and keyed via
environment variables (FMP_API_KEY, SEC_USER_AGENT). Missing fields stay
None — they are never imputed.
"""

from research_data.fundamentals.models import (
    FundamentalsFetchResult,
    FundamentalsSnapshot,
)
from research_data.fundamentals.store import FundamentalsStore, to_factor_inputs
from research_data.fundamentals.fmp import FMPFundamentalsClient, parse_fmp_statements
from research_data.fundamentals.sec import SECEdgarClient, parse_companyfacts

__all__ = [
    "FMPFundamentalsClient",
    "FundamentalsFetchResult",
    "FundamentalsSnapshot",
    "FundamentalsStore",
    "SECEdgarClient",
    "parse_companyfacts",
    "parse_fmp_statements",
    "to_factor_inputs",
]
