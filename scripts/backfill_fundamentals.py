#!/usr/bin/env python
"""Backfill SEC quarterly fundamentals depth to match a deepened price window.

Phase 2b V5 (Docs/PHASE2B_SOLUTION_DESIGN.md §1-2): earliest quarterly
`fiscal_period_end` must reach at or before the tier target for all 10
equities (BRKB is SEC-only; ETFs stay empty by design — no fundamentals for
index funds). `SECEdgarClient.fetch_companyfacts` already exists; its
default `max_periods=12` mixes quarterly + annual periods and caps quarterly
depth at ~8-10, which is why the live DB was shallow. This script just raises
that cap so more of SEC's own filing history is kept -- never fabricates a
period SEC did not file, never touches gate/hook code.

Usage:
  source .venv/bin/activate
  python scripts/backfill_fundamentals.py --max-periods 32
  python scripts/backfill_fundamentals.py --symbols AAPL MSFT --max-periods 32
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

from research_data.config import load_config
from research_data.env import load_dotenv
from research_data.fundamentals import FundamentalsStore, SECEdgarClient
from research_data.fundamentals.sec import SECEdgarError

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(PROJECT_ROOT / "data" / "market.duckdb"))
    parser.add_argument(
        "--max-periods",
        type=int,
        default=32,
        help="Combined quarterly+annual periods to keep per equity (SEC's own history is the ceiling)",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Equities to backfill (default: all equities in config/assets.toml; ETFs excluded)",
    )
    args = parser.parse_args()

    config = load_config()
    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        symbols = sorted(
            symbol
            for symbol, asset in config.universe.assets.items()
            if asset.asset_type == "equity"
        )

    client = SECEdgarClient()
    con = duckdb.connect(args.db_path)
    try:
        store = FundamentalsStore(con)
        for symbol in symbols:
            try:
                result = client.fetch_companyfacts(symbol, max_periods=args.max_periods)
            except SECEdgarError as e:
                print(f"{symbol}: FAILED ({e})")
                continue
            stored = store.upsert_snapshots(result.snapshots)
            quarters = [s for s in result.snapshots if s.period_type == "quarter"]
            earliest_q = min((s.fiscal_period_end for s in quarters), default=None)
            warn = f" warnings={result.warnings}" if result.warnings else ""
            print(
                f"{symbol}: stored={stored} quarters={len(quarters)} "
                f"earliest_quarter={earliest_q}{warn}"
            )
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
