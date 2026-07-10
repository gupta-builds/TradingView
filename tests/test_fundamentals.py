"""Fundamentals path tests: parsing, storage, factor-input assembly, guards.

All offline — live clients are only tested for their fail-closed behavior
when keys/identities are absent.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from research_data.fundamentals import (
    FMPFundamentalsClient,
    FundamentalsSnapshot,
    FundamentalsStore,
    SECEdgarClient,
    parse_companyfacts,
    parse_fmp_statements,
    to_factor_inputs,
)
from research_data.fundamentals.fmp import FMPError
from research_data.fundamentals.sec import SECEdgarError

FIXTURES = Path(__file__).parent / "fixtures" / "fundamentals"
RETRIEVED_AT = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def fmp_snapshots() -> list[FundamentalsSnapshot]:
    return parse_fmp_statements(
        "AAPL",
        (FIXTURES / "AAPL_fmp_income.json").read_text(),
        (FIXTURES / "AAPL_fmp_balance.json").read_text(),
        (FIXTURES / "AAPL_fmp_cashflow.json").read_text(),
        RETRIEVED_AT,
    )


# -- FMP parsing ---------------------------------------------------------------


def test_fmp_parses_all_periods(fmp_snapshots) -> None:
    assert len(fmp_snapshots) == 3
    by_end = {s.fiscal_period_end: s for s in fmp_snapshots}
    annual = by_end[date(2025, 9, 27)]
    assert annual.period_type == "annual"
    assert annual.revenue == 391e9
    assert annual.operating_cash_flow == 118e9
    assert annual.capex == 11e9  # stored as positive magnitude
    q2 = by_end[date(2026, 3, 28)]
    assert q2.period_type == "quarter"
    assert q2.total_debt == 98e9
    assert q2.operating_margin == pytest.approx(29.5 / 95.0)


def test_fmp_snapshots_carry_provenance(fmp_snapshots) -> None:
    for snapshot in fmp_snapshots:
        assert snapshot.source == "fmp"
        assert len(snapshot.raw_payload_hash) == 64
        assert snapshot.retrieved_at == RETRIEVED_AT


def test_fmp_parse_rejects_malformed_json() -> None:
    with pytest.raises(FMPError, match="Invalid JSON"):
        parse_fmp_statements("AAPL", "{not json", "[]", "[]", RETRIEVED_AT)
    with pytest.raises(FMPError, match="shape"):
        parse_fmp_statements("AAPL", '{"a": 1}', "[]", "[]", RETRIEVED_AT)


def test_fmp_empty_payloads_yield_no_snapshots() -> None:
    assert parse_fmp_statements("AAPL", "[]", "[]", "[]", RETRIEVED_AT) == []


def test_fmp_live_client_fails_closed_without_key(monkeypatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    with pytest.raises(FMPError, match="FMP_API_KEY"):
        FMPFundamentalsClient().fetch_statements("AAPL")


# -- SEC parsing -----------------------------------------------------------------


def test_sec_parses_companyfacts_periods() -> None:
    snapshots = parse_companyfacts(
        "AAPL", (FIXTURES / "AAPL_companyfacts.json").read_text(), RETRIEVED_AT
    )
    by_key = {(s.fiscal_period_end, s.period_type): s for s in snapshots}
    annual = by_key[(date(2025, 9, 27), "annual")]
    assert annual.revenue == 391e9
    assert annual.operating_cash_flow == 118e9
    assert annual.capex == 11e9
    assert annual.total_debt == 96e9
    assert annual.total_equity == 65e9
    quarter = by_key[(date(2026, 3, 28), "quarter")]
    assert quarter.revenue == 95e9
    assert quarter.shares_outstanding == 15e9


def test_sec_ignores_non_10k_10q_forms() -> None:
    snapshots = parse_companyfacts(
        "AAPL", (FIXTURES / "AAPL_companyfacts.json").read_text(), RETRIEVED_AT
    )
    # The 8-K FY2024 revenue entry must not create a period.
    assert not any(s.fiscal_period_end == date(2024, 9, 28) for s in snapshots)


def test_sec_parse_rejects_malformed_json() -> None:
    with pytest.raises(SECEdgarError, match="Invalid"):
        parse_companyfacts("AAPL", "{oops", RETRIEVED_AT)


def test_sec_live_client_fails_closed_without_user_agent(monkeypatch) -> None:
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SECEdgarError, match="SEC_USER_AGENT"):
        SECEdgarClient().fetch_companyfacts("AAPL")


# -- store ------------------------------------------------------------------------


def test_store_roundtrip_and_idempotent_upsert(fmp_snapshots) -> None:
    conn = duckdb.connect(":memory:")
    store = FundamentalsStore(conn)
    store.init_schema()
    assert store.upsert_snapshots(fmp_snapshots) == 3
    # Second upsert of the same periods replaces, not duplicates.
    store.upsert_snapshots(fmp_snapshots)
    loaded = store.get_snapshots("AAPL", source="fmp")
    assert len(loaded) == 3
    assert loaded[0].fiscal_period_end < loaded[-1].fiscal_period_end
    assert loaded[-1].retrieved_at == RETRIEVED_AT

    quarters = store.get_snapshots("AAPL", period_type="quarter")
    assert len(quarters) == 2


# -- factor-input assembly -----------------------------------------------------------


def test_to_factor_inputs_uses_latest_fields_and_quarterly_margins(fmp_snapshots) -> None:
    inputs = to_factor_inputs("AAPL", fmp_snapshots)
    assert inputs is not None
    assert inputs.as_of == date(2026, 3, 28)
    assert inputs.total_debt == 98e9
    assert inputs.operating_cash_flow == 28e9
    assert inputs.fcf == 28e9 - 2.9e9
    # Margins come from the two quarterly periods only.
    assert len(inputs.operating_margins) == 2


def test_to_factor_inputs_empty_is_none() -> None:
    assert to_factor_inputs("VOO", []) is None


def test_fmp_and_sec_agree_on_shared_fields() -> None:
    """Cross-provider sanity: the two parsers must produce comparable numbers
    for the same underlying periods (fixtures encode the same statements)."""
    fmp = parse_fmp_statements(
        "AAPL",
        (FIXTURES / "AAPL_fmp_income.json").read_text(),
        (FIXTURES / "AAPL_fmp_balance.json").read_text(),
        (FIXTURES / "AAPL_fmp_cashflow.json").read_text(),
        RETRIEVED_AT,
    )
    sec = parse_companyfacts(
        "AAPL", (FIXTURES / "AAPL_companyfacts.json").read_text(), RETRIEVED_AT
    )
    fmp_annual = next(s for s in fmp if s.period_type == "annual")
    sec_annual = next(s for s in sec if s.period_type == "annual")
    assert fmp_annual.revenue == sec_annual.revenue
    assert fmp_annual.operating_cash_flow == sec_annual.operating_cash_flow
    assert fmp_annual.capex == sec_annual.capex
